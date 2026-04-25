"""
Build creative_features.parquet for a single campaign.

Usage:
    python -m pipeline.build_table

Reads DATA_DIR from .env. Writes pipeline/creative_features.parquet.
Automatically picks the campaign with n_creatives >= 10, n_days >= 30, highest spend
unless CAMPAIGN_ID is already set in .env.
"""
import os
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from scipy.stats import linregress

load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "./Smadex_Creative_Intelligence_Dataset_FULL"))
IMAGES_DIR = Path(os.getenv("IMAGES_DIR", str(DATA_DIR / "assets")))
OUT_PATH = Path("pipeline/creative_features.parquet")
CAMPAIGN_ID = os.getenv("CAMPAIGN_ID", "")


def pick_campaign() -> str:
    daily_path = str(DATA_DIR / "creative_daily_country_os_stats.csv")
    con = duckdb.connect()
    row = con.execute(f"""
        SELECT campaign_id,
               COUNT(DISTINCT creative_id) AS n_creatives,
               COUNT(DISTINCT date)        AS n_days,
               SUM(spend_usd)              AS total_spend
        FROM read_csv_auto('{daily_path}')
        GROUP BY campaign_id
        HAVING n_creatives >= 10 AND n_days >= 30
        ORDER BY total_spend DESC
        LIMIT 1
    """).fetchone()

    if not row:
        raise ValueError("No campaign meets criteria (n_creatives >= 10, n_days >= 30)")

    cid = str(row[0])
    print(f"Auto-selected campaign {cid} | {row[1]} creatives | {row[2]} days | ${row[3]:,.0f} spend")
    print(f"  → Add to .env: CAMPAIGN_ID={cid}")
    return cid


def compute_ctr_slope_7d(daily: pd.DataFrame) -> pd.Series:
    """Linear slope of daily CTR over the last 7 days, keyed by creative_id."""
    daily = daily.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    agg = daily.groupby(["creative_id", "date"]).agg(
        impressions=("impressions", "sum"),
        clicks=("clicks", "sum"),
    ).reset_index()
    agg["ctr"] = agg["clicks"] / agg["impressions"].clip(lower=1)

    slopes: dict[str | int, float] = {}
    for cid, grp in agg.groupby("creative_id"):
        last7 = grp.nlargest(7, "date").sort_values("date")
        if len(last7) < 2:
            slopes[cid] = 0.0
            continue
        x = np.arange(len(last7), dtype=float)
        y = last7["ctr"].values
        try:
            slope, *_ = linregress(x, y)
            slopes[cid] = float(slope)
        except Exception:
            slopes[cid] = 0.0

    return pd.Series(slopes, name="ctr_slope_7d")


def build(campaign_id: str) -> pd.DataFrame:
    con = duckdb.connect()
    cid = int(campaign_id)

    summary = con.execute(f"""
        SELECT * FROM read_csv_auto('{DATA_DIR / "creative_summary.csv"}')
        WHERE campaign_id = {cid}
    """).df()

    daily = con.execute(f"""
        SELECT * FROM read_csv_auto('{DATA_DIR / "creative_daily_country_os_stats.csv"}')
        WHERE campaign_id = {cid}
    """).df()

    campaign_meta = con.execute(f"""
        SELECT * FROM read_csv_auto('{DATA_DIR / "campaigns.csv"}')
        WHERE campaign_id = {cid}
    """).df()

    print(f"  {len(summary)} creatives | {len(daily)} daily rows")

    slopes = compute_ctr_slope_7d(daily)
    df = summary.merge(
        slopes.reset_index().rename(columns={"index": "creative_id"}),
        on="creative_id",
        how="left",
    )
    df["ctr_slope_7d"] = df["ctr_slope_7d"].fillna(0.0)

    # Standardise column names to match agent-expected schema
    df = df.rename(columns={
        "total_spend_usd": "spend",
        "total_impressions": "impressions",
        "total_clicks": "clicks",
        "total_conversions": "installs",
        "overall_ctr": "ctr",
        "overall_cvr": "cvr",
        "overall_ipm": "ipm",
        "total_days_active": "active_days",
    })

    df["creative_id"] = df["creative_id"].astype(str)
    df["campaign_id"] = df["campaign_id"].astype(str)
    df["cpi"] = df["spend"] / df["installs"].clip(lower=1)
    df["creative_age_days"] = df["active_days"]

    df["creative_launch_date"] = pd.to_datetime(df["creative_launch_date"])
    df["first_date"] = df["creative_launch_date"]
    df["last_date"] = df["first_date"] + pd.to_timedelta(df["active_days"] - 1, unit="d")

    # Percentile ranks within campaign
    for src, out in [("ctr", "ctr_pct"), ("ipm", "ipm_pct"), ("spend", "spend_pct"), ("cvr", "cvr_pct")]:
        df[out] = df[src].rank(pct=True)

    # Absolute image paths
    df["image_path"] = df["asset_file"].apply(
        lambda p: str((DATA_DIR / p).resolve())
    )

    # Attach campaign-level metadata columns
    if len(campaign_meta):
        meta = campaign_meta.iloc[0]
        for col in ["target_os", "countries", "objective", "kpi_goal", "target_age_segment"]:
            if col in meta.index:
                df[col] = meta[col]

    return df


def main():
    campaign_id = CAMPAIGN_ID or pick_campaign()
    df = build(campaign_id)

    OUT_PATH.parent.mkdir(exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"\nWritten {len(df)} rows → {OUT_PATH}")
    print("\nSchema sample:")
    print(df[["creative_id", "ctr", "ipm", "spend", "installs",
              "ctr_pct", "ipm_pct", "ctr_slope_7d", "active_days"]].head().to_string())


if __name__ == "__main__":
    main()
