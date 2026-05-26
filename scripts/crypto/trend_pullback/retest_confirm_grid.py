"""1H MA20 retest under 1W slope>0 + confirmation bar feature grid (marginal sweep).

For each (ma_period_weekly, confirm_offset, vol_sma_period, rsi_period) combo,
collects 1H touch events under the gate, measures confirmation-bar features at
bar (i + confirm_offset), and enters at bar (i + confirm_offset + 1) open.

Marginal sweep: only one param differs from default at a time. Default point is
included once. Total combos = 1 (default) + sum(len(values)-1 for each sweep axis).

For each combo we emit:
  - overall summary (n, mean/median/std/win/var_adj per horizon)
  - 1D feature × quintile cell grid (per horizon)

Outputs (under <run_dir>/output/):
  events_all.parquet            — all events × combos with param columns
  sweep_overall.csv             — combo × horizon overall
  sweep_<param>.csv             — marginal table for each swept param (wide)
  sweep_grid1d.csv              — combo × feature × quintile × horizon (long)
  sweep_top_cells.csv           — combo × top-K 1D cells by win @ 168h (n>=100)

Run:
  .venv/Scripts/python.exe -m scripts.trend_pullback.retest_confirm_grid \\
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
    "ma_period_weekly": 20,
    "confirm_offset": 1,
    "vol_sma_period": 20,
    "rsi_period": 14,
    "n_quantiles": 5,
    "horizons_hours": [1, 6, 24, 72, 168, 336, 672],
    "min_history_weeks": 30,
}

DEFAULT_SWEEP = {
    "ma_period_weekly": [10, 20, 30, 50],
    "confirm_offset": [1, 2, 3],
    "vol_sma_period": [10, 20, 50],
    "rsi_period": [7, 14, 21],
}


def load_symbols() -> list:
    return sorted(p.stem for p in CACHE_DIR.glob("*.parquet"))


def load_weekly_ma_locked(symbol: str, ma_period: int) -> Optional[pd.DataFrame]:
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
        "ma_locked": ma.shift(1),
        "slope_up_locked": (ma.diff() > 0).shift(1).astype("boolean"),
    })
    return out


def build_btc_regime(ma_period: int) -> Optional[pd.DataFrame]:
    df = load_weekly_ma_locked("BTCUSDT", ma_period)
    if df is None:
        return None
    df = df.rename(columns={"slope_up_locked": "btc_slope_up"})
    return df[["week_start", "btc_slope_up"]].copy()


def _rsi_wilders(close: np.ndarray, period: int) -> np.ndarray:
    n = len(close)
    rsi = np.full(n, np.nan)
    if n <= period:
        return rsi
    delta = np.diff(close)
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)
    avg_up = up[:period].mean()
    avg_dn = dn[:period].mean()
    rsi[period] = (100.0 if avg_up > 0 else 50.0) if avg_dn == 0 else (100.0 - 100.0 / (1.0 + avg_up / avg_dn))
    for i in range(period + 1, n):
        avg_up = (avg_up * (period - 1) + up[i - 1]) / period
        avg_dn = (avg_dn * (period - 1) + dn[i - 1]) / period
        rsi[i] = (100.0 if avg_up > 0 else 50.0) if avg_dn == 0 else (100.0 - 100.0 / (1.0 + avg_up / avg_dn))
    return rsi


def find_events_for_symbol(
    symbol: str,
    horizons: list,
    ma_period: int,
    confirm_offset: int,
    vol_sma_period: int,
    rsi_period: int,
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

    df = pd.merge_asof(df, weekly, left_on="timestamp", right_on="week_start",
                         direction="backward")

    ts = df["timestamp"].astype("int64").to_numpy()
    open_ = df["open"].astype("float64").to_numpy()
    high = df["high"].astype("float64").to_numpy()
    low = df["low"].astype("float64").to_numpy()
    close = df["close"].astype("float64").to_numpy()
    vol = df["volume"].astype("float64").to_numpy()
    ma_lock = df["ma_locked"].astype("float64").to_numpy()
    slope_up = df["slope_up_locked"].fillna(False).astype(bool).to_numpy()
    week_id = df["week_start"].astype("int64").to_numpy()
    n = len(df)

    vol_sma_prev = pd.Series(vol).rolling(vol_sma_period, min_periods=vol_sma_period).mean().shift(1).to_numpy()
    rsi = _rsi_wilders(close, rsi_period)

    valid_ma = np.isfinite(ma_lock)
    touch = valid_ma & (low <= ma_lock) & (ma_lock <= high) & slope_up
    if not touch.any():
        return None

    rows = []
    seen_week = -1
    co = int(confirm_offset)
    entry_off = co + 1
    for i in np.where(touch)[0]:
        wk = week_id[i]
        if wk == seen_week:
            continue
        if i + entry_off >= n:
            continue
        c_open = open_[i + co]
        c_high = high[i + co]
        c_low = low[i + co]
        c_close = close[i + co]
        c_vol = vol[i + co]
        if not (np.isfinite(c_open) and c_open > 0 and np.isfinite(c_close)):
            continue
        entry_price = open_[i + entry_off]
        if not (np.isfinite(entry_price) and entry_price > 0):
            continue
        seen_week = wk

        rng = c_high - c_low
        body_top = max(c_open, c_close)
        body_bot = min(c_open, c_close)
        up_wick = (c_high - body_top) / rng if rng > 0 else 0.0
        low_wick = (body_bot - c_low) / rng if rng > 0 else 0.0
        body_ret = (c_close - c_open) / c_open
        color_green = bool(c_close > c_open)
        vsma = vol_sma_prev[i + co]
        vol_ratio = float(c_vol / vsma) if (np.isfinite(vsma) and vsma > 0) else np.nan
        rsi_val = float(rsi[i + co]) if np.isfinite(rsi[i + co]) else np.nan
        ma_v = ma_lock[i]
        touch_depth = float((ma_v - low[i]) / ma_v) if (np.isfinite(ma_v) and ma_v > 0) else np.nan

        row = {
            "symbol": symbol,
            "ts_touch": int(ts[i]),
            "ts_confirm": int(ts[i + co]),
            "ts_entry": int(ts[i + entry_off]),
            "week_start": int(wk),
            "ma_locked": float(ma_v),
            "touch_depth": touch_depth,
            "body_ret": float(body_ret),
            "color_green": color_green,
            "vol_ratio": vol_ratio,
            "up_wick_ratio": float(up_wick),
            "low_wick_ratio": float(low_wick),
            "rsi": rsi_val,
            "entry_price": float(entry_price),
        }
        for h in horizons:
            tgt = i + co + h
            if tgt < n and np.isfinite(close[tgt]):
                row[f"fwd_ret_{h}h"] = float(close[tgt] / entry_price - 1.0)
            else:
                row[f"fwd_ret_{h}h"] = np.nan
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
    return {
        "n": int(len(s)),
        "mean": mean,
        "median": float(s.median()),
        "std": std,
        "win": float((s > 0).mean()),
        "var_adj": mean - 1.65 * std,
    }


def overall_summary(events: pd.DataFrame, horizons: list) -> pd.DataFrame:
    out = []
    for h in horizons:
        col = f"fwd_ret_{h}h"
        if col not in events.columns:
            continue
        stats = _cell_stats(events[col])
        out.append({"horizon_h": h, **stats})
    return pd.DataFrame(out)


def grid_1d_long(events: pd.DataFrame, features: list, horizons: list, q: int) -> pd.DataFrame:
    out = []
    for feat in features:
        if feat not in events.columns:
            continue
        s = events[feat].dropna()
        if len(s) < q * 10:
            continue
        try:
            cats = pd.qcut(s, q=q, duplicates="drop")
        except ValueError:
            continue
        full = pd.Series(pd.NA, index=events.index, dtype="object")
        full.loc[s.index] = cats.astype(str)
        for cat, idx in full.dropna().groupby(full.dropna()).indices.items():
            sub = events.loc[list(idx)]
            for h in horizons:
                col = f"fwd_ret_{h}h"
                if col not in sub.columns:
                    continue
                out.append({"feature": feat, "quantile": cat, "horizon_h": h,
                            **_cell_stats(sub[col])})
        if feat == "body_ret":
            for label, mask in [("green", events["color_green"] == True),
                                 ("red", events["color_green"] == False)]:
                sub = events[mask]
                for h in horizons:
                    col = f"fwd_ret_{h}h"
                    if col not in sub.columns:
                        continue
                    out.append({"feature": "color", "quantile": label,
                                "horizon_h": h, **_cell_stats(sub[col])})
    return pd.DataFrame(out)


def build_combos(defaults: dict, sweep: dict) -> list:
    """Marginal sweep: default point + each non-default axis."""
    combos = []
    seen = set()
    def add(combo):
        key = tuple(sorted(combo.items()))
        if key in seen:
            return
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


def run_one_combo(symbols, combo: dict, horizons, min_history) -> Optional[pd.DataFrame]:
    parts = []
    for sym in symbols:
        ev = find_events_for_symbol(
            sym, horizons,
            ma_period=combo["ma_period_weekly"],
            confirm_offset=combo["confirm_offset"],
            vol_sma_period=combo["vol_sma_period"],
            rsi_period=combo["rsi_period"],
            min_history_weeks=min_history,
        )
        if ev is not None:
            parts.append(ev)
    if not parts:
        return None
    df = pd.concat(parts, ignore_index=True)
    for k, v in combo.items():
        df[k] = v
    return df


def marginal_table(sweep_overall: pd.DataFrame, defaults: dict, axis: str,
                    horizons_to_show=(168, 672)) -> pd.DataFrame:
    """Filter combos where only `axis` varies; pivot wide on horizons."""
    fixed_axes = [k for k in defaults.keys() if k != axis]
    mask = pd.Series(True, index=sweep_overall.index)
    for fx in fixed_axes:
        if fx in sweep_overall.columns:
            mask &= (sweep_overall[fx] == defaults[fx])
    sub = sweep_overall[mask].copy()
    if sub.empty:
        return pd.DataFrame()
    keep_cols = [axis, "n", "mean", "median", "win", "var_adj"]
    pieces = []
    for h in horizons_to_show:
        sh = sub[sub["horizon_h"] == h].copy()
        sh = sh[keep_cols]
        sh = sh.rename(columns={c: f"{c}_{h}h" for c in keep_cols if c != axis})
        pieces.append(sh.set_index(axis))
    if not pieces:
        return pd.DataFrame()
    wide = pd.concat(pieces, axis=1).reset_index()
    return wide


def main():
    from scripts._common.run_helper import parse_args, update_config, resolve_config_path

    def add_args(ap):
        # CLI overrides for the single defaults (sweep comes from config.sweep)
        for k, v in DEFAULTS.items():
            if isinstance(v, list):
                continue
            ap.add_argument(f"--{k.replace('_', '-')}", type=type(v), default=None)

    out_dir, params, args = parse_args(add_args, DEFAULTS, __doc__.splitlines()[0])

    horizons = list(params.get("horizons_hours", DEFAULTS["horizons_hours"]))
    min_history = int(params.get("min_history_weeks", DEFAULTS["min_history_weeks"]))
    q = int(params.get("n_quantiles", DEFAULTS["n_quantiles"]))

    defaults_for_sweep = {
        "ma_period_weekly": int(params.get("ma_period_weekly", DEFAULTS["ma_period_weekly"])),
        "confirm_offset": int(params.get("confirm_offset", DEFAULTS["confirm_offset"])),
        "vol_sma_period": int(params.get("vol_sma_period", DEFAULTS["vol_sma_period"])),
        "rsi_period": int(params.get("rsi_period", DEFAULTS["rsi_period"])),
    }

    # Sweep config: from config.json's top-level 'sweep' (preferred) or DEFAULT_SWEEP.
    cfg_path = resolve_config_path(args)
    sweep = None
    if cfg_path:
        import json
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        sweep = cfg.get("sweep")
    if not sweep:
        sweep = DEFAULT_SWEEP

    combos = build_combos(defaults_for_sweep, sweep)
    print(f"[retest_confirm_grid] sweep combos: {len(combos)}, q={q}")
    for c in combos:
        print(f"  {c}")

    symbols = load_symbols()
    print(f"\n{len(symbols)} symbols")

    btc_regime_default = build_btc_regime(defaults_for_sweep["ma_period_weekly"])

    all_events = []
    overall_rows = []
    grid_rows = []
    top_cells_rows = []
    features_1d = ["body_ret", "vol_ratio", "rsi", "up_wick_ratio",
                    "low_wick_ratio", "touch_depth"]

    t_total = time.time()
    for ci, combo in enumerate(combos, 1):
        t0 = time.time()
        events = run_one_combo(symbols, combo, horizons, min_history)
        if events is None or events.empty:
            print(f"  combo {ci}/{len(combos)} {combo}: NO EVENTS")
            continue

        # Attach BTC regime (use default ma_period_weekly BTC slope — comparable across combos)
        if btc_regime_default is not None:
            events = events.merge(btc_regime_default, on="week_start", how="left")
        events.reset_index(drop=True, inplace=True)

        # Overall per horizon
        summ = overall_summary(events, horizons)
        for _, r in summ.iterrows():
            overall_rows.append({**combo, "horizon_h": int(r["horizon_h"]),
                                  "n": int(r["n"]), "mean": r["mean"],
                                  "median": r["median"], "std": r["std"],
                                  "win": r["win"], "var_adj": r["var_adj"]})

        # 1D grid
        g = grid_1d_long(events, features_1d, horizons, q)
        for _, r in g.iterrows():
            grid_rows.append({**combo, **r.to_dict()})

        # Top cells @ 168h with n>=100
        g_168 = g[(g["horizon_h"] == 168) & (g["n"] >= 100)].sort_values("win", ascending=False).head(5)
        for _, r in g_168.iterrows():
            top_cells_rows.append({**combo, **r.to_dict()})

        all_events.append(events)
        elapsed = time.time() - t0
        n_ev = len(events)
        win168 = summ[summ.horizon_h == 168]["win"].iloc[0] if (summ.horizon_h == 168).any() else float("nan")
        print(f"  combo {ci}/{len(combos)} n={n_ev} win@168h={win168:.3f} ({elapsed:.1f}s)")

    print(f"\n[done] total elapsed={time.time()-t_total:.1f}s")

    if all_events:
        all_df = pd.concat(all_events, ignore_index=True)
        all_df.to_parquet(out_dir / "events_all.parquet", index=False)

    sweep_overall = pd.DataFrame(overall_rows)
    sweep_overall.to_csv(out_dir / "sweep_overall.csv", index=False)

    sweep_grid = pd.DataFrame(grid_rows)
    sweep_grid.to_csv(out_dir / "sweep_grid1d.csv", index=False)

    sweep_top = pd.DataFrame(top_cells_rows)
    sweep_top.to_csv(out_dir / "sweep_top_cells.csv", index=False)

    # Marginal tables (one per axis)
    for axis in sweep.keys():
        tbl = marginal_table(sweep_overall, defaults_for_sweep, axis)
        if not tbl.empty:
            tbl.to_csv(out_dir / f"sweep_{axis}.csv", index=False)
            print(f"\n--- marginal: {axis} ---")
            print(tbl.to_string(index=False))

    if cfg_path:
        n_events_default = 0
        if not sweep_overall.empty:
            m = pd.Series(True, index=sweep_overall.index)
            for k, v in defaults_for_sweep.items():
                m &= (sweep_overall[k] == v)
            base = sweep_overall[m & (sweep_overall["horizon_h"] == 168)]
            if len(base):
                n_events_default = int(base.iloc[0]["n"])
        results_summary = {
            "n_combos": len(combos),
            "n_events_default": n_events_default,
            "symbol_count": len(symbols),
        }
        update_config(cfg_path,
                       params={**defaults_for_sweep,
                                "n_quantiles": q,
                                "horizons_hours": horizons,
                                "min_history_weeks": min_history},
                       data={"symbol_count": len(symbols)},
                       results_summary=results_summary)


if __name__ == "__main__":
    main()
