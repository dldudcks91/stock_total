"""5 confirmation strategies after the same breakout trigger.

Input events: B (pullback) events from breakout_mtf_stack — they carry
ts_trigger / symbol / trigger_close + meta. We re-load 1H + higher-TF MAs
per symbol and define 5 entry strategies. All forward returns use post-confirm
entry bar open.

Strategies:
A — 저점 유지 + 횡보 (sweep N bars and tolerance):
    For next N bars after trigger, require min(low) >= trigger_low * (1 - tol).
    If pass: entry = bar (trigger + N + 1) open.

B — 풀백 + 반등 양봉 (timeout sweep):
    From trigger+1, find first bar j where low[j] <= MA10_1h_locked[j] (pullback).
    Then check if bar j is bullish (close > open AND close > close[j-1]).
    If bar j has both conditions: entry = bar j+1 open.
    Timeout: if no qualifying bar within timeout_h, skip.

C — 새 고점 갱신 (sweep N bars):
    In next N bars after trigger, find first bar where high > trigger_high AND
    bar is bullish (close > open). Entry = next bar open.

D — MA stack 유지 (sweep N bars):
    For next N bars after trigger, require ALL bars to have close above 1H MA20,
    4H MA20_locked, 1D MA20_locked, 1W MA20_locked.
    If pass: entry = bar (trigger + N + 1) open.

E — 1D 봉 마감 확인:
    Find first 1D bar that opens AFTER trigger close. Check close > open
    (bullish daily). If pass: entry = next 1D bar's open (first 1H bar in next day).

Outputs (under run_dir/output/):
    events_A.parquet  events_B.parquet  events_C.parquet  events_D.parquet  events_E.parquet
    summary.csv       — per-strategy combo overall horizon stats
    compare.csv       — A/B/C/D/E head-to-head (best combo each)

Run:
    .venv/Scripts/python.exe -m scripts.trend_pullback.confirm_strategies \\
        --config scripts/trend_pullback/runs/<ts>_<name>/config.json
"""
from __future__ import annotations

import sys, time, json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_1H = PROJECT_ROOT / "data" / "cache" / "crypto" / "1h"

DEFAULTS = {
    "ma_period": 20,
    "ma_short_1h": 10,
    "horizons_hours": [4, 24, 72, 168, 336, 672],
}


def _load_1h(sym: str) -> Optional[pd.DataFrame]:
    p = CACHE_1H / f"{sym}.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p).sort_values("timestamp").reset_index(drop=True)
        return df
    except Exception:
        return None


def _resample_load(sym: str, interval: str):
    try:
        from data.resample import load as load_resampled
        df = load_resampled(sym, interval)
        if df is None or df.empty:
            return None
        return df.sort_values("timestamp").reset_index(drop=True)
    except Exception:
        return None


def _prepare_symbol(sym: str, ma_period: int, ma_short: int) -> Optional[pd.DataFrame]:
    h1 = _load_1h(sym)
    if h1 is None or len(h1) < ma_period + 5:
        return None
    h1["ma20_1h"] = h1["close"].rolling(ma_period).mean()
    h1["ma10_1h_locked"] = h1["close"].rolling(ma_short).mean().shift(1)
    for tf, name in [("4h", "ma20_4h"), ("1d", "ma20_1d"), ("1w", "ma20_1w")]:
        df_tf = _resample_load(sym, tf)
        if df_tf is None:
            return None
        ma = df_tf["close"].rolling(ma_period).mean().shift(1)
        ww = pd.DataFrame({"ts": df_tf["timestamp"].astype("int64"), name: ma})
        h1 = pd.merge_asof(h1.sort_values("timestamp"), ww,
                            left_on="timestamp", right_on="ts", direction="backward")
        h1.drop(columns=["ts"], inplace=True, errors="ignore")
    return h1.reset_index(drop=True)


def _fwd_rets(close: np.ndarray, entry_idx: int, entry_price: float,
               horizons: list, n: int) -> dict:
    out = {}
    for h in horizons:
        tgt = entry_idx + h - 1
        if tgt < n and np.isfinite(close[tgt]):
            out[f"fwd_ret_{h}h"] = float(close[tgt] / entry_price - 1.0)
        else:
            out[f"fwd_ret_{h}h"] = np.nan
    return out


