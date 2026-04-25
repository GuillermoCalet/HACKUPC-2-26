"""
Build creative_features.parquet for a single campaign.

Joins creative_summary.csv + campaigns.csv on campaign_id.
Cleans the 10% dirty data (fatigue_day nulls) and adds manager-friendly
derived columns so non-technical users can read the output directly.

Usage:
    python -m pipeline.build_table

Reads DATA_DIR from .env. Writes pipeline/creative_features.parquet.
Automatically picks the campaign with n_creatives >= 6, n_days >= 30, highest spend
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
MIN_CREATIVES = int(os.getenv("MIN_CREATIVES", "6"))
MIN_DAYS = int(os.getenv("MIN_DAYS", "30"))


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
        HAVING n_creatives >= {MIN_CREATIVES} AND n_days >= {MIN_DAYS}
        ORDER BY total_spend DESC
        LIMIT 1
    """).fetchone()

    if not row:
        best = con.execute(f"""
            SELECT campaign_id,
                   COUNT(DISTINCT creative_id) AS n_creatives,
                   COUNT(DISTINCT date)        AS n_days,
                   SUM(spend_usd)              AS total_spend
            FROM read_csv_auto('{daily_path}')
            GROUP BY campaign_id
            ORDER BY n_creatives DESC, n_days DESC, total_spend DESC
            LIMIT 1
        """).fetchone()
        suffix = ""
        if best:
            suffix = (
                f"; best available campaign is {best[0]} "
                f"({best[1]} creatives, {best[2]} days)"
            )
        raise ValueError(
            "No campaign meets criteria "
            f"(n_creatives >= {MIN_CREATIVES}, n_days >= {MIN_DAYS}){suffix}"
        )

    cid = str(row[0])
    print(f"Auto-selected campaign {cid} | {row[1]} creatives | {row[2]} days | ${row[3]:,.0f} spend")
    print(f"  → Add to .env: CAMPAIGN_ID={cid}")
    return cid


def compute_ctr_slope_7d(daily: pd.DataFrame) -> pd.Series:
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


def _clean_fatigue(df: pd.DataFrame) -> pd.DataFrame:
    """
    fatigue_day is null for the ~88% of creatives that are not fatigued.
    Strategy: create is_fatigued (bool) + fill fatigue_day with 0 for non-fatigued.
    This lets a manager filter/sort without being confused by nulls.
    """
    df["is_fatigued"] = df["creative_status"] == "fatigued"
    df["fatigue_day"] = df["fatigue_day"].fillna(0).astype(int)
    return df


def _add_manager_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Derived columns designed for non-technical readers (managers / directius).
    All values are human-readable: percentages, labels, plain-text comparisons.
    """
    # Plain-text performance label for the UI (replaces raw perf_score for managers)
    def _perf_label(row):
        status = row["creative_status"]
        if status == "top_performer":
            return "Top performer"
        if status == "fatigued":
            return f"Fatigued (day {row['fatigue_day']})"
        if status == "underperformer":
            return "Underperformer"
        return "Stable"

    df["performance_label"] = df.apply(_perf_label, axis=1)

    # Spend share within the campaign (what % of budget went to this creative)
    campaign_total = df["spend"].sum()
    df["spend_share_pct"] = (df["spend"] / campaign_total * 100).round(1) if campaign_total > 0 else 0.0

    # Days since fatigue onset — 0 if not fatigued
    df["days_since_fatigue"] = df.apply(
        lambda r: int(r["active_days"] - r["fatigue_day"]) if r["is_fatigued"] and r["fatigue_day"] > 0 else 0,
        axis=1,
    )

    return df


def build(campaign_id: str) -> pd.DataFrame:
    con = duckdb.connect()
    cid = int(campaign_id)

    # --- Load creative_summary (creative-level performance) ---
    creative_sum = con.execute(f"""
        SELECT * FROM read_csv_auto('{DATA_DIR / "creative_summary.csv"}')
        WHERE campaign_id = {cid}
    """).df()

    # --- Load campaigns context (pure configuration, no biased metrics) ---
    campaign_meta = con.execute(f"""
        SELECT * FROM read_csv_auto('{DATA_DIR / "campaigns.csv"}')
        WHERE campaign_id = {cid}
    """).df()
    # Drop overlapping metadata to avoid column duplication on merge
    campaign_meta = campaign_meta.drop(columns=["advertiser_name", "app_name", "vertical"], errors="ignore")

    # --- Load daily stats for slope calculation ---
    daily = con.execute(f"""
        SELECT * FROM read_csv_auto('{DATA_DIR / "creative_daily_country_os_stats.csv"}')
        WHERE campaign_id = {cid}
    """).df()

    print(f"  {len(creative_sum)} creatives | {len(daily)} daily rows | 1 campaign meta row")

    # --- Join creative_summary + campaigns.csv on campaign_id ---
    # campaign_id is the only key — one campaign row fans out to all its creatives
    df = creative_sum.merge(campaign_meta, on="campaign_id", how="left")

    # --- Add CTR slope (requires daily table) ---
    slopes = compute_ctr_slope_7d(daily)
    df = df.merge(
        slopes.reset_index().rename(columns={"index": "creative_id"}),
        on="creative_id",
        how="left",
    )
    df["ctr_slope_7d"] = df["ctr_slope_7d"].fillna(0.0)

    # --- Standardise column names to match agent-expected schema ---
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
    df["last_date"] = df["first_date"] + pd.to_timedelta(df["active_days"] - 1, unit="D")

    # Percentile ranks within campaign
    for src, out in [("ctr", "ctr_pct"), ("ipm", "ipm_pct"), ("spend", "spend_pct"), ("cvr", "cvr_pct")]:
        df[out] = df[src].rank(pct=True)

    # Absolute image paths
    df["image_path"] = df["asset_file"].apply(
        lambda p: str((DATA_DIR / p).resolve())
    )

    # --- Clean dirty 10%: fatigue_day nulls ---
    df = _clean_fatigue(df)

    # --- Add manager-friendly derived columns ---
    df = _add_manager_columns(df)

    return df


def main():
    campaign_id = CAMPAIGN_ID or pick_campaign()
    df = build(campaign_id)

    OUT_PATH.parent.mkdir(exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"\nWritten {len(df)} rows → {OUT_PATH}")
    print(f"Total columns: {len(df.columns)}")
    print()
    print("=== Performance overview (manager view) ===")
    print(df[["creative_id", "performance_label",
              "spend_share_pct", "days_since_fatigue"]].to_string(index=False))
    print()
    print("=== Campaign context columns added by join ===")
    camp_cols = ["campaign_id", "countries", "target_os", "objective",
                 "kpi_goal", "daily_budget_usd", "target_age_segment"]
    print(df[[c for c in camp_cols if c in df.columns]].iloc[0].to_string())


if __name__ == "__main__":
    main()
