"""1W MA20 slope cross-up event study on crypto 1D bars.

Trigger:
    slope[W]   = MA20[W]   - MA20[W-1]
    slope[W-1] = MA20[W-1] - MA20[W-2]
    event when slope[W] > 0 AND slope[W-1] <= 0
    (i.e. the first weekly close at which the 20w MA slope turns positive)

Entry:
    Open of the first 1D bar AFTER week W closes (i.e. first 1D bar whose
    timestamp >= week_W_start + 7 days). No lookahead — at week W close we
    know slope[W] and slope[W-1].

Forward returns:
    fwd_ret_{N}d = close[entry_idx + N - 1] / open[entry_idx] - 1
    for N in horizons_days (e.g. 1..7, 14, 21, 28, 35, 42, 49, 56)

Output (under <run_dir>/output/):
    events.parquet       — per-event row (symbol, ts_cross_close, ts_entry,
                           ma20[W], ma20[W-1], ma20[W-2], entry_price,
                           fwd_ret_*d)
    horizon_curve.csv    — wide: row=horizon_d, cols=n,mean,median,std,win,p25,p75
    per_symbol_n.csv     — symbol × n events (sanity)

Run:
    .venv/Scripts/python.exe -m scripts.trend_pullback.slope_cross_event \\
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
CACHE_1H = PROJECT_ROOT / "data" / "cache" / "crypto" / "1h"
CACHE_1D = PROJECT_ROOT / "data" / "cache" / "crypto" / "1d"

DEFAULTS = {
    "ma_period_weekly": 20,
    "horizons_days": [1, 2, 3, 4, 5, 6, 7, 14, 21, 28, 35, 42, 49, 56],
    "min_history_weeks": 30,
}


def load_symbols() -> list:
    # Prefer 1d cache, else fall back to 1h list
    if CACHE_1D.exists():
        d = sorted(p.stem for p in CACHE_1D.glob("*.parquet"))
        if d:
            return d
    return sorted(p.stem for p in CACHE_1H.glob("*.parquet"))


def load_daily(symbol: str) -> Optional[pd.DataFrame]:
    """Return 1D OHLCV with timestamp (UTC ms) + ohlcv columns."""
    try:
        from data.resample import load as load_resampled
        df = load_resampled(symbol, "1d")
    except Exception:
        return None
    if df is None or df.empty:
        return None
    return df.sort_values("timestamp").reset_index(drop=True)


def load_weekly(symbol: str) -> Optional[pd.DataFrame]:
    try:
        from data.resample import load as load_resampled
        w = load_resampled(symbol, "1w")
    except Exception:
        return None
    if w is None or w.empty:
        return None
    return w.sort_values("timestamp").reset_index(drop=True)


def find_events_for_symbol(symbol: str, horizons_d: list, ma_period: int,
                            min_history_weeks: int) -> Optional[pd.DataFrame]:
    w = load_weekly(symbol)
    if w is None or len(w) < ma_period + 3:
        return None
    d = load_daily(symbol)
    if d is None or len(d) < min_history_weeks * 7:
        return None

    ma = w["close"].rolling(ma_period, min_periods=ma_period).mean()
    slope = ma.diff()
    prev_slope = slope.shift(1)
    # Cross-up at week W: slope[W] > 0 AND slope[W-1] <= 0
    cross = (slope > 0) & (prev_slope <= 0) & slope.notna() & prev_slope.notna()

    if not cross.any():
        return None

    ws = w["timestamp"].astype("int64").to_numpy()
    ma_v = ma.to_numpy()

    d_ts = d["timestamp"].astype("int64").to_numpy()
    d_open = d["open"].astype("float64").to_numpy()
    d_close = d["close"].astype("float64").to_numpy()
    n_d = len(d)

    ms_per_week = 7 * 24 * 3600 * 1000
    rows = []
    max_h = int(max(horizons_d))
    for wi in np.where(cross.to_numpy())[0]:
        week_start_ms = int(ws[wi])
        next_week_start_ms = week_start_ms + ms_per_week
        # Find first 1D bar at or after next_week_start_ms
        idx = int(np.searchsorted(d_ts, next_week_start_ms, side="left"))
        if idx + max_h > n_d:
            continue
        entry_price = d_open[idx]
        if not (np.isfinite(entry_price) and entry_price > 0):
            continue
        row = {
            "symbol": symbol,
            "ts_week_close": int(week_start_ms + ms_per_week - 1),  # end of week W
            "ts_entry": int(d_ts[idx]),
            "ma20_w": float(ma_v[wi]),
            "ma20_w_1": float(ma_v[wi - 1]) if wi >= 1 else np.nan,
            "ma20_w_2": float(ma_v[wi - 2]) if wi >= 2 else np.nan,
            "entry_price": float(entry_price),
        }
        for h in horizons_d:
            tgt = idx + h - 1
            if tgt < n_d and np.isfinite(d_close[tgt]):
                row[f"fwd_ret_{h}d"] = float(d_close[tgt] / entry_price - 1.0)
            else:
                row[f"fwd_ret_{h}d"] = np.nan
        rows.append(row)

    if not rows:
        return None
    return pd.DataFrame(rows)


def horizon_curve(events: pd.DataFrame, horizons: list) -> pd.DataFrame:
    rows = []
    for h in horizons:
        col = f"fwd_ret_{h}d"
        if col not in events.columns:
            continue
        s = events[col].dropna()
        if s.empty:
            rows.append({"horizon_d": h, "n": 0, "mean": np.nan,
                          "median": np.nan, "std": np.nan, "win": np.nan,
                          "p25": np.nan, "p75": np.nan})
            continue
        rows.append({
            "horizon_d": h,
            "n": int(len(s)),
            "mean": float(s.mean()),
            "median": float(s.median()),
            "std": float(s.std()),
            "win": float((s > 0).mean()),
            "p25": float(s.quantile(0.25)),
            "p75": float(s.quantile(0.75)),
        })
    return pd.DataFrame(rows)


def main():
    from scripts._common.run_helper import parse_args, update_config, resolve_config_path

    def add_args(ap):
        ap.add_argument("--ma-period-weekly", type=int, default=None)

    out_dir, params, args = parse_args(add_args, DEFAULTS, __doc__.splitlines()[0])

    ma_period = int(params.get("ma_period_weekly", DEFAULTS["ma_period_weekly"]))
    horizons = list(params.get("horizons_days", DEFAULTS["horizons_days"]))
    min_history = int(params.get("min_history_weeks", DEFAULTS["min_history_weeks"]))

    symbols = load_symbols()
    print(f"[slope_cross_event] {len(symbols)} symbols, ma_period_weekly={ma_period}, "
          f"horizons_d={horizons}")

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
    events.to_parquet(out_dir / "events.parquet", index=False)

    curve = horizon_curve(events, horizons)
    curve.to_csv(out_dir / "horizon_curve.csv", index=False)

    per_sym = events.groupby("symbol").size().reset_index(name="n_events").sort_values("n_events", ascending=False)
    per_sym.to_csv(out_dir / "per_symbol_n.csv", index=False)

    n_events = len(events)
    n_syms = events["symbol"].nunique()
    print(f"\n[done] events={n_events} symbols_with_events={n_syms} "
          f"skipped_syms={n_skipped} elapsed={time.time()-t0:.1f}s")
    print("\nhorizon_curve:")
    print(curve.to_string(index=False))

    cfg_path = resolve_config_path(args)
    if cfg_path:
        results_summary = {
            "n_events": n_events,
            "n_symbols_with_events": int(n_syms),
            "n_symbols_skipped": int(n_skipped),
        }
        for h in (1, 7, 14, 28, 56):
            row = curve.loc[curve["horizon_d"] == h]
            if len(row):
                r = row.iloc[0]
                results_summary[f"fwd_{h}d_mean"] = float(r["mean"])
                results_summary[f"fwd_{h}d_median"] = float(r["median"])
                results_summary[f"fwd_{h}d_win"] = float(r["win"])
        update_config(cfg_path,
                       params={"ma_period_weekly": ma_period,
                                "horizons_days": horizons,
                                "min_history_weeks": min_history},
                       data={"symbol_count": len(symbols)},
                       results_summary=results_summary)


if __name__ == "__main__":
    main()