def run_strategy_A(events: pd.DataFrame, sweep_n: list, sweep_tol: list,
                    horizons: list, sym_cache: dict) -> pd.DataFrame:
    rows = []
    for _, e in events.iterrows():
        sym = e["symbol"]
        h1 = sym_cache.get(sym)
        if h1 is None:
            continue
        ts = h1["timestamp"].astype("int64").to_numpy()
        op = h1["open"].astype("float64").to_numpy()
        lo = h1["low"].astype("float64").to_numpy()
        cl = h1["close"].astype("float64").to_numpy()
        n = len(h1)
        ti = int(np.searchsorted(ts, e["ts_trigger"]))
        if ti >= n: continue
        trig_low = float(lo[ti])
        for N in sweep_n:
            for tol in sweep_tol:
                end = ti + 1 + N
                if end + 1 >= n: continue
                window_lows = lo[ti + 1: end]
                if len(window_lows) == 0 or not np.isfinite(window_lows).any():
                    continue
                pass_hold = bool((window_lows >= trig_low * (1 - tol)).all())
                if not pass_hold: continue
                entry_idx = end  # bar after window
                ep = op[entry_idx]
                if not (np.isfinite(ep) and ep > 0): continue
                row = {"strategy": "A", "symbol": sym,
                        "ts_trigger": int(e["ts_trigger"]),
                        "ts_entry": int(ts[entry_idx]),
                        "trigger_low": trig_low,
                        "entry_price": float(ep),
                        "A_n_bars": int(N), "A_tolerance": float(tol)}
                row.update(_fwd_rets(cl, entry_idx, ep, horizons, n))
                rows.append(row)
    return pd.DataFrame(rows)


def run_strategy_B(events: pd.DataFrame, sweep_timeout: list,
                    horizons: list, sym_cache: dict) -> pd.DataFrame:
    rows = []
    for _, e in events.iterrows():
        sym = e["symbol"]
        h1 = sym_cache.get(sym)
        if h1 is None: continue
        ts = h1["timestamp"].astype("int64").to_numpy()
        op = h1["open"].astype("float64").to_numpy()
        hi = h1["high"].astype("float64").to_numpy()
        lo = h1["low"].astype("float64").to_numpy()
        cl = h1["close"].astype("float64").to_numpy()
        ma10 = h1["ma10_1h_locked"].astype("float64").to_numpy()
        n = len(h1)
        ti = int(np.searchsorted(ts, e["ts_trigger"]))
        if ti >= n: continue
        for to_h in sweep_timeout:
            end = min(ti + 1 + to_h, n)
            ok_idx = -1
            for j in range(ti + 1, end):
                m = ma10[j]
                if not (np.isfinite(m) and m > 0): continue
                # pullback condition + bullish + close > prev close
                if lo[j] <= m and cl[j] > op[j] and j >= 1 and cl[j] > cl[j - 1]:
                    ok_idx = j
                    break
            if ok_idx < 0: continue
            entry_idx = ok_idx + 1
            if entry_idx >= n: continue
            ep = op[entry_idx]
            if not (np.isfinite(ep) and ep > 0): continue
            row = {"strategy": "B", "symbol": sym,
                    "ts_trigger": int(e["ts_trigger"]),
                    "ts_pullback": int(ts[ok_idx]),
                    "ts_entry": int(ts[entry_idx]),
                    "hours_to_entry": int((ts[ok_idx] - e["ts_trigger"]) / 3600000),
                    "entry_price": float(ep),
                    "B_timeout_h": int(to_h)}
            row.update(_fwd_rets(cl, entry_idx, ep, horizons, n))
            rows.append(row)
    return pd.DataFrame(rows)


