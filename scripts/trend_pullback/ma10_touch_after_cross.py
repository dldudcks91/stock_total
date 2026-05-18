"""1W MA20 slope cross-up gate + first MA(short) touch entry on crypto 1D bars.

Gate:
    gate_strict=True  -> slope cross-up: slope[W]>0 AND slope[W-1]<=0
    gate_strict=False -> slope_up only:   slope[W]>0 (no prev-week condition)
    `slope` = MA20[W] - MA20[W-1].

Trigger:
    After the gate fires at week W close, scan 1D bars from first 1D bar
    of week W+1 onward. First 1D bar with low <= MA_short_locked <= high
    is the trigger bar. MA_short is the weekly MA of `ma_short_period`,
    locked from prev week (shift 1).

Entry:
    Open of the 1D bar after the trigger bar (no lookahead).

Forward returns:
    fwd_ret_{N}d = close[entry_idx + N - 1] / open[entry_idx] - 1

Sweep:
    Marginal: ma_short_period (default 10) and gate_strict (default True).
    Total combos = 1 (default) + (len(sweep.ma_short_period)-1) + (len(gate_strict)-1)

Outputs:
    events_all.parquet
    sweep_overall.csv
    sweep_ma_short_period.csv
    sweep_gate_strict.csv

Run:
    .venv/Scripts/python.exe -m scripts.trend_pullback.ma10_touch_after_cross \\
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

DEFAULTS = {
    "ma_period_weekly": 20,
    "ma_short_period": 10,
    "gate_strict": True,
    "horizons_days": [1, 2, 3, 4, 5, 6, 7, 14, 21, 28, 35, 42, 49, 56],
    "max_lookforward_days": 365,
    "min_history_weeks": 30,
}

DEFAULT_SWEEP = {
    "ma_short_period": [5, 10, 15],
    "gate_strict": [True, False],
}


def load_symbols() -> list:
    p = PROJECT_ROOT / "data" / "cache" / "crypto" / "1d"
    return sorted(x.stem for x in p.glob("*.parquet"))


def load_daily(symbol: str) -> Optional[pd.DataFrame]:
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


def find_events_for_symbol(symbol: str, horizons: list, ma_period: int,
                            ma_short: int, gate_strict: bool,
                            max_lookforward_days: int,
                            min_history_weeks: int) -> Optional[pd.DataFrame]:
    w = load_weekly(symbol)
    if w is None or len(w) < max(ma_period, ma_short) + 3:
        return None
    d = load_daily(symbol)
    if d is None or len(d) < min_history_weeks * 7:
        return None

    ma20 = w["close"].rolling(ma_period, min_periods=ma_period).mean()
    ma_s = w["close"].rolling(ma_short, min_periods=ma_short).mean()
    slope = ma20.diff()
    prev_slope = slope.shift(1)
    if gate_strict:
        gate = (slope > 0) & (prev_slope <= 0) & slope.notna() & prev_slope.notna()
    else:
        gate = (slope > 0) & slope.notna()

    if not gate.any():
        return None

    ws = w["timestamp"].astype("int64").to_numpy()
    ma_s_locked = ma_s.shift(1).to_numpy()  # locked from prev week
    ma20_v = ma20.to_numpy()
    ma_s_v = ma_s.to_numpy()

    d_ts = d["timestamp"].astype("int64").to_numpy()
    d_open = d["open"].astype("float64").to_numpy()
    d_high = d["high"].astype("float64").to_numpy()
    d_low = d["low"].astype("float64").to_numpy()
    d_close = d["close"].astype("float64").to_numpy()
    n_d = len(d)

    ms_week = 7 * 24 * 3600 * 1000
    ms_day = 24 * 3600 * 1000
    max_bars = max_lookforward_days  # 1 bar = 1 day on 1d data

    # Per-1D bar, find which weekly index it belongs to (via merge_asof would work,
    # but we iterate by gate weeks for clarity).
    rows = []
    for wi in np.where(gate.to_numpy())[0]:
        gate_week_close_ms = int(ws[wi] + ms_week - 1)
        # First 1D bar at or after next_week_start
        next_week_start_ms = int(ws[wi] + ms_week)
        start_idx = int(np.searchsorted(d_ts, next_week_start_ms, side="left"))
        if start_idx >= n_d:
            continue
        end_idx = min(start_idx + max_bars, n_d)

        # MA_short locked value applicable to bars in week W+1 (since locked from prev week,
        # the MA_short value at week W is what's "known" entering W+1).
        # We iterate week-by-week within the lookforward window to get the right locked value.
        touch_bar = -1
        last_ma_s_used = np.nan
        for bar_idx in range(start_idx, end_idx):
            ts_bar = d_ts[bar_idx]
            # Which weekly bin does this 1d bar belong to?
            # week_index_for_ts: find weekly index s.t. ws[wi'] <= ts_bar < ws[wi'+1]
            # MA_short_locked value to use = ma_s value at PREV week of that week
            # Simpler: use ma_s shifted weekly index >= 0 such that ws[wi_curr] <= ts_bar.
            # Then locked value = ma_s_v[wi_curr - 1] (or ma_s_locked at wi_curr).
            wi_curr = int(np.searchsorted(ws, ts_bar, side="right") - 1)
            if wi_curr < 1:
                continue
            ma_locked = ma_s_locked[wi_curr]
            if not np.isfinite(ma_locked) or ma_locked <= 0:
                continue
            last_ma_s_used = ma_locked
            if d_low[bar_idx] <= ma_locked <= d_high[bar_idx]:
                touch_bar = bar_idx
                break

        if touch_bar < 0:
            continue
        entry_idx = touch_bar + 1
        if entry_idx >= n_d:
            continue
        entry_price = d_open[entry_idx]
        if not (np.isfinite(entry_price) and entry_price > 0):
            continue

        days_to_touch = (d_ts[touch_bar] - next_week_start_ms) // ms_day + 1  # 1-based
        # Above/below MA10 at the moment of cross-up (= first 1d bar of week W+1)
        first_bar = d_open[start_idx] if start_idx < n_d else np.nan
        gap_at_gate = float(first_bar / last_ma_s_used - 1.0) if (np.isfinite(first_bar) and np.isfinite(last_ma_s_used) and last_ma_s_used > 0) else np.nan

        row = {
            "symbol": symbol,
            "ts_gate": int(gate_week_close_ms),
            "ts_touch": int(d_ts[touch_bar]),
            "ts_entry": int(d_ts[entry_idx]),
            "days_to_touch": int(days_to_touch),
            "ma20_locked": float(ma20_v[wi]),
            "ma_short_locked_at_touch": float(last_ma_s_used),
            "touch_low": float(d_low[touch_bar]),
            "touch_high": float(d_high[touch_bar]),
            "touch_close": float(d_close[touch_bar]),
            "gap_first_bar_to_ma_short": gap_at_gate,
            "entry_price": float(entry_price),
        }
        for h in horizons:
            tgt = entry_idx + h - 1
            if tgt < n_d and np.isfinite(d_close[tgt]):
                row[f"fwd_ret_{h}d"] = float(d_close[tgt] / entry_price - 1.0)
            else:
                row[f"fwd_ret_{h}d"] = np.nan
        rows.append(row)

    if not rows:
        return None
    return pd.DataFrame(rows)


def _cell_stats(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"n": 0, "mean": np.nan, "median": np.nan, "std": np.nan,
                "win": np.nan, "var_adj": np.nan}
    mean = float(s.mean())
    std = float(s.std())
    return {"n": int(len(s)), "mean": mean, "median": float(s.median()),
            "std": std, "win": float((s > 0).mean()),
            "var_adj": mean - 1.65 * std}


def horizon_curve(events: pd.DataFrame, horizons: list) -> pd.DataFrame:
    rows = []
    for h in horizons:
        col = f"fwd_ret_{h}d"
        if col not in events.columns:
            continue
        rows.append({"horizon_d": h, **_cell_stats(events[col])})
    return pd.DataFrame(rows)


def build_combos(defaults: dict, sweep: dict) -> list:
    combos = []
    seen = set()
    def add(combo):
        key = tuple(sorted(combo.items()))
        if key not in seen:
            seen.add(key)
            combos.append(dict(combo))
    add({k: defaults[k] for k in sweep.keys()})
    for axis, values in sweep.items():
        for v in values:
            if v == defaults[axis]:
                continue
            combo = {k: defaults[k] for k in sweep.keys()}
            combo[axis] = v
            add(combo)
    return combos


def main():
    from scripts._common.run_helper import parse_args, update_config, resolve_config_path

    def add_args(ap):
        ap.add_argument("--ma-period-weekly", type=int, default=None)
        ap.add_argument("--ma-short-period", type=int, default=None)
        ap.add_argument("--gate-strict", type=int, default=None,
                         help="1 for strict (cross-up), 0 for slope-up only")

    out_dir, params, args = parse_args(add_args, DEFAULTS, __doc__.splitlines()[0])

    horizons = list(params.get("horizons_days", DEFAULTS["horizons_days"]))
    ma_period = int(params.get("ma_period_weekly", DEFAULTS["ma_period_weekly"]))
    min_history = int(params.get("min_history_weeks", DEFAULTS["min_history_weeks"]))
    max_lf = int(params.get("max_lookforward_days", DEFAULTS["max_lookforward_days"]))

    defaults_for_sweep = {
        "ma_short_period": int(params.get("ma_short_period", DEFAULTS["ma_short_period"])),
        "gate_strict": bool(params.get("gate_strict", DEFAULTS["gate_strict"])),
    }

    cfg_path = resolve_config_path(args)
    sweep = None
    if cfg_path:
        import json
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        sweep = cfg.get("sweep")
    if not sweep:
        sweep = DEFAULT_SWEEP

    combos = build_combos(defaults_for_sweep, sweep)
    print(f"[ma10_touch_after_cross] sweep combos: {len(combos)}")
    for c in combos:
        print(f"  {c}")

    symbols = load_symbols()
    print(f"\n{len(symbols)} symbols")

    all_events = []
    overall_rows = []
    t_total = time.time()
    for ci, combo in enumerate(combos, 1):
        t0 = time.time()
        parts = []
        for sym in symbols:
            ev = find_events_for_symbol(
                sym, horizons,
                ma_period=ma_period,
                ma_short=combo["ma_short_period"],
                gate_strict=combo["gate_strict"],
                max_lookforward_days=max_lf,
                min_history_weeks=min_history,
            )
            if ev is not None:
                parts.append(ev)
        if not parts:
            print(f"  combo {ci}/{len(combos)} {combo}: NO EVENTS")
            continue
        events = pd.concat(parts, ignore_index=True)
        for k, v in combo.items():
            events[k] = v
        events.reset_index(drop=True, inplace=True)

        summ = horizon_curve(events, horizons)
        for _, r in summ.iterrows():
            overall_rows.append({**combo, "horizon_d": int(r["horizon_d"]),
                                  "n": int(r["n"]), "mean": r["mean"],
                                  "median": r["median"], "std": r["std"],
                                  "win": r["win"], "var_adj": r["var_adj"]})
        all_events.append(events)
        elapsed = time.time() - t0
        n_ev = len(events)
        w14 = summ[summ.horizon_d == 14]["win"].iloc[0] if (summ.horizon_d == 14).any() else float("nan")
        m14 = summ[summ.horizon_d == 14]["mean"].iloc[0] if (summ.horizon_d == 14).any() else float("nan")
        print(f"  combo {ci}/{len(combos)} n={n_ev} 14d win={w14:.3f} mean={m14*100:+.2f}% ({elapsed:.1f}s)")

    print(f"\n[done] total elapsed={time.time()-t_total:.1f}s")
    if all_events:
        all_df = pd.concat(all_events, ignore_index=True)
        all_df.to_parquet(out_dir / "events_all.parquet", index=False)

    sweep_overall = pd.DataFrame(overall_rows)
    sweep_overall.to_csv(out_dir / "sweep_overall.csv", index=False)

    # Marginal tables (per axis)
    for axis in sweep.keys():
        fixed = [k for k in defaults_for_sweep.keys() if k != axis]
        mask = pd.Series(True, index=sweep_overall.index)
        for fx in fixed:
            mask &= (sweep_overall[fx] == defaults_for_sweep[fx])
        sub = sweep_overall[mask].copy()
        if sub.empty:
            continue
        # Wide on horizons of interest
        keep_cols = [axis, "n", "mean", "median", "win", "var_adj"]
        pieces = []
        for h in (1, 7, 14, 28, 56):
            sh = sub[sub["horizon_d"] == h].copy()[keep_cols]
            sh = sh.rename(columns={c: f"{c}_{h}d" for c in keep_cols if c != axis})
            pieces.append(sh.set_index(axis))
        if pieces:
            wide = pd.concat(pieces, axis=1).reset_index()
            wide.to_csv(out_dir / f"sweep_{axis}.csv", index=False)
            print(f"\n--- marginal: {axis} ---")
            print(wide.to_string(index=False))

    if cfg_path:
        n_default = 0
        if not sweep_overall.empty:
            m = pd.Series(True, index=sweep_overall.index)
            for k, v in defaults_for_sweep.items():
                m &= (sweep_overall[k] == v)
            base = sweep_overall[m & (sweep_overall["horizon_d"] == 14)]
            if len(base):
                n_default = int(base.iloc[0]["n"])
        update_config(cfg_path,
                       params={"ma_period_weekly": ma_period,
                                **defaults_for_sweep,
                                "horizons_days": horizons,
                                "max_lookforward_days": max_lf,
                                "min_history_weeks": min_history},
                       data={"symbol_count": len(symbols)},
                       results_summary={"n_combos": len(combos),
                                        "n_events_default": n_default})


if __name__ == "__main__":
    main()
