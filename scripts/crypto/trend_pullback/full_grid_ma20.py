"""3-axis grid: upper_wick × bars_to_touch × angle quantile.

All entries measured from MA10 touch bar close (= purchase moment).
1D MA20 gate already applied (events parquet pre-filtered).

W groups:  W_low (≤1%),  W_mid (1-5%),  W_high (>5%)
bars:      1-3 / 4-6 / 7-10
angle:     Q5 steepest .. Q1 flattest (per-bars-group quantile)

Run:
  .venv/Scripts/python.exe -m scripts.trend_pullback.full_grid
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

WICK_BINS = [-1e-9, 0.01, 0.05, np.inf]
WICK_LABELS = ["W_low ≤1%", "W_mid 1-5%", "W_high >5%"]

BARS_BINS = [(1, 7), (8, 14), (15, 20)]
Q_PROBS = [0.20, 0.40, 0.60, 0.80]
Q_LABELS = ["Q5 steepest", "Q4", "Q3 median", "Q2", "Q1 flattest"]


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


def cell_stats(grp: pd.DataFrame, h: int = 168, col_suffix: str = "ma20") -> dict:
    col = f"fwd_{h}h_{col_suffix}"
    s = grp[col].dropna()
    if len(s) == 0:
        return {"n": 0, "mean": np.nan, "median": np.nan, "win": np.nan}
    return {"n": int(len(s)),
            "mean": float(s.mean()),
            "median": float(s.median()),
            "win": float((s > 0).mean())}


def main():
    from scripts._common.run_helper import parse_args
    out_dir, _, args = parse_args(None, {}, "full_grid_ma20")
    events_path = out_dir / "events.parquet"
    if not events_path.exists():
        print(f"events parquet not found: {events_path}")
        return 1
    events = pd.read_parquet(events_path)
    print(f"events: {len(events)}")
    events = add_impulse_high(events)
    events["_wbin"] = pd.cut(events["upper_wick_pct"], bins=WICK_BINS, labels=WICK_LABELS,
                              include_lowest=True, right=True)

    # touched / untouched split
    untouched = events[~events["touched_ma20"]].copy()
    print(f"MA10 UNtouched within 10: {len(untouched)} (fwd = fr i+20 close)")

    ev = events[events["touched_ma20"]].copy()
    print(f"MA10 touched: {len(ev)}")

    # bars bin
    def bars_label(b):
        for lo, hi in BARS_BINS:
            if lo <= b <= hi:
                return f"bars {lo:>2}-{hi:>2}"
        return None
    # UNTCH lookback for ma20 is 20 (not 10)
    ev["_bbin"] = ev["bars_to_touch_ma20"].apply(bars_label)

    # angle quantile per bars-group (global across all W groups in that bars range)
    angle_q_by_bars = {}
    for lo, hi in BARS_BINS:
        sub = ev[(ev["bars_to_touch_ma20"] >= lo) & (ev["bars_to_touch_ma20"] <= hi)]
        angle_q_by_bars[(lo, hi)] = sub["angle_per_bar_ma20"].quantile(Q_PROBS).values

    def angle_label(row):
        b = row["bars_to_touch_ma20"]
        a = row["angle_per_bar_ma20"]
        if pd.isna(a):
            return None
        for lo, hi in BARS_BINS:
            if lo <= b <= hi:
                qs = angle_q_by_bars[(lo, hi)]
                edges = [-np.inf] + list(qs) + [np.inf]
                for i in range(5):
                    if edges[i] < a <= edges[i + 1] or (i == 0 and a <= edges[1]):
                        return Q_LABELS[i]
        return None
    ev["_qbin"] = ev.apply(angle_label, axis=1)

    # build 3-axis table (touched cells + 1 untouched cell per wick)
    rows = []
    for wlabel in WICK_LABELS:
        for lo, hi in BARS_BINS:
            for qlabel in Q_LABELS:
                cell = ev[(ev["_wbin"] == wlabel) &
                           (ev["_bbin"] == f"bars {lo:>2}-{hi:>2}") &
                           (ev["_qbin"] == qlabel)]
                row = {"wick": wlabel,
                        "bars": f"{lo}-{hi}",
                        "angle": qlabel}
                for h in HORIZONS:
                    st = cell_stats(cell, h, "ma20")
                    if h == HORIZONS[-1]:
                        row["n"] = st["n"]
                    row[f"{h}h_mean"] = st["mean"]
                    row[f"{h}h_med"] = st["median"]
                    row[f"{h}h_win"] = st["win"]
                rows.append(row)
        # untouched cell for this wick - fwd from cf20 (i+20 close)
        un_cell = untouched[untouched["_wbin"] == wlabel]
        row = {"wick": wlabel, "bars": "UNTCH", "angle": "(fr i+20)"}
        for h in HORIZONS:
            st = cell_stats(un_cell, h, "cf20")
            if h == HORIZONS[-1]:
                row["n"] = st["n"]
            row[f"{h}h_mean"] = st["mean"]
            row[f"{h}h_med"] = st["median"]
            row[f"{h}h_win"] = st["win"]
        rows.append(row)
    grid = pd.DataFrame(rows)
    grid.to_csv(out_dir / "full_grid_ma20_summary.csv", index=False, encoding="utf-8")

    # quantile edges for context
    print("\nAngle quantile edges by bars group (per-bars, across all W):")
    for (lo, hi), qs in angle_q_by_bars.items():
        print(f"  bars {lo}-{hi}: q20={qs[0]*100:+.2f}%/봉, q40={qs[1]*100:+.2f}%, "
              f"q60={qs[2]*100:+.2f}%, q80={qs[3]*100:+.2f}%")

    # full grid - ordered by wick > bars > angle (natural order)
    BARS_ORDER = {"1-3": 0, "4-6": 1, "7-10": 2, "UNTCH": 3}
    Q_ORDER = {l: i for i, l in enumerate(Q_LABELS)}
    Q_ORDER["(fr i+20)"] = 99
    W_ORDER = {l: i for i, l in enumerate(WICK_LABELS)}
    grid["_w"] = grid["wick"].map(W_ORDER)
    grid["_b"] = grid["bars"].map(BARS_ORDER)
    grid["_q"] = grid["angle"].map(Q_ORDER)
    view = grid.sort_values(["_w", "_b", "_q"]).reset_index(drop=True).drop(columns=["_w", "_b", "_q"])
    print(f"\n=== full grid ({len(view)} cells), wick > bars > angle order ===")
    pct_cols = []
    for h in HORIZONS:
        pct_cols += [f"{h}h_mean", f"{h}h_med"]
    win_cols = [f"{h}h_win" for h in HORIZONS]
    disp = view[["wick", "bars", "angle", "n"] + pct_cols + win_cols].copy()
    for c in pct_cols:
        disp[c] = disp[c].apply(lambda x: f"{x*100:+.2f}%" if pd.notna(x) else "-")
    for c in win_cols:
        disp[c] = disp[c].apply(lambda x: f"{x*100:.0f}%" if pd.notna(x) else "-")
    with pd.option_context("display.max_rows", None,
                            "display.max_columns", None,
                            "display.width", 240):
        print(disp.to_string(index=False))

    print(f"\nsaved: {OUT_DIR / 'full_grid_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