def run_strategy_C(events: pd.DataFrame, sweep_n: list,
                    horizons: list, sym_cache: dict) -> pd.DataFrame:
    rows = []
    for _, e in events.iterrows():
        sym = e["symbol"]
        h1 = sym_cache.get(sym)
        if h1 is None: continue
        ts = h1["timestamp"].astype("int64").to_numpy()
        op = h1["open"].astype("float64").to_numpy()
        hi = h1["high"].astype("float64").to_numpy()
        cl = h1["close"].astype("float64").to_numpy()
        n = len(h1)
        ti = int(np.searchsorted(ts, e["ts_trigger"]))
        if ti >= n: continue
        trig_high = float(hi[ti])
        for N in sweep_n:
            end = min(ti + 1 + N, n)
            ok_idx = -1
            for j in range(ti + 1, end):
                if hi[j] > trig_high and cl[j] > op[j]:
                    ok_idx = j
                    break
            if ok_idx < 0: continue
            entry_idx = ok_idx + 1
            if entry_idx >= n: continue
            ep = op[entry_idx]
            if not (np.isfinite(ep) and ep > 0): continue
            row = {"strategy": "C", "symbol": sym,
                    "ts_trigger": int(e["ts_trigger"]),
                    "ts_breakout": int(ts[ok_idx]),
                    "ts_entry": int(ts[entry_idx]),
                    "hours_to_entry": int((ts[ok_idx] - e["ts_trigger"]) / 3600000),
                    "trigger_high": trig_high,
                    "entry_price": float(ep),
                    "C_n_bars": int(N)}
            row.update(_fwd_rets(cl, entry_idx, ep, horizons, n))
            rows.append(row)
    return pd.DataFrame(rows)


def run_strategy_D(events: pd.DataFrame, sweep_n: list,
                    horizons: list, sym_cache: dict) -> pd.DataFrame:
    rows = []
    for _, e in events.iterrows():
        sym = e["symbol"]
        h1 = sym_cache.get(sym)
        if h1 is None: continue
        ts = h1["timestamp"].astype("int64").to_numpy()
        op = h1["open"].astype("float64").to_numpy()
        cl = h1["close"].astype("float64").to_numpy()
        m1h = h1["ma20_1h"].astype("float64").to_numpy()
        m4h = h1["ma20_4h"].astype("float64").to_numpy()
        m1d = h1["ma20_1d"].astype("float64").to_numpy()
        m1w = h1["ma20_1w"].astype("float64").to_numpy()
        n = len(h1)
        ti = int(np.searchsorted(ts, e["ts_trigger"]))
        if ti >= n: continue
        for N in sweep_n:
            end = ti + 1 + N
            if end + 1 >= n: continue
            window = slice(ti + 1, end)
            wc = cl[window]
            m1 = m1h[window]; m4 = m4h[window]; md = m1d[window]; mw = m1w[window]
            if len(wc) < N: continue
            ok = bool((np.isfinite(wc) & np.isfinite(m1) & np.isfinite(m4)
                        & np.isfinite(md) & np.isfinite(mw)
                        & (wc > m1) & (wc > m4) & (wc > md) & (wc > mw)).all())
            if not ok: continue
            entry_idx = end
            ep = op[entry_idx]
            if not (np.isfinite(ep) and ep > 0): continue
            row = {"strategy": "D", "symbol": sym,
                    "ts_trigger": int(e["ts_trigger"]),
                    "ts_entry": int(ts[entry_idx]),
                    "entry_price": float(ep),
                    "D_n_bars": int(N)}
            row.update(_fwd_rets(cl, entry_idx, ep, horizons, n))
            rows.append(row)
    return pd.DataFrame(rows)


