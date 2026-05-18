"""1H intraweek touch of 1W MA20 (slope>0 locked from prev week) -> long.

Difference vs `ma20_touch_entry.py`:
  - That one used weekly close-bar touch (low<=MA20<=high on the WEEKLY bar)
  - This one finds 1H bars within the week that touch MA20, locked from prev week
  - Catches cases where weekly close recovered ABOVE MA20 but intra-week dipped to it

Lock-in:
  - For week W, MA20_locked = MA20 computed on weekly closes up through W-1
  - slope_up_locked = MA20(W-1) > MA20(W-2)
  - Both locked values stay constant across all 1H bars within week W (no lookahead)

Event = first 1H bar of week W with low<=MA20_locked<=high AND slope_up_locked True.
Entry = open of next 1H bar.
fwd_ret_{h}h = close[entry+h-1] / entry_open - 1

Outputs (under <run_dir>/output/):
  events.parquet
  summary.csv
  btc_slice.csv

Run:
  .venv/Scripts/python.exe -m scripts.trend_pullback.ma20_touch_1h_entry \
      --config scripts/trend_pullback/runs/<ts>_<name>/config.json
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

DEFAULTS = {
    "ma_period": 20,
    "horizons_hours": [1, 6, 24, 72, 168, 336, 672],
    "min_history_weeks": 30,
}


def load_symbols() -> list:
    return sorted(p.stem for p in CACHE_DIR.glob("*.parquet"))


def load_weekly_ma_locked(symbol: str, ma_period: int) -> Optional[pd.DataFrame]:
    """Return per-week (week_start_ts_ms, ma20_locked, slope_up_locked).

    Both columns are values from the PREVIOUSLY completed week (.shift(1)),
    so they are known and safe to use throughout that week's 1H bars.
    """
    try:
        from data.resample import load as load_resampled
        w = load_resampled(symbol, "1w")
    except Exception:
        return None
    if w is None or len(w) < ma_period + 2:
        return None
    w = w.sort_values("timestamp").reset_index(drop=True)
    ma = w["close"].rolling(ma_period, min_periods=ma_period).mean()
    out = pd.DataFrame({
        "week_start": w["timestamp"].astype("int64"),
        "ma20_locked": ma.shift(1),
        "slope_up_locked": (ma.diff() > 0).shift(1),
    })
    return out


def build_btc_regime(ma_period: int = 20) -> Optional[pd.DataFrame]:
    df = load_weekly_ma_locked("BTCUSDT", ma_period)
    if df is None:
        return None
    df = df.rename(columns={"slope_up_locked": "btc_slope_up"})
    return df[["week_start", "btc_slope_up"]].copy()


def find_events_for_symbol(
    symbol: str,
    horizons: list,
    ma_period: int,
    min_history_weeks: int,
) -> Optional[pd.DataFrame]:
    path = CACHE_DIR / f"{symbol}.parquet"
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None
    if df is None or len(df) < min_history_weeks * 168:
        return None

    df = df.sort_values("timestamp").reset_index(drop=True)

    weekly = load_weekly_ma_locked(symbol, ma_period)
    if weekly is None:
        return None

    # Map each 1H ts to its containing week_start via merge_asof (backward).
    # weekly["week_start"] is the start ts of each weekly bar; for any 1H ts in
    # [week_start, week_start + 7d), backward match returns that week.
    df = pd.merge_asof(df, weekly, left_on="timestamp", right_on="week_start",
                         direction="backward")

    ts = df["timestamp"].astype("int64").to_numpy()
    open_ = df["open"].astype("float64").to_numpy()
    high = df["high"].astype("float64").to_numpy()
    low = df["low"].astype("float64").to_numpy()
    close = df["close"].astype("float64").to_numpy()
    ma_lock = df["ma20_locked"].astype("float64").to_numpy()
    slope_up = df["slope_up_locked"].fillna(False).to_numpy().astype(bool)
    week_id = df["week_start"].astype("int64").to_numpy()
    n = len(df)

    valid_ma = np.isfinite(ma_lock)
    touch = valid_ma & (low <= ma_lock) & (ma_lock <= high) & slope_up

    if not touch.any():
        return None

    # First touch within each week (skip duplicates inside same week).
    # week_id transitions mark week boundaries.
    week_changed = np.concatenate([[True], week_id[1:] != week_id[:-1]])

    rows = []
    max_h = int(max(horizons))
    seen_week = -1
    for i in np.where(touch)[0]:
        wk = week_id[i]
        if wk == seen_week:
            continue
        # require entry bar (i+1) to exist
        if i + 1 >= n:
            continue
        entry_price = open_[i + 1]
        if not np.isfinite(entry_price) or entry_price <= 0:
            continue
        seen_week = wk
        row = {
            "symbol": symbol,
            "ts": int(ts[i]),
            "ts_entry": int(ts[i + 1]),
            "week_start": int(wk),
            "ma20_locked": float(ma_lock[i]),
            "low_1h": float(low[i]),
            "high_1h": float(high[i]),
            "close_1h": float(close[i]),
            "entry_price": float(entry_price),
        }
        for h in horizons:
            tgt = i + h  # entry is open of bar i+1; close after h hours = close[i+h]
            if tgt < n and np.isfinite(close[tgt]):
                row[f"fwd_ret_{h}h"] = float(close[tgt] / entry_price - 1.0)
            else:
                row[f"fwd_ret_{h}h"] = np.nan
        rows.append(row)

    if not rows:
        return None
    return pd.DataFrame(rows)


def summarize(events: pd.DataFrame, horizons: list) -> pd.DataFrame:
    out = []
    for h in horizons:
        col = f"fwd_ret_{h}h"
        s = events[col].dropna()
        if len(s) == 0:
            continue
        out.append({
            "horizon_h": h,
            "n": int(len(s)),
            "mean": float(s.mean()),
            "median": float(s.median()),
            "std": float(s.std()),
            "win": float((s > 0).mean()),
            "p25": float(s.quantile(0.25)),
            "p75": float(s.quantile(0.75)),
        })
    return pd.DataFrame(out)


def btc_slice_summary(events: pd.DataFrame, horizons: list) -> pd.DataFrame:
    out = []
    for label, mask in [
        ("btc_up", events["btc_slope_up"] == True),
        ("btc_down", events["btc_slope_up"] == False),
    ]:
        sub = events[mask]
        for h in horizons:
            col = f"fwd_ret_{h}h"
            s = sub[col].dropna()
            if len(s) == 0:
                continue
            out.append({
                "btc_regime": label,
                "horizon_h": h,
                "n": int(len(s)),
                "mean": float(s.mean()),
                "median": float(s.median()),
                "win": float((s > 0).mean()),
            })
    return pd.DataFrame(out)


def main():
    from scripts._common.run_helper import parse_args, update_config, resolve_config_path

    def add_args(ap):
        ap.add_argument("--ma-period", type=int, default=None)

    out_dir, params, args = parse_args(add_args, DEFAULTS, __doc__.splitlines()[0])

    horizons = list(params.get("horizons_hours", DEFAULTS["horizons_hours"]))
    ma_period = int(params.get("ma_period", DEFAULTS["ma_period"]))
    min_history = int(params.get("min_history_weeks", DEFAULTS["min_history_weeks"]))

    symbols = load_symbols()
    print(f"[ma20_touch_1h_entry] {len(symbols)} symbols, ma={ma_period}, horizons(h)={horizons}")

    btc_regime = build_btc_regime(ma_period)

    t0 = time.time()
    parts = []
    n_skipped = 0
    for k, sym in enumerate(symbols, 1):
        ev = find_events_for_symbol(sym, horizons, ma_period, min_history)
        if ev is None:
            n_skipped += 1
        else:
            parts.append(ev)
        if k % 100 == 0:
            print(f"  {k}/{len(symbols)} ({time.time()-t0:.1f}s)")

    if not parts:
        print("no events")
        return

    events = pd.concat(parts, ignore_index=True)
    if btc_regime is not None:
        events = events.merge(btc_regime, on="week_start", how="left")
    else:
        events["btc_slope_up"] = pd.NA

    events.to_parquet(out_dir / "events.parquet", index=False)
    summary = summarize(events, horizons)
    summary.to_csv(out_dir / "summary.csv", index=False)

    btc_slice = btc_slice_summary(events, horizons) if btc_regime is not None else pd.DataFrame()
    if not btc_slice.empty:
        btc_slice.to_csv(out_dir / "btc_slice.csv", index=False)

    n_events = len(events)
    n_syms = events["symbol"].nunique()
    n_weeks = events["week_start"].nunique()
    print(f"\n[done] events={n_events} symbols_with_events={n_syms} "
          f"unique_weeks={n_weeks} skipped_syms={n_skipped} elapsed={time.time()-t0:.1f}s")
    print("\nsummary:")
    print(summary.to_string(index=False))
    if not btc_slice.empty:
        print("\nbtc_slice:")
        print(btc_slice.to_string(index=False))

    cfg_path = resolve_config_path(args)
    if cfg_path:
        results_summary = {
            "n_events": n_events,
            "n_symbols_with_events": int(n_syms),
            "n_unique_weeks": int(n_weeks),
            "n_symbols_skipped": int(n_skipped),
        }
        for h in (24, 168, 672):
            if (summary["horizon_h"] == h).any():
                row = summary.loc[summary["horizon_h"] == h].iloc[0]
                results_summary[f"fwd_{h}h_mean"] = float(row["mean"])
                results_summary[f"fwd_{h}h_median"] = float(row["median"])
                results_summary[f"fwd_{h}h_win"] = float(row["win"])
        update_config(cfg_path,
                       params={"ma_period": ma_period, "horizons_hours": horizons,
                                "min_history_weeks": min_history},
                       data={"symbol_count": len(symbols)},
                       results_summary=results_summary)


if __name__ == "__main__":
    main()
