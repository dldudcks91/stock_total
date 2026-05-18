"""Event study: weekly close-bar straddles MA20 while MA20 slope > 0 -> long.

Trigger: at weekly bar t,
  - MA20 slope > 0       (MA20[t] > MA20[t-1])
  - low[t] <= MA20[t] <= high[t]   (bar straddles MA20)
  - previous bar t-1 did NOT straddle (avoid overlapping touches)
Entry: open[t+1]
Forward return at horizon h (weeks): close[t+h] / entry - 1

Outputs (under <run_dir>/output/):
  events.parquet   - one row per touch event
  summary.csv      - per-horizon n/mean/median/std/win/p25/p75
  btc_slice.csv    - per-horizon stats split by BTC 1W MA20 slope

Run:
  .venv/Scripts/python.exe -m scripts.trend_pullback.ma20_touch_entry \
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
    "gate": "1W_MA20_slope_up",
    "ma_period": 20,
    "interval": "1w",
    "horizons_weeks": [1, 2, 4, 8, 24],
    "min_history_weeks": 30,
}


def load_symbols() -> list:
    return sorted(p.stem for p in CACHE_DIR.glob("*.parquet"))


def load_weekly(symbol: str) -> Optional[pd.DataFrame]:
    try:
        from data.resample import load as load_resampled
        df = load_resampled(symbol, "1w")
    except Exception:
        return None
    if df is None or len(df) < 25:
        return None
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def build_btc_regime() -> Optional[pd.DataFrame]:
    """BTC 1W MA20 slope flag, keyed by timestamp (ms)."""
    df = load_weekly("BTCUSDT")
    if df is None:
        return None
    ma20 = df["close"].rolling(20, min_periods=20).mean()
    df["btc_ma20"] = ma20
    df["btc_slope_up"] = ma20.diff() > 0
    return df[["timestamp", "btc_slope_up"]].copy()


def find_events_for_symbol(
    symbol: str,
    horizons: list,
    ma_period: int,
    min_history: int,
) -> Optional[pd.DataFrame]:
    df = load_weekly(symbol)
    if df is None or len(df) < min_history:
        return None

    close = df["close"].astype("float64").to_numpy()
    high = df["high"].astype("float64").to_numpy()
    low = df["low"].astype("float64").to_numpy()
    open_ = df["open"].astype("float64").to_numpy()
    ts = df["timestamp"].astype("int64").to_numpy()
    n = len(df)

    ma = pd.Series(close).rolling(ma_period, min_periods=ma_period).mean().to_numpy()
    ma_prev = np.concatenate([[np.nan], ma[:-1]])
    slope_up = ma > ma_prev

    straddle = (low <= ma) & (ma <= high) & np.isfinite(ma)
    straddle_prev = np.concatenate([[False], straddle[:-1]])
    # event = first bar of a touch series (previous bar untouched) AND slope_up
    event_mask = straddle & (~straddle_prev) & slope_up

    # need entry bar (t+1) to exist
    last_entry_t = n - 2
    event_mask[last_entry_t + 1:] = False

    idx = np.where(event_mask)[0]
    if idx.size == 0:
        return None

    rows = []
    max_h = max(horizons)
    for i in idx:
        entry_idx = i + 1
        entry_price = open_[entry_idx]
        if not np.isfinite(entry_price) or entry_price <= 0:
            continue
        row = {
            "symbol": symbol,
            "ts": int(ts[i]),
            "ts_entry": int(ts[entry_idx]),
            "ma20": float(ma[i]),
            "low": float(low[i]),
            "high": float(high[i]),
            "close": float(close[i]),
            "entry_price": float(entry_price),
            "ma_slope_pct": float((ma[i] / ma_prev[i] - 1.0) if ma_prev[i] > 0 else np.nan),
        }
        for h in horizons:
            tgt = entry_idx + (h - 1)  # h weeks after entry → close at index entry_idx + h - 1
            # entry is open of bar entry_idx; +1w = close of same bar; +Nw = close of bar entry_idx + N - 1
            tgt = entry_idx + h - 1
            if tgt < n and np.isfinite(close[tgt]):
                row[f"fwd_ret_{h}w"] = float(close[tgt] / entry_price - 1.0)
            else:
                row[f"fwd_ret_{h}w"] = np.nan
        rows.append(row)

    if not rows:
        return None
    return pd.DataFrame(rows)


def summarize(events: pd.DataFrame, horizons: list) -> pd.DataFrame:
    out = []
    for h in horizons:
        col = f"fwd_ret_{h}w"
        s = events[col].dropna()
        if len(s) == 0:
            continue
        out.append({
            "horizon_w": h,
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
            col = f"fwd_ret_{h}w"
            s = sub[col].dropna()
            if len(s) == 0:
                continue
            out.append({
                "btc_regime": label,
                "horizon_w": h,
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
        ap.add_argument("--min-history", type=int, default=None)

    out_dir, params, args = parse_args(add_args, DEFAULTS, __doc__.splitlines()[0])

    horizons = list(params.get("horizons_weeks", DEFAULTS["horizons_weeks"]))
    ma_period = int(params.get("ma_period", DEFAULTS["ma_period"]))
    min_history = int(params.get("min_history_weeks", DEFAULTS["min_history_weeks"]))

    symbols = load_symbols()
    print(f"[ma20_touch_entry] {len(symbols)} symbols, horizons={horizons}, ma={ma_period}")

    btc_regime = build_btc_regime()

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
    # attach BTC regime by ts (weekly bars share UTC week boundary)
    if btc_regime is not None:
        events = events.merge(btc_regime.rename(columns={"timestamp": "ts"}),
                                on="ts", how="left")
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
    print(f"\n[done] events={n_events} symbols_with_events={n_syms} "
          f"skipped_syms={n_skipped} elapsed={time.time()-t0:.1f}s")
    print("\nsummary:")
    print(summary.to_string(index=False))
    if not btc_slice.empty:
        print("\nbtc_slice:")
        print(btc_slice.to_string(index=False))

    cfg_path = resolve_config_path(args)
    if cfg_path:
        baseline_4w = summary.loc[summary["horizon_w"] == 4].iloc[0] if (summary["horizon_w"] == 4).any() else None
        baseline_8w = summary.loc[summary["horizon_w"] == 8].iloc[0] if (summary["horizon_w"] == 8).any() else None
        results_summary = {
            "n_events": n_events,
            "n_symbols_with_events": int(n_syms),
            "n_symbols_skipped": int(n_skipped),
        }
        if baseline_4w is not None:
            results_summary["fwd_4w_mean"] = float(baseline_4w["mean"])
            results_summary["fwd_4w_median"] = float(baseline_4w["median"])
            results_summary["fwd_4w_win"] = float(baseline_4w["win"])
        if baseline_8w is not None:
            results_summary["fwd_8w_mean"] = float(baseline_8w["mean"])
            results_summary["fwd_8w_median"] = float(baseline_8w["median"])
            results_summary["fwd_8w_win"] = float(baseline_8w["win"])
        update_config(cfg_path,
                       params={"ma_period": ma_period, "horizons_weeks": horizons,
                                "min_history_weeks": min_history},
                       data={"symbol_count": len(symbols)},
                       results_summary=results_summary)


if __name__ == "__main__":
    main()