def run_strategy_E(events: pd.DataFrame, sweep_max_days: list,
                    horizons: list, sym_cache: dict, sym_d_cache: dict) -> pd.DataFrame:
    """E: first 1D bar AFTER trigger close that closes bullish AND close > trigger_close.
    Entry = open of next 1H bar after that 1D bar closes (i.e. first 1H bar of next day).
    """
    rows = []
    MS_DAY = 86400000
    for _, e in events.iterrows():
        sym = e["symbol"]
        h1 = sym_cache.get(sym); d1 = sym_d_cache.get(sym)
        if h1 is None or d1 is None: continue
        ts_h = h1["timestamp"].astype("int64").to_numpy()
        op_h = h1["open"].astype("float64").to_numpy()
        cl_h = h1["close"].astype("float64").to_numpy()
        ts_d = d1["timestamp"].astype("int64").to_numpy()
        op_d = d1["open"].astype("float64").to_numpy()
        cl_d = d1["close"].astype("float64").to_numpy()
        n_h = len(h1); n_d = len(d1)
        ti_h = int(np.searchsorted(ts_h, e["ts_trigger"]))
        if ti_h >= n_h: continue
        trig_close = float(cl_h[ti_h])
        # First 1D bar that STARTS after trigger close (= next day's bar)
        # 1D bar.timestamp = bar start; we need the first 1D bar whose start > ts_trigger
        di = int(np.searchsorted(ts_d, e["ts_trigger"], side="right"))
        for max_d in sweep_max_days:
            ok_di = -1
            for j in range(di, min(di + max_d, n_d)):
                if cl_d[j] > op_d[j] and cl_d[j] > trig_close:
                    ok_di = j
                    break
            if ok_di < 0: continue
            # Entry: first 1H bar AFTER that daily bar closes
            # 1D bar j ends at ts_d[j] + 1 day. Find first 1H bar at or after that.
            entry_ts = int(ts_d[ok_di] + MS_DAY)
            entry_idx = int(np.searchsorted(ts_h, entry_ts, side="left"))
            if entry_idx >= n_h: continue
            ep = op_h[entry_idx]
            if not (np.isfinite(ep) and ep > 0): continue
            row = {"strategy": "E", "symbol": sym,
                    "ts_trigger": int(e["ts_trigger"]),
                    "ts_daily_close": int(ts_d[ok_di] + MS_DAY - 1),
                    "ts_entry": int(ts_h[entry_idx]),
                    "days_to_entry": int((ts_h[entry_idx] - e["ts_trigger"]) // MS_DAY) + 1,
                    "entry_price": float(ep),
                    "E_max_days": int(max_d)}
            row.update(_fwd_rets(cl_h, entry_idx, ep, horizons, n_h))
            rows.append(row)
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, key_cols: list, horizons: list) -> pd.DataFrame:
    rows = []
    for keys, grp in df.groupby(key_cols, observed=True):
        kd = dict(zip(key_cols, keys if isinstance(keys, tuple) else (keys,)))
        for h in horizons:
            col = f"fwd_ret_{h}h"
            if col not in grp.columns: continue
            s = grp[col].dropna()
            if len(s) == 0: continue
            rows.append({**kd, "h": h, "n": len(s),
                          "mean": float(s.mean()), "median": float(s.median()),
                          "win": float((s > 0).mean()), "std": float(s.std())})
    return pd.DataFrame(rows)


