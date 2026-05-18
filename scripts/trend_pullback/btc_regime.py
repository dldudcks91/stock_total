"""BTC regime × impulse size cross-tab.

Tests two hypotheses for why baseline (impulse close entry) is net-negative:
  H1: market regime - bear market => negative drift after impulse
  H2: mean reversion - large 1H impulses pump-and-dump regardless of regime

Each impulse gets BTC's state at that timestamp (above 1D MA50, 30d return).
Forward returns measured from impulse close (= fwd_*_imp columns already
present in events parquet).

Run:
  .venv/Scripts/python.exe -m scripts.trend_pullback.btc_regime
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

HORIZONS = [1, 6, 24, 72, 168]
SIZE_BINS = [0.10, 0.12, 0.15, 0.20, np.inf]
SIZE_LABELS = ["S1 10-12%", "S2 12-15%", "S3 15-20%", "S4 >20%"]


def load_btc_state() -> pd.DataFrame:
    from data.resample import load as load_resampled
    btc = load_resampled("BTCUSDT", "1d")
    btc = btc.sort_values("timestamp").reset_index(drop=True)
    btc["btc_ma50"] = btc["close"].rolling(50).mean().shift(1)
    btc["btc_above_ma50"] = btc["close"] > btc["btc_ma50"]
    btc["btc_30d_ret"] = btc["close"].pct_change(30).shift(1)
    return btc[["timestamp", "btc_above_ma50", "btc_30d_ret"]].rename(
        columns={"timestamp": "impulse_ts"})


def _stats(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"mean": np.nan, "median": np.nan, "win": np.nan}
    return {"mean": float(s.mean()), "median": float(s.median()),
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


def fmt_table(rows, label: str) -> None:
    df = pd.DataFrame(rows)
    print(f"\n=== {label} ===")
    cols = ["group", "n"] + [f"{h}h_mean" for h in HORIZONS] + \
           [f"{h}h_med" for h in HORIZONS] + \
           [f"{h}h_win" for h in HORIZONS]
    disp = df[cols].copy()
    for h in HORIZONS:
        for k in ("mean", "med"):
            c = f"{h}h_{k}"
            disp[c] = disp[c].apply(lambda x: f"{x*100:+.2f}%" if pd.notna(x) else "-")
        c = f"{h}h_win"
        disp[c] = disp[c].apply(lambda x: f"{x*100:.0f}%" if pd.notna(x) else "-")
    with pd.option_context("display.max_columns", None, "display.width", 240):
        print(disp.to_string(index=False))


def main() -> int:
    from scripts._common.run_helper import parse_args
    out_dir, _, args = parse_args(None, {}, "btc_regime")
    events_path = out_dir / "events.parquet"
    if not events_path.exists():
        print(f"events parquet not found: {events_path}")
        return 1
    events = pd.read_parquet(events_path)
    print(f"events: {len(events)}")

    btc_state = load_btc_state()
    events_sorted = events.sort_values("impulse_ts").reset_index(drop=True)
    ev = pd.merge_asof(events_sorted, btc_state.sort_values("impulse_ts"),
                        on="impulse_ts", direction="backward")
    n_with_btc = ev["btc_above_ma50"].notna().sum()
    print(f"events with BTC regime joined: {n_with_btc}")

    # bins
    ev["_sbin"] = pd.cut(ev["impulse_ret"], bins=SIZE_BINS, labels=SIZE_LABELS, right=False)

    # ---- single-axis tables ----
    rows = []
    rows.append(_row(ev, "ALL impulses"))
    rows.append(_row(ev[ev["btc_above_ma50"] == True], "BTC > MA50 (bull)"))
    rows.append(_row(ev[ev["btc_above_ma50"] == False], "BTC <= MA50 (bear)"))
    fmt_table(rows, "by BTC regime")

    rows = []
    rows.append(_row(ev, "ALL impulses"))
    for s in SIZE_LABELS:
        rows.append(_row(ev[ev["_sbin"] == s], f"size {s}"))
    fmt_table(rows, "by impulse size")

    # BTC 30d return quartiles
    q = ev["btc_30d_ret"].quantile([0.25, 0.5, 0.75]).values
    print(f"\nBTC 30d return quartiles: q25={q[0]*100:+.1f}%, q50={q[1]*100:+.1f}%, q75={q[2]*100:+.1f}%")
    btc_ret_labels = ["BTC30 Q1 worst", "BTC30 Q2", "BTC30 Q3", "BTC30 Q4 best"]
    ev["_btcq"] = pd.cut(ev["btc_30d_ret"],
                          bins=[-np.inf, q[0], q[1], q[2], np.inf],
                          labels=btc_ret_labels, include_lowest=True, right=True)
    rows = [_row(ev, "ALL impulses")]
    for label in btc_ret_labels:
        rows.append(_row(ev[ev["_btcq"] == label], label))
    fmt_table(rows, "by BTC 30d return quartile")

    # ---- 2-axis: BTC regime × size ----
    rows = []
    for regime, regime_label in [(True, "bull"), (False, "bear")]:
        for s in SIZE_LABELS:
            cell = ev[(ev["btc_above_ma50"] == regime) & (ev["_sbin"] == s)]
            rows.append(_row(cell, f"  BTC {regime_label} × {s}"))
    fmt_table(rows, "2-axis: BTC regime × impulse size")

    # ---- 2-axis: BTC 30d quartile × size ----
    rows = []
    for label in btc_ret_labels:
        for s in SIZE_LABELS:
            cell = ev[(ev["_btcq"] == label) & (ev["_sbin"] == s)]
            rows.append(_row(cell, f"  {label} × {s}"))
    fmt_table(rows, "2-axis: BTC 30d quartile × impulse size")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
