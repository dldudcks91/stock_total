"""Impulse size × forward return table.

Gate: 1W MA20 slope > 0 (lagged 1 week, no lookahead).
Impulse: (close - open) / close in size bins from 3% upward.
Forward horizons: 1h, 4h, 8h, 24h, 72h (3d), 168h (7d).
Entry: impulse bar close. Returns measured from there.

Run:
  .venv/Scripts/python.exe -m scripts.trend_pullback.size_table
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "crypto" / "1h"

HORIZONS = [1, 4, 8, 24, 72, 168]
H_LABELS = ["1h", "4h", "8h", "24h(1d)", "72h(3d)", "168h(7d)"]

# size bins: 1% steps from 3% to 20%, then 20%+
SIZE_EDGES = [x / 100 for x in range(3, 21)] + [np.inf]
SIZE_LABELS = [f"{i}-{i+1}%" for i in range(3, 20)] + ["20%+"]


def get_1w_ma20_slope(symbol: str) -> Optional[pd.DataFrame]:
    try:
        from data.resample import load as load_resampled
        df_1w = load_resampled(symbol, "1w")
    except Exception:
        return None
    if df_1w is None or len(df_1w) < 22:
        return None
    df_1w = df_1w.sort_values("timestamp").reset_index(drop=True)
    ma20 = df_1w["close"].rolling(20, min_periods=20).mean()
    df_1w["ma20_1w_slope_up"] = (ma20.diff() > 0).shift(1)
    return df_1w[["timestamp", "ma20_1w_slope_up"]].copy()


def find_events(symbol: str) -> Optional[pd.DataFrame]:
    path = CACHE_DIR / f"{symbol}.parquet"
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None
    if len(df) < 100:
        return None
    df = df.sort_values("timestamp").reset_index(drop=True)

    ma_df = get_1w_ma20_slope(symbol)
    if ma_df is None:
        return None
    df = pd.merge_asof(df, ma_df, on="timestamp", direction="backward")

    open_ = df["open"].astype("float64").to_numpy()
    close = df["close"].astype("float64").to_numpy()
    volume = df["volume"].astype("float64").to_numpy()
    slope_up = df["ma20_1w_slope_up"].fillna(False).to_numpy().astype(bool)
    n = len(df)

    # impulse size: (close - open) / open  (시가 기준)
    size = np.where(open_ > 0, (close - open_) / open_, np.nan)

    # volume filter: impulse bar volume >= 5 × prev-10-bar average
    vol_avg10 = pd.Series(volume).rolling(10, min_periods=10).mean().shift(1).to_numpy()
    vol_filter = np.where(np.isfinite(vol_avg10) & (vol_avg10 > 0),
                            volume >= vol_avg10 * 5, False)

    impulse_mask = (size >= 0.03) & slope_up & vol_filter & np.isfinite(size)
    idx = np.where(impulse_mask)[0]
    if idx.size == 0:
        return None

    rows = []
    for i in idx:
        row = {"symbol": symbol, "i": int(i),
                "ts": int(df["timestamp"].iloc[i]),
                "size": float(size[i]),
                "imp_close": float(close[i])}
        for h in HORIZONS:
            j = i + h
            row[f"fwd_{h}"] = float(close[j] / close[i] - 1.0) if j < n else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def collect_all() -> pd.DataFrame:
    symbols = sorted(p.stem for p in CACHE_DIR.glob("*.parquet"))
    print(f"symbols: {len(symbols)}")
    out = []
    t0 = time.time()
    for k, s in enumerate(symbols):
        ev = find_events(s)
        if ev is not None and len(ev) > 0:
            out.append(ev)
        if (k + 1) % 200 == 0:
            print(f"  [{k+1}/{len(symbols)}] events so far: {sum(len(x) for x in out)}")
    if not out:
        return pd.DataFrame()
    df = pd.concat(out, ignore_index=True)
    print(f"total events: {len(df)} (elapsed {time.time()-t0:.1f}s)")
    return df


def summarize(events: pd.DataFrame) -> pd.DataFrame:
    events = events.copy()
    events["_sbin"] = pd.cut(events["size"], bins=SIZE_EDGES, labels=SIZE_LABELS,
                              include_lowest=True, right=False)

    rows = []
    for label in SIZE_LABELS:
        sub = events[events["_sbin"] == label]
        row = {"size_bin": label, "n": int(len(sub))}
        for h, hl in zip(HORIZONS, H_LABELS):
            s = sub[f"fwd_{h}"].dropna()
            if len(s) > 0:
                row[f"{hl}_mean"] = float(s.mean())
                row[f"{hl}_med"] = float(s.median())
                row[f"{hl}_win"] = float((s > 0).mean())
            else:
                row[f"{hl}_mean"] = np.nan
                row[f"{hl}_med"] = np.nan
                row[f"{hl}_win"] = np.nan
        rows.append(row)
    # ALL
    sub = events
    row = {"size_bin": "ALL >=3%", "n": int(len(sub))}
    for h, hl in zip(HORIZONS, H_LABELS):
        s = sub[f"fwd_{h}"].dropna()
        row[f"{hl}_mean"] = float(s.mean()) if len(s) else np.nan
        row[f"{hl}_med"] = float(s.median()) if len(s) else np.nan
        row[f"{hl}_win"] = float((s > 0).mean()) if len(s) else np.nan
    rows.append(row)
    return pd.DataFrame(rows)


def print_table(df: pd.DataFrame, kind: str) -> None:
    cols = ["size_bin", "n"] + [f"{hl}_{kind}" for hl in H_LABELS]
    view = df[cols].copy()
    for hl in H_LABELS:
        c = f"{hl}_{kind}"
        if kind == "win":
            view[c] = view[c].apply(lambda x: f"{x*100:.0f}%" if pd.notna(x) else "-")
        else:
            view[c] = view[c].apply(lambda x: f"{x*100:+.2f}%" if pd.notna(x) else "-")
    with pd.option_context("display.max_rows", None, "display.width", 240):
        print(view.to_string(index=False))


def main() -> int:
    from scripts._common.run_helper import parse_args
    out_dir, _, args = parse_args(None, {}, "size_table")
    events = collect_all()
    if events.empty:
        return 1
    events.to_parquet(out_dir / "size_table_events.parquet", index=False)
    print(f"saved: {out_dir / 'size_table_events.parquet'}")

    summary = summarize(events)
    summary.to_csv(out_dir / "size_table_summary.csv", index=False, encoding="utf-8")

    print("\n=== MEAN forward returns (entry = impulse close) ===")
    print_table(summary, "mean")
    print("\n=== MEDIAN forward returns ===")
    print_table(summary, "med")
    print("\n=== Win rate (>0) ===")
    print_table(summary, "win")
    print(f"\nsaved: {out_dir / 'size_table_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