def main():
    from scripts._common.run_helper import parse_args, update_config, resolve_config_path

    def add_args(ap):
        pass

    out_dir, params, args = parse_args(add_args, DEFAULTS, __doc__.splitlines()[0])

    in_path = Path(params.get("input_events"))
    if not in_path.is_absolute():
        in_path = PROJECT_ROOT / in_path
    print(f"loading events from {in_path}")
    src = pd.read_parquet(in_path)
    print(f"  source events: {len(src)}")
    sub = src[(src["body_ret_min"] == 0.03) & (src["vol_ratio_min"] == 3.0)
              & (src["pullback_timeout_h"] == 24)].copy()
    # Dedupe by (symbol, ts_trigger) — the events have one row per timeout, we want unique triggers
    sub = sub.drop_duplicates(subset=["symbol", "ts_trigger"]).reset_index(drop=True)
    print(f"  unique triggers: {len(sub)}")

    horizons = list(params.get("horizons_hours", DEFAULTS["horizons_hours"]))
    ma_period = int(params.get("ma_period", DEFAULTS["ma_period"]))
    ma_short = int(params.get("ma_short_1h", DEFAULTS["ma_short_1h"]))

    cfg_path = resolve_config_path(args)
    sweep = {}
    if cfg_path:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        sweep = cfg.get("sweep", {}) or {}

    sweep_A_n = sweep.get("A_n_bars", [12, 24, 48])
    sweep_A_tol = sweep.get("A_tolerance", [0.02, 0.05])
    sweep_B_to = sweep.get("B_timeout_h", [48])
    sweep_C_n = sweep.get("C_n_bars", [12, 24, 48])
    sweep_D_n = sweep.get("D_n_bars", [4, 8, 12])
    sweep_E_md = sweep.get("E_max_days", [2])

    # Cache 1H + higher-TF MAs per unique symbol
    syms = sub["symbol"].unique()
    print(f"\ncaching {len(syms)} symbols (1H + 4 MA20)...")
    sym_cache = {}
    sym_d_cache = {}
    t0 = time.time()
    for k, sym in enumerate(syms, 1):
        prep = _prepare_symbol(sym, ma_period, ma_short)
        if prep is not None:
            sym_cache[sym] = prep
        d1 = _resample_load(sym, "1d")
        if d1 is not None:
            sym_d_cache[sym] = d1
        if k % 100 == 0:
            print(f"  {k}/{len(syms)} ({time.time()-t0:.1f}s)")
    print(f"cached. ({time.time()-t0:.1f}s)")

    print("\nrunning strategies...")
    t0 = time.time()
    A = run_strategy_A(sub, sweep_A_n, sweep_A_tol, horizons, sym_cache)
    print(f"  A: {len(A)} rows ({time.time()-t0:.1f}s)")
    t0 = time.time()
    B = run_strategy_B(sub, sweep_B_to, horizons, sym_cache)
    print(f"  B: {len(B)} rows ({time.time()-t0:.1f}s)")
    t0 = time.time()
    C = run_strategy_C(sub, sweep_C_n, horizons, sym_cache)
    print(f"  C: {len(C)} rows ({time.time()-t0:.1f}s)")
    t0 = time.time()
    D = run_strategy_D(sub, sweep_D_n, horizons, sym_cache)
    print(f"  D: {len(D)} rows ({time.time()-t0:.1f}s)")
    t0 = time.time()
    E = run_strategy_E(sub, sweep_E_md, horizons, sym_cache, sym_d_cache)
    print(f"  E: {len(E)} rows ({time.time()-t0:.1f}s)")

    if not A.empty: A.to_parquet(out_dir / "events_A.parquet", index=False)
    if not B.empty: B.to_parquet(out_dir / "events_B.parquet", index=False)
    if not C.empty: C.to_parquet(out_dir / "events_C.parquet", index=False)
    if not D.empty: D.to_parquet(out_dir / "events_D.parquet", index=False)
    if not E.empty: E.to_parquet(out_dir / "events_E.parquet", index=False)

    # Summaries
    summaries = []
    for label, df, keys in [("A", A, ["A_n_bars","A_tolerance"]),
                              ("B", B, ["B_timeout_h"]),
                              ("C", C, ["C_n_bars"]),
                              ("D", D, ["D_n_bars"]),
                              ("E", E, ["E_max_days"])]:
        if df.empty: continue
        s = summarize(df, keys, horizons)
        s["strategy"] = label
        summaries.append(s)
    summary = pd.concat(summaries, ignore_index=True) if summaries else pd.DataFrame()
    summary.to_csv(out_dir / "summary.csv", index=False)

    print("\n=== SUMMARY (all years) ===")
    for h in (24, 168, 672):
        sub_h = summary[summary["h"] == h].copy()
        sub_h["combo"] = sub_h.apply(lambda r: f"{r['strategy']}: {' '.join(f'{k}={int(v) if pd.notna(v) and v==v//1 else v}' for k,v in r.items() if k in ('A_n_bars','A_tolerance','B_timeout_h','C_n_bars','D_n_bars','E_max_days') and pd.notna(v))}", axis=1)
        print(f"\n@ {h}h:")
        print(sub_h[["strategy","combo","n","mean","median","win"]].sort_values("win", ascending=False).to_string(index=False))

    if cfg_path:
        update_config(cfg_path,
                       params={"ma_period": ma_period, "ma_short_1h": ma_short,
                                "horizons_hours": horizons},
                       data={"symbol_count": int(sub["symbol"].nunique())},
                       results_summary={"n_triggers": int(len(sub)),
                                        "n_events_A": int(len(A)),
                                        "n_events_B": int(len(B)),
                                        "n_events_C": int(len(C)),
                                        "n_events_D": int(len(D)),
                                        "n_events_E": int(len(E))})


if __name__ == "__main__":
    main()
