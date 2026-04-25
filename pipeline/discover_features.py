"""
Discover the two most predictive columns for creative performance (ipm).

Usage:
    python -m pipeline.discover_features

Run build_table.py first to generate creative_features.parquet.
Share the two top columns with the whole team and add them to SCHEMA.md.
"""
import pandas as pd
from pathlib import Path

PARQUET = Path("pipeline/creative_features.parquet")
TARGET = "ipm"

SKIP_COLS = {"creative_id", "campaign_id", "image_path", "asset_file",
             "first_date", "last_date", "creative_launch_date"}


def main():
    if not PARQUET.exists():
        print(f"Missing {PARQUET} — run `python -m pipeline.build_table` first.")
        return

    df = pd.read_parquet(PARQUET)
    print(f"Loaded {len(df)} creatives from {PARQUET}\n")

    if TARGET not in df.columns:
        print(f"Target column '{TARGET}' not found. Available: {list(df.columns)}")
        return

    # Numerical correlations
    num_cols = [c for c in df.select_dtypes("number").columns if c not in SKIP_COLS]
    corr = df[num_cols].corrwith(df[TARGET]).abs().sort_values(ascending=False)
    print(f"Top numerical predictors of {TARGET}:")
    print(corr.drop(TARGET, errors="ignore").head(12).to_string())
    print()

    # Categorical group variance
    print(f"Categorical columns — std of mean {TARGET} across groups (higher = more predictive):")
    cat_results = []
    for col in df.select_dtypes("object").columns:
        if col in SKIP_COLS:
            continue
        try:
            var = df.groupby(col)[TARGET].mean().std()
            cat_results.append((col, var))
        except Exception:
            pass
    for col, var in sorted(cat_results, key=lambda x: x[1], reverse=True):
        print(f"  {col:40s} {var:.6f}")

    print("\n>>> Top entries above are the two most predictive columns.")
    print(">>> Document them in SCHEMA.md and share with the team.\n")


if __name__ == "__main__":
    main()
