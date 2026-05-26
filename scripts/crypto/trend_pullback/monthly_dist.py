"""Monthly distribution of impulses passing 1W MA20 slope>0 gate.

Run:
  .venv/Scripts/python.exe -m scripts.trend_pullback.monthly_dist
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main():
    from scripts._common.run_helper import parse_args
    out_dir, _, args = parse_args(None, {}, "monthly_dist")
    events_path = out_dir / "events.parquet"
    if not events_path.exists():
        print(f"events parquet not found: {events_path}")
        return 1
    ev = pd.read_parquet(events_path)
    print(f"total events: {len(ev)}")

    ev["dt"] = pd.to_datetime(ev["impulse_ts"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul")
    ev["year_month"] = ev["dt"].dt.strftime("%Y-%m")

    monthly = ev.groupby("year_month").agg(
        n_impulses=("impulse_idx", "count"),
        n_symbols=("symbol", "nunique"),
        mean_168h_imp=("fwd_168h_imp", "mean"),
        median_168h_imp=("fwd_168h_imp", "median"),
        mean_168h_ma10=("fwd_168h_ma10", "mean"),
        median_168h_ma10=("fwd_168h_ma10", "median"),
        win_168h_ma10=("fwd_168h_ma10", lambda x: (x.dropna() > 0).mean()),
        n_touched=("touched_ma10", "sum"),
    ).reset_index()

    print("\n=== monthly impulse counts (1W MA20 slope>0 gate) ===")
    disp = monthly.copy()
    for c in ["mean_168h_imp", "median_168h_imp", "mean_168h_ma10", "median_168h_ma10"]:
        disp[c] = disp[c].apply(lambda x: f"{x*100:+.2f}%" if pd.notna(x) else "-")
    disp["win_168h_ma10"] = disp["win_168h_ma10"].apply(
        lambda x: f"{x*100:.0f}%" if pd.notna(x) else "-")
    with pd.option_context("display.max_rows", None, "display.width", 240):
        print(disp.to_string(index=False))

    # quick year totals
    ev["year"] = ev["dt"].dt.year
    yearly = ev.groupby("year").agg(
        n_impulses=("impulse_idx", "count"),
        n_symbols=("symbol", "nunique"),
    ).reset_index()
    print("\n=== yearly totals ===")
    print(yearly.to_string(index=False))

    monthly.to_csv(out_dir / "monthly_dist.csv", index=False)
    print(f"\nsaved: {OUT_DIR / 'monthly_dist.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
