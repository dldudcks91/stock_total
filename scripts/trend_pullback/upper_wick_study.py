"""Upper-wick filter on impulses: enter at impulse close immediately.

Hypothesis: when (high - close)/close is small, the impulse bar pushed all the
way to the high — strong buyer follow-through. Skip waiting for MA10 touch.

Reads angle_study_events.parquet (already filtered by 1D MA20 gate).

For each upper-wick bin, reports n, MEAN and MEDIAN of fwd_*_imp at each
horizon (1h, 6h, 24h, 72h, 168h). All from impulse close (= purchase moment).

Run:
  .venv/Scripts/python.exe -m scripts.trend_pullback.upper_wick_study
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "crypto" / "1h"

HORIZONS = [1, 6, 24, 72, 168]
WICK_BINS = [-1e-9, 0.005, 0.01, 0.02, 0.05, 0.10, np.inf]
WICK_LABELS = ["W1 ≤0.5%", "W2 0.5-1%", "W3 1-2%", "W4 2-5%", "W5 5-10%", "W6 >10%"]


def add_impulse_high(events: pd.DataFrame) -> pd.DataFrame:
    events = events.copy()
    events["impulse_high"] = np.nan
    for sym, grp in events.groupby("symbol"):
        path = CACHE_DIR / f"{sym}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path).sort_values("timestamp").reset_index(drop=True)
        highs = df["high"].to_numpy()
        idx = grp["impulse_idx"].astype(int).to_numpy()
        valid = (idx >= 0) & (idx < len(highs))
        events.loc[grp.index[valid], "impulse_high"] = highs[idx[valid]]
    events["upper_wick_pct"] = (events["impulse_high"] - events["impulse_close"]) / events["impulse_close"]
    return events


def _stats(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"mean": np.nan, "median": np.nan, "win": np.nan}
    return {"mean": float(s.mean()),
            "median": float(s.median()),
            "win": float((s > 0).mean())}


def _row(grp: pd.DataFrame, label: str) -> dict:
    out = {"group": label, "n": int(len(grp))}
    for h in HORIZONS:
        col = f"fwd_{h}h_imp"
        st = _stats(grp[col])
        out[f"{h}h_mean"] = st["mean"]
        out[f"{h}h_med"] = st["median"]
        out[f"{h}h_win"] = st["win"]
    return out


def main():
    from scripts._common.run_helper import parse_args, update_config, resolve_config_path
    out_dir, params, args = parse_args(None, {}, "upper_wick_study")
    events_path = out_dir / "events.parquet"
    if not events_path.exists():
        print(f"events parquet not found: {events_path}")
        print("run scripts.trend_pullback.angle_study with the same --config first")
        return 1
    events = pd.read_parquet(events_path)
    print(f"loaded {len(events)} events")

    events = add_impulse_high(events)
    n_valid = events["upper_wick_pct"].notna().sum()
    print(f"events with valid impulse_high: {n_valid}")
    print(f"upper_wick_pct distribution:")
    print(events["upper_wick_pct"].describe())

    # bin
    events["_wbin"] = pd.cut(events["upper_wick_pct"],
                              bins=WICK_BINS, labels=WICK_LABELS,
                              include_lowest=True, right=True)

    rows = []
    rows.append(_row(events, "ALL impulses (any wick)"))
    for label in WICK_LABELS:
        sub = events[events["_wbin"] == label]
        rows.append(_row(sub, label))

    summary = pd.DataFrame(rows)
    summary.to_csv(out_dir / "upper_wick_summary.csv", index=False, encoding="utf-8")

    # MEAN table
    print("\n=== MEAN forward returns (entry = impulse close) ===")
    cols = ["group", "n"] + [f"{h}h_mean" for h in HORIZONS]
    view = summary[cols].copy()
    for h in HORIZONS:
        view[f"{h}h_mean"] = view[f"{h}h_mean"].apply(
            lambda x: f"{x*100:+.2f}%" if pd.notna(x) else "-")
    print(view.to_string(index=False))

    # MEDIAN table (사용자 요청)
    print("\n=== MEDIAN forward returns (entry = impulse close) ===")
    cols = ["group", "n"] + [f"{h}h_med" for h in HORIZONS]
    view = summary[cols].copy()
    for h in HORIZONS:
        view[f"{h}h_med"] = view[f"{h}h_med"].apply(
            lambda x: f"{x*100:+.2f}%" if pd.notna(x) else "-")
    print(view.to_string(index=False))

    # win
    print("\n=== Win rate (>0) ===")
    cols = ["group", "n"] + [f"{h}h_win" for h in HORIZONS]
    view = summary[cols].copy()
    for h in HORIZONS:
        view[f"{h}h_win"] = view[f"{h}h_win"].apply(
            lambda x: f"{x*100:.0f}%" if pd.notna(x) else "-")
    print(view.to_string(index=False))

    print(f"\nsaved: {out_dir / 'upper_wick_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
