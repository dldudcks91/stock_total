"""1H breakout with 4-TF MA20 stack confirmation; A=chase, B=pullback entries.

Trigger (T) at 1H bar i:
    body_ret[i] = (close[i]-open[i])/open[i] >= body_ret_min
    vol_ratio[i] = vol[i] / SMA(vol,20)[i-1] >= vol_ratio_min   (no lookahead)
    AND close[i] > MA20_1h[i]
    AND close[i] > MA20_4h_locked[i]   (most recent CLOSED 4H bar's MA20)
    AND close[i] > MA20_1d_locked[i]
    AND close[i] > MA20_1w_locked[i]

Cooldown: 24h between consecutive triggers per symbol.

A (chase_breakout):
    Entry = open[i+1]
    Forward returns at close[i+h] / open[i+1] - 1, h in horizons_hours.

B (pullback_after_breakout):
    From i+1 to i+pullback_timeout_h, find first bar j with low[j]<=MA10_1h_locked[j]<=high[j].
    Entry = open[j+1]. If not found in window: skip event for B.
    Forward returns from open[j+1] over horizons_hours.

Sweep:
    body_ret_min x vol_ratio_min for A.
    Same x pullback_timeout_h for B.

Outputs:
    events_A.parquet
    events_B.parquet
    sweep_A_overall.csv  (combo x horizon long table for A)
    sweep_B_overall.csv
    sweep_A_body.csv / sweep_A_vol.csv (marginals)
    sweep_B_body.csv / sweep_B_vol.csv / sweep_B_timeout.csv

Run:
    .venv/Scripts/python.exe -m scripts.trend_pullback.breakout_mtf_stack \\
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

DEFAULTS = {
    "ma_period": 20,
    "ma_period_short_1h": 10,
    "vol_sma_period": 20,
    "cooldown_hours": 24,
    "horizons_hours": [4, 12, 24, 72, 168, 336, 672],
    "min_history_hours": 720,
    "body_ret_min": 0.02,
    "vol_ratio_min": 1.0,
    "pullback_timeout_h": 24,
}

DEFAULT_SWEEP_BODY = [0.01, 0.02, 0.03]
DEFAULT_SWEEP_VOL = [1.0, 2.0]
DEFAULT_SWEEP_TIMEOUT = [24, 168]


def load_symbols() -> list:
    return sorted(p.stem for p in CACHE_1H.glob("*.parquet"))


def _load_1h(symbol: str) -> Optional[pd.DataFrame]:
    p = CACHE_1H / f"{symbol}.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    return df.sort_values("timestamp").reset_index(drop=True)


def _resample_load(symbol: str, interval: str) -> Optional[pd.DataFrame]:
    try:
        from data.resample import load as load_resampled
        df = load_resampled(symbol, interval)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    return df.sort_values("timestamp").reset_index(drop=True)


def _build_locked_ma(df: pd.DataFrame, period: int) -> pd.DataFrame:
    """Return (timestamp, ma_locked) where ma_locked uses bars up through PREV bar
    of this TF (shift 1). Suitable for merge_asof backward onto a finer-TF series."""
    ma = df["close"].rolling(period, min_periods=period).mean()
    return pd.DataFrame({
        "ts": df["timestamp"].astype("int64"),
        "ma_locked": ma.shift(1),
    })


def process_symbol(symbol: str, ma_period: int, ma_short_1h: int,
                    vol_sma_period: int, cooldown_h: int,
                    sweep_body: list, sweep_vol: list, sweep_timeout: list,
                    horizons_h: list, min_history_h: int):
    """Returns (events_A_df, events_B_df) for all combos, or (None, None)."""
    h1 = _load_1h(symbol)
    if h1 is None or len(h1) < min_history_h:
        return None, None

    # Higher-TF MAs (locked)
    d4 = _resample_load(symbol, "4h")
    d1 = _resample_load(symbol, "1d")
    w1 = _resample_load(symbol, "1w")
    if d4 is None or d1 is None or w1 is None:
        return None, None
    if len(d4) < ma_period + 2 or len(d1) < ma_period + 2 or len(w1) < ma_period + 2:
        return None, None

    ma_4h = _build_locked_ma(d4, ma_period).rename(columns={"ma_locked": "ma20_4h"})
    ma_1d = _build_locked_ma(d1, ma_period).rename(columns={"ma_locked": "ma20_1d"})
    ma_1w = _build_locked_ma(w1, ma_period).rename(columns={"ma_locked": "ma20_1w"})

    # 1H MA20 (current bar, includes close[i])
    h1["ma20_1h"] = h1["close"].rolling(ma_period, min_periods=ma_period).mean()
    # 1H MA10 (locked = shift 1) used for pullback target detection
    h1["ma10_1h_locked"] = h1["close"].rolling(ma_short_1h, min_periods=ma_short_1h).mean().shift(1)
    # Vol SMA20 shifted (avoid current bar in denom)
    h1["vol_sma_prev"] = h1["volume"].rolling(vol_sma_period, min_periods=vol_sma_period).mean().shift(1)

    # body / vol ratio
    h1["body_ret"] = (h1["close"] - h1["open"]) / h1["open"]
    h1["vol_ratio"] = h1["volume"] / h1["vol_sma_prev"]

    # Merge locked higher-TF MAs backward onto 1H ts
    h1 = h1.sort_values("timestamp")
    h1 = pd.merge_asof(h1, ma_4h, left_on="timestamp", right_on="ts", direction="backward")
    h1.drop(columns=["ts"], inplace=True, errors="ignore")
    h1 = pd.merge_asof(h1, ma_1d, left_on="timestamp", right_on="ts", direction="backward")
    h1.drop(columns=["ts"], inplace=True, errors="ignore")
    h1 = pd.merge_asof(h1, ma_1w, left_on="timestamp", right_on="ts", direction="backward")
    h1.drop(columns=["ts"], inplace=True, errors="ignore")
    h1.reset_index(drop=True, inplace=True)

    n = len(h1)
    ts = h1["timestamp"].astype("int64").to_numpy()
    op = h1["open"].astype("float64").to_numpy()
    hi = h1["high"].astype("float64").to_numpy()
    lo = h1["low"].astype("float64").to_numpy()
    cl = h1["close"].astype("float64").to_numpy()
    body = h1["body_ret"].astype("float64").to_numpy()
    vr = h1["vol_ratio"].astype("float64").to_numpy()
    m_1h = h1["ma20_1h"].astype("float64").to_numpy()
    m_4h = h1["ma20_4h"].astype("float64").to_numpy()
    m_1d = h1["ma20_1d"].astype("float64").to_numpy()
    m_1w = h1["ma20_1w"].astype("float64").to_numpy()
    m_short = h1["ma10_1h_locked"].astype("float64").to_numpy()

    # stack ok = close > all MAs and all MAs finite
    stack_ok = (np.isfinite(m_1h) & np.isfinite(m_4h) & np.isfinite(m_1d) & np.isfinite(m_1w)
                & (cl > m_1h) & (cl > m_4h) & (cl > m_1d) & (cl > m_1w))

    max_h = int(max(horizons_h))
    cooldown_bars = int(cooldown_h)
    ms_hour = 3600 * 1000

    events_A = []
    events_B = []

    for body_min in sweep_body:
        for vol_min in sweep_vol:
            cond = (np.isfinite(body) & np.isfinite(vr) & (body >= body_min)
                    & (vr >= vol_min) & stack_ok)
            idxs = np.where(cond)[0]
            if len(idxs) == 0:
                continue

            # Cooldown filter
            last_kept = -10**9
            kept = []
            for i in idxs:
                if i - last_kept >= cooldown_bars:
                    kept.append(i)
                    last_kept = i

            for i in kept:
                # A entry
                ai = i + 1
                if ai >= n:
                    continue
                a_entry = op[ai]
                if not (np.isfinite(a_entry) and a_entry > 0):
                    continue
                rowA = {
                    "symbol": symbol,
                    "ts_trigger": int(ts[i]),
                    "ts_entry": int(ts[ai]),
                    "body_ret": float(body[i]),
                    "vol_ratio": float(vr[i]),
                    "trigger_close": float(cl[i]),
                    "ma20_1h_trigger": float(m_1h[i]),
                    "ma20_4h_trigger": float(m_4h[i]),
                    "ma20_1d_trigger": float(m_1d[i]),
                    "ma20_1w_trigger": float(m_1w[i]),
                    "entry_price": float(a_entry),
                    "body_ret_min": float(body_min),
                    "vol_ratio_min": float(vol_min),
                }
                for h in horizons_h:
                    tgt = ai + h - 1
                    if tgt < n and np.isfinite(cl[tgt]):
                        rowA[f"fwd_ret_{h}h"] = float(cl[tgt] / a_entry - 1.0)
                    else:
                        rowA[f"fwd_ret_{h}h"] = np.nan
                events_A.append(rowA)

                # B entries (per timeout)
                for to_h in sweep_timeout:
                    end_scan = min(i + 1 + to_h, n)
                    pull_idx = -1
                    for j in range(i + 1, end_scan):
                        ma = m_short[j]
                        if np.isfinite(ma) and ma > 0 and lo[j] <= ma <= hi[j]:
                            pull_idx = j
                            break
                    if pull_idx < 0:
                        continue
                    bi = pull_idx + 1
                    if bi >= n:
                        continue
                    b_entry = op[bi]
                    if not (np.isfinite(b_entry) and b_entry > 0):
                        continue
                    hours_to_pullback = int((ts[pull_idx] - ts[i]) / ms_hour)
                    rowB = {
                        "symbol": symbol,
                        "ts_trigger": int(ts[i]),
                        "ts_pullback": int(ts[pull_idx]),
                        "ts_entry": int(ts[bi]),
                        "hours_to_pullback": hours_to_pullback,
                        "body_ret": float(body[i]),
                        "vol_ratio": float(vr[i]),
                        "trigger_close": float(cl[i]),
                        "pullback_low": float(lo[pull_idx]),
                        "pullback_ma_short": float(m_short[pull_idx]),
                        "entry_price": float(b_entry),
                        "body_ret_min": float(body_min),
                        "vol_ratio_min": float(vol_min),
                        "pullback_timeout_h": int(to_h),
                    }
                    for h in horizons_h:
                        tgt = bi + h - 1
                        if tgt < n and np.isfinite(cl[tgt]):
                            rowB[f"fwd_ret_{h}h"] = float(cl[tgt] / b_entry - 1.0)
                        else:
                            rowB[f"fwd_ret_{h}h"] = np.nan
                    events_B.append(rowB)

    return (pd.DataFrame(events_A) if events_A else None,
            pd.DataFrame(events_B) if events_B else None)


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


def overall_long(events: pd.DataFrame, key_cols: list, horizons: list) -> pd.DataFrame:
    rows = []
    for keys, grp in events.groupby(key_cols, observed=True):
        kdict = dict(zip(key_cols, keys if isinstance(keys, tuple) else (keys,)))
        for h in horizons:
            col = f"fwd_ret_{h}h"
            if col not in grp.columns:
                continue
            rows.append({**kdict, "horizon_h": h, **_cell_stats(grp[col])})
    return pd.DataFrame(rows)


def marginal_wide(long_df: pd.DataFrame, axis: str, other_axes: dict,
                    horizons_to_show=(4, 24, 72, 168, 672)) -> pd.DataFrame:
    mask = pd.Series(True, index=long_df.index)
    for k, v in other_axes.items():
        if k in long_df.columns:
            mask &= (long_df[k] == v)
    sub = long_df[mask].copy()
    if sub.empty:
        return pd.DataFrame()
    keep_cols = [axis, "n", "mean", "median", "win", "var_adj"]
    pieces = []
    for h in horizons_to_show:
        sh = sub[sub["horizon_h"] == h].copy()[keep_cols]
        sh = sh.rename(columns={c: f"{c}_{h}h" for c in keep_cols if c != axis})
        pieces.append(sh.set_index(axis))
    if not pieces:
        return pd.DataFrame()
    return pd.concat(pieces, axis=1).reset_index()


def main():
    from scripts._common.run_helper import parse_args, update_config, resolve_config_path

    def add_args(ap):
        ap.add_argument("--ma-period", type=int, default=None)
        ap.add_argument("--cooldown-hours", type=int, default=None)

    out_dir, params, args = parse_args(add_args, DEFAULTS, __doc__.splitlines()[0])

    horizons = list(params.get("horizons_hours", DEFAULTS["horizons_hours"]))
    ma_period = int(params.get("ma_period", DEFAULTS["ma_period"]))
    ma_short = int(params.get("ma_period_short_1h", DEFAULTS["ma_period_short_1h"]))
    vol_sma = int(params.get("vol_sma_period", DEFAULTS["vol_sma_period"]))
    cooldown_h = int(params.get("cooldown_hours", DEFAULTS["cooldown_hours"]))
    min_hist_h = int(params.get("min_history_hours", DEFAULTS["min_history_hours"]))

    cfg_path = resolve_config_path(args)
    sweep = None
    if cfg_path:
        import json
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        sweep = cfg.get("sweep")
    if not sweep:
        sweep = {"body_ret_min": DEFAULT_SWEEP_BODY,
                 "vol_ratio_min": DEFAULT_SWEEP_VOL,
                 "pullback_timeout_h": DEFAULT_SWEEP_TIMEOUT}
    sweep_body = list(sweep.get("body_ret_min", DEFAULT_SWEEP_BODY))
    sweep_vol = list(sweep.get("vol_ratio_min", DEFAULT_SWEEP_VOL))
    sweep_to = list(sweep.get("pullback_timeout_h", DEFAULT_SWEEP_TIMEOUT))

    symbols = load_symbols()
    print(f"[breakout_mtf_stack] {len(symbols)} symbols")
    print(f"  body_ret_min sweep: {sweep_body}")
    print(f"  vol_ratio_min sweep: {sweep_vol}")
    print(f"  pullback_timeout_h sweep (B only): {sweep_to}")
    print(f"  horizons_h: {horizons}")

    t0 = time.time()
    all_A, all_B = [], []
    n_skipped = 0
    for k, sym in enumerate(symbols, 1):
        eA, eB = process_symbol(sym, ma_period, ma_short, vol_sma, cooldown_h,
                                  sweep_body, sweep_vol, sweep_to,
                                  horizons, min_hist_h)
        if eA is None and eB is None:
            n_skipped += 1
        if eA is not None:
            all_A.append(eA)
        if eB is not None:
            all_B.append(eB)
        if k % 50 == 0:
            print(f"  {k}/{len(symbols)} ({time.time()-t0:.1f}s) A={sum(len(x) for x in all_A)} B={sum(len(x) for x in all_B)}")

    print(f"\n[done] elapsed={time.time()-t0:.1f}s skipped={n_skipped}")

    if all_A:
        A = pd.concat(all_A, ignore_index=True)
        A.to_parquet(out_dir / "events_A.parquet", index=False)
        print(f"A events: {len(A)}")
    else:
        A = pd.DataFrame()
    if all_B:
        B = pd.concat(all_B, ignore_index=True)
        B.to_parquet(out_dir / "events_B.parquet", index=False)
        print(f"B events: {len(B)}")
    else:
        B = pd.DataFrame()

    # Long format sweep results
    if not A.empty:
        longA = overall_long(A, ["body_ret_min", "vol_ratio_min"], horizons)
        longA.to_csv(out_dir / "sweep_A_overall.csv", index=False)
        # Marginals
        defaults_for_A = {"vol_ratio_min": DEFAULTS["vol_ratio_min"]}
        m = marginal_wide(longA, "body_ret_min", defaults_for_A)
        if not m.empty:
            m.to_csv(out_dir / "sweep_A_body.csv", index=False)
            print("\n--- A marginal: body_ret_min (vol_ratio_min=1.0) ---")
            print(m.to_string(index=False))
        m = marginal_wide(longA, "vol_ratio_min", {"body_ret_min": DEFAULTS["body_ret_min"]})
        if not m.empty:
            m.to_csv(out_dir / "sweep_A_vol.csv", index=False)
            print("\n--- A marginal: vol_ratio_min (body_ret_min=0.02) ---")
            print(m.to_string(index=False))

    if not B.empty:
        longB = overall_long(B, ["body_ret_min", "vol_ratio_min", "pullback_timeout_h"], horizons)
        longB.to_csv(out_dir / "sweep_B_overall.csv", index=False)
        m = marginal_wide(longB, "body_ret_min",
                            {"vol_ratio_min": DEFAULTS["vol_ratio_min"],
                             "pullback_timeout_h": DEFAULTS["pullback_timeout_h"]})
        if not m.empty:
            m.to_csv(out_dir / "sweep_B_body.csv", index=False)
            print("\n--- B marginal: body_ret_min (vol=1.0, timeout=24h) ---")
            print(m.to_string(index=False))
        m = marginal_wide(longB, "vol_ratio_min",
                            {"body_ret_min": DEFAULTS["body_ret_min"],
                             "pullback_timeout_h": DEFAULTS["pullback_timeout_h"]})
        if not m.empty:
            m.to_csv(out_dir / "sweep_B_vol.csv", index=False)
            print("\n--- B marginal: vol_ratio_min (body=0.02, timeout=24h) ---")
            print(m.to_string(index=False))
        m = marginal_wide(longB, "pullback_timeout_h",
                            {"body_ret_min": DEFAULTS["body_ret_min"],
                             "vol_ratio_min": DEFAULTS["vol_ratio_min"]})
        if not m.empty:
            m.to_csv(out_dir / "sweep_B_timeout.csv", index=False)
            print("\n--- B marginal: pullback_timeout_h (body=0.02, vol=1.0) ---")
            print(m.to_string(index=False))

    if cfg_path:
        results_summary = {
            "n_events_A": int(len(A)),
            "n_events_B": int(len(B)),
            "n_symbols_skipped": int(n_skipped),
            "elapsed_sec": float(time.time() - t0),
        }
        update_config(cfg_path,
                       params={"ma_period": ma_period,
                                "ma_period_short_1h": ma_short,
                                "vol_sma_period": vol_sma,
                                "cooldown_hours": cooldown_h,
                                "horizons_hours": horizons,
                                "min_history_hours": min_hist_h},
                       data={"symbol_count": len(symbols)},
                       results_summary=results_summary)


if __name__ == "__main__":
    main()
