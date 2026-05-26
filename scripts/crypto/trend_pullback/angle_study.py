"""Event study: 1H impulse (>=10%) -> MA10/MA20 touch within MA-specific window.

For each impulse event we track MA10 and MA20 touches SEPARATELY:
  - MA10 lookback = 15 bars  (mathematically MA10 catches price in ~9 bars)
  - MA20 lookback = 30 bars  (MA20 catches price in ~19 bars)
  - Same impulse can hit MA10 only, MA20 only, both, or neither.

Both axes of the pullback are recorded:
  - angle_per_bar = drop_pct / bars_to_touch  (per-bar slope)
  - bars_to_touch (time bucket, 5-bar bins)

Outputs (under <run_dir>/output/, created by /study init):
  events.parquet              - per-impulse rows
  angle_study_summary.csv     - group summary

Run:
  .venv/Scripts/python.exe -m scripts.trend_pullback.angle_study \
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

# Module-level params (defaults; overridable via --config / --out-dir + CLI)
IMPULSE_RET_MIN = 0.07           # (close-open)/open >= X
VOL_MULT_MIN = 5.0               # vol >= X * prev-10-bar avg; None = skip filter
TOUCH_PAD = 0.005                # low <= MA * (1 + pad)
HORIZONS = [1, 6, 24, 72, 168]   # 1H bars

MA_CFG = {
    10: {"lookahead": 10, "bins": [(1, 3), (4, 6), (7, 10)]},
    20: {"lookahead": 20, "bins": [(1, 7), (8, 14), (15, 20)]},
}

ANGLE_BINS = [-np.inf, -0.030, -0.015, -0.007, -0.003, np.inf]
ANGLE_LABELS = ["G5 very_steep (<-3%/bar)",
                "G4 steep (-3 ~ -1.5)",
                "G3 normal (-1.5 ~ -0.7)",
                "G2 gentle (-0.7 ~ -0.3)",
                "G1 flat (>-0.3)"]


def load_symbols() -> list:
    return sorted(p.stem for p in CACHE_DIR.glob("*.parquet"))


def get_1w_ma20(symbol: str) -> Optional[pd.DataFrame]:
    """1W MA10 + MA20 value+slope (lagged 1 week)."""
    try:
        from data.resample import load as load_resampled
        df_1w = load_resampled(symbol, "1w")
    except Exception:
        return None
    if df_1w is None or len(df_1w) < 2:
        return None
    df_1w = df_1w.sort_values("timestamp").reset_index(drop=True)
    ma10 = df_1w["close"].rolling(10, min_periods=10).mean()
    ma20 = df_1w["close"].rolling(20, min_periods=20).mean()
    df_1w["ma10_1w"] = ma10.shift(1)
    df_1w["ma10_1w_slope_up"] = (ma10.diff() > 0).shift(1)
    df_1w["ma20_1w"] = ma20.shift(1)
    df_1w["ma20_1w_slope_up"] = (ma20.diff() > 0).shift(1)
    return df_1w[["timestamp", "ma10_1w", "ma10_1w_slope_up",
                   "ma20_1w", "ma20_1w_slope_up"]].copy()


def get_1d_ma20_slope(symbol: str) -> Optional[pd.DataFrame]:
    """1D MA20 slope flag (for new-coin gate)."""
    try:
        from data.resample import load as load_resampled
        df_1d = load_resampled(symbol, "1d")
    except Exception:
        return None
    if df_1d is None or len(df_1d) < 22:
        return None
    df_1d = df_1d.sort_values("timestamp").reset_index(drop=True)
    ma20 = df_1d["close"].rolling(20, min_periods=20).mean()
    df_1d["ma20_1d_slope_up"] = (ma20.diff() > 0).shift(1)
    return df_1d[["timestamp", "ma20_1d_slope_up"]].copy()


def _first_touch(low: np.ndarray, ma: np.ndarray, i: int, lookahead: int, n: int):
    """Return (touch_idx, t_low, t_close placeholder) or None."""
    end = min(i + lookahead, n - 1)
    if end <= i:
        return None
    win_low = low[i + 1 : end + 1]
    win_ma = ma[i + 1 : end + 1]
    hits = win_low <= win_ma * (1.0 + TOUCH_PAD)
    if not hits.any():
        return None
    rel = int(np.argmax(hits))
    return i + 1 + rel


def find_events_for_symbol(symbol: str) -> Optional[pd.DataFrame]:
    path = CACHE_DIR / f"{symbol}.parquet"
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None
    if len(df) < 200:
        return None

    df = df.sort_values("timestamp").reset_index(drop=True)

    # GATE: 1W MA10 slope > 0
    ma_1w_df = get_1w_ma20(symbol)
    if ma_1w_df is None:
        return None
    df = pd.merge_asof(df, ma_1w_df, on="timestamp", direction="backward")

    open_ = df["open"].astype("float64").to_numpy()
    low = df["low"].astype("float64").to_numpy()
    close = df["close"].astype("float64").to_numpy()
    volume = df["volume"].astype("float64").to_numpy()
    ts = df["timestamp"].astype("int64").to_numpy()
    slope_w_ma20 = df["ma20_1w_slope_up"].fillna(False).to_numpy().astype(bool)
    n = len(df)

    bar_ret = (close - open_) / np.where(open_ > 0, open_, np.nan)
    if VOL_MULT_MIN is not None and VOL_MULT_MIN > 0:
        vol_avg10 = pd.Series(volume).rolling(10, min_periods=10).mean().shift(1).to_numpy()
        vol_filter = np.where(np.isfinite(vol_avg10) & (vol_avg10 > 0),
                                volume >= vol_avg10 * VOL_MULT_MIN, False)
    else:
        vol_filter = np.ones_like(close, dtype=bool)
    impulse_idx = np.where((bar_ret >= IMPULSE_RET_MIN) & slope_w_ma20 & vol_filter)[0]
    if impulse_idx.size == 0:
        return None

    ma10 = pd.Series(close).rolling(10, min_periods=10).mean().to_numpy()
    ma20 = pd.Series(close).rolling(20, min_periods=20).mean().to_numpy()
    ma_arrs = {10: ma10, 20: ma20}

    rows = []
    for i in impulse_idx:
        if i + 1 >= n:
            continue
        impulse_close = float(close[i])
        row = {
            "symbol": symbol,
            "impulse_idx": int(i),
            "impulse_ts": int(ts[i]),
            "impulse_close": impulse_close,
            "impulse_ret": float(bar_ret[i]),
        }
        # impulse-close-based forward returns (chase view, has lookahead for untouched groups)
        for h in HORIZONS:
            j = i + h
            row[f"fwd_{h}h_imp"] = float(close[j] / impulse_close - 1.0) if j < n else np.nan

        # confirm-time forward returns (no lookahead): entry at close[i + lookahead]
        # used for untouched groups - the time you can actually confirm "untouched"
        for confirm_lb in (MA_CFG[10]["lookahead"], MA_CFG[20]["lookahead"]):
            c_idx = i + confirm_lb
            if c_idx < n:
                c_close = float(close[c_idx])
                row[f"confirm{confirm_lb}_close"] = c_close
                for h in HORIZONS:
                    j = c_idx + h
                    row[f"fwd_{h}h_cf{confirm_lb}"] = float(close[j] / c_close - 1.0) if j < n else np.nan
            else:
                row[f"confirm{confirm_lb}_close"] = np.nan
                for h in HORIZONS:
                    row[f"fwd_{h}h_cf{confirm_lb}"] = np.nan

        for ma in (10, 20):
            cfg = MA_CFG[ma]
            t_idx = _first_touch(low, ma_arrs[ma], i, cfg["lookahead"], n)
            if t_idx is None:
                row[f"touched_ma{ma}"] = False
                row[f"bars_to_touch_ma{ma}"] = np.nan
                row[f"touch_low_ma{ma}"] = np.nan
                row[f"touch_close_ma{ma}"] = np.nan
                row[f"drop_pct_ma{ma}"] = np.nan
                row[f"angle_per_bar_ma{ma}"] = np.nan
                for h in HORIZONS:
                    row[f"fwd_{h}h_ma{ma}"] = np.nan
            else:
                t_low = float(low[t_idx])
                t_close = float(close[t_idx])
                bars = int(t_idx - i)
                drop = (t_low / impulse_close) - 1.0
                angle = drop / bars if bars > 0 else 0.0
                row[f"touched_ma{ma}"] = True
                row[f"bars_to_touch_ma{ma}"] = bars
                row[f"touch_low_ma{ma}"] = t_low
                row[f"touch_close_ma{ma}"] = t_close
                row[f"drop_pct_ma{ma}"] = drop
                row[f"angle_per_bar_ma{ma}"] = angle
                for h in HORIZONS:
                    j = t_idx + h
                    row[f"fwd_{h}h_ma{ma}"] = float(close[j] / t_close - 1.0) if j < n else np.nan
        rows.append(row)

    if not rows:
        return None
    return pd.DataFrame(rows)


def collect_events(symbols: Optional[list] = None) -> pd.DataFrame:
    if symbols is None:
        symbols = load_symbols()
    print(f"[angle_study] symbols: {len(symbols)}")
    out = []
    t0 = time.time()
    for k, s in enumerate(symbols):
        ev = find_events_for_symbol(s)
        if ev is not None and len(ev) > 0:
            out.append(ev)
        if (k + 1) % 200 == 0:
            print(f"  [{k+1}/{len(symbols)}] elapsed={time.time()-t0:.1f}s, rows: {sum(len(x) for x in out)}")
    if not out:
        return pd.DataFrame()
    df = pd.concat(out, ignore_index=True)
    print(f"[angle_study] total events: {len(df)}  (elapsed {time.time()-t0:.1f}s)")
    return df


def _stats(s: pd.Series):
    s = s.dropna()
    if len(s) == 0:
        return np.nan, np.nan, np.nan
    return float(s.mean()), float(s.median()), float((s > 0).mean())


def _summary_row(grp: pd.DataFrame, fwd_prefix: str, label: str) -> dict:
    out = {"group": label, "n": int(len(grp))}
    for h in HORIZONS:
        col = f"{fwd_prefix}_{h}h_" + fwd_prefix.split("_")[-1] if False else None
    # simpler: explicit cols
    for h in HORIZONS:
        col = f"fwd_{h}h_{fwd_prefix}"
        mean, med, win = _stats(grp[col])
        out[f"{h}h_mean"] = mean
        out[f"{h}h_win"] = win
    return out


def summarize(events: pd.DataFrame) -> pd.DataFrame:
    """MA10-only analysis. All fwd returns measured from MA10 touch bar close
    (= purchase moment). Cross-tab uses bars-group-local angle QUANTILES for
    balanced cell sizes (each cell ~ 1/5 of its bars group)."""
    rows = []

    # baseline
    rows.append(_summary_row(events, "imp", "BASELINE: ALL impulses (imp-close)"))

    # MA10 touched ALL
    touched = events[events["touched_ma10"]].copy()
    rows.append(_summary_row(touched, "ma10",
                              f"MA10 touched within 10 (fr touch close)"))

    bars_col = "bars_to_touch_ma10"
    angle_col = "angle_per_bar_ma10"

    # by bars only
    for lo, hi in MA_CFG[10]["bins"]:
        sub = touched[(touched[bars_col] >= lo) & (touched[bars_col] <= hi)]
        rows.append(_summary_row(sub, "ma10",
                                  f"  MA10 bars {lo:>2}-{hi:>2} (ALL angles)"))

    # CROSS-TAB with per-bars-group QUANTILE bins (Q5 steepest .. Q1 flattest)
    QUANTILE_PROBS = [0.20, 0.40, 0.60, 0.80]
    Q_LABELS = ["Q5 steepest", "Q4", "Q3 median", "Q2", "Q1 flattest"]
    rows.append({"group": "--- CROSS-TAB: bars × angle (quantile bins) ---", "n": 0,
                  **{f"{h}h_mean": np.nan for h in HORIZONS},
                  **{f"{h}h_win": np.nan for h in HORIZONS}})

    for lo, hi in MA_CFG[10]["bins"]:
        bars_sub = touched[(touched[bars_col] >= lo) & (touched[bars_col] <= hi)].copy()
        if len(bars_sub) == 0:
            continue
        qs = bars_sub[angle_col].quantile(QUANTILE_PROBS).values
        # Q5 = steepest (most negative). Bin edges: -inf, q20, q40, q60, q80, +inf
        bin_edges = [-np.inf] + list(qs) + [np.inf]
        # show edges in header
        edge_str = f"q20={qs[0]*100:+.2f}%/봉, q40={qs[1]*100:+.2f}%, q60={qs[2]*100:+.2f}%, q80={qs[3]*100:+.2f}%"
        rows.append({"group": f"  [bars {lo}-{hi}] quantile edges: {edge_str}", "n": int(len(bars_sub)),
                      **{f"{h}h_mean": np.nan for h in HORIZONS},
                      **{f"{h}h_win": np.nan for h in HORIZONS}})

        bars_sub["_qbin"] = pd.cut(bars_sub[angle_col],
                                    bins=bin_edges, labels=Q_LABELS,
                                    include_lowest=True, right=True)
        for label in Q_LABELS:
            sub = bars_sub[bars_sub["_qbin"] == label]
            rows.append(_summary_row(sub, "ma10",
                                      f"  bars {lo:>2}-{hi:>2} × {label}"))

    return pd.DataFrame(rows)


def print_summary(summary: pd.DataFrame) -> None:
    print("\n=== mean forward returns ===")
    cols = ["group", "n"] + [f"{h}h_mean" for h in HORIZONS]
    view = summary[cols].copy()
    for h in HORIZONS:
        view[f"{h}h_mean"] = view[f"{h}h_mean"].apply(
            lambda x: f"{x*100:+.2f}%" if pd.notna(x) else "-")
    print(view.to_string(index=False))

    print("\n=== win rate (>0) ===")
    cols_w = ["group", "n"] + [f"{h}h_win" for h in HORIZONS]
    view_w = summary[cols_w].copy()
    for h in HORIZONS:
        view_w[f"{h}h_win"] = view_w[f"{h}h_win"].apply(
            lambda x: f"{x*100:.0f}%" if pd.notna(x) else "-")
    print(view_w.to_string(index=False))


def main() -> int:
    global IMPULSE_RET_MIN, VOL_MULT_MIN, TOUCH_PAD
    from scripts._common.run_helper import parse_args, update_config, resolve_config_path

    def add_args(ap):
        ap.add_argument("--impulse-min", type=float, default=None,
                        help="impulse threshold (close-open)/open")
        ap.add_argument("--vol-mult-min", type=float, default=None,
                        help="volume / prev-10-bar avg; 0 or None = skip filter")
        ap.add_argument("--touch-pad", type=float, default=None,
                        help="low <= MA * (1 + pad)")

    defaults = {
        "impulse_min": IMPULSE_RET_MIN,
        "vol_mult_min": VOL_MULT_MIN,
        "touch_pad": TOUCH_PAD,
    }
    out_dir, params, args = parse_args(add_args, defaults, "angle_study")

    # apply params to module constants
    IMPULSE_RET_MIN = float(params["impulse_min"])
    VOL_MULT_MIN = (float(params["vol_mult_min"])
                    if params.get("vol_mult_min") not in (None, 0, 0.0)
                    else None)
    TOUCH_PAD = float(params["touch_pad"])

    events = collect_events()
    if events.empty:
        print("No events found.")
        return 1

    events_path = out_dir / "events.parquet"
    events.to_parquet(events_path, index=False)
    print(f"saved: {events_path}")

    n_imp = len(events)
    n_ma10 = int(events["touched_ma10"].sum())
    n_ma20 = int(events["touched_ma20"].sum())
    n_both = int(((events["touched_ma10"]) & (events["touched_ma20"])).sum())
    n_neither = int(((~events["touched_ma10"]) & (~events["touched_ma20"])).sum())
    print(f"\nimpulses={n_imp}")
    print(f"  touched MA10 within {MA_CFG[10]['lookahead']}:  {n_ma10} ({100*n_ma10/n_imp:.1f}%)")
    print(f"  touched MA20 within {MA_CFG[20]['lookahead']}:  {n_ma20} ({100*n_ma20/n_imp:.1f}%)")
    print(f"  touched BOTH (deep):     {n_both} ({100*n_both/n_imp:.1f}%)")
    print(f"  touched NEITHER (chase): {n_neither} ({100*n_neither/n_imp:.1f}%)")

    summary = summarize(events)
    summary_path = out_dir / "angle_study_summary.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8")
    print(f"saved: {summary_path}")
    print_summary(summary)

    # write back params + data into config.json
    cfg_path = resolve_config_path(args)
    if cfg_path is not None:
        update_config(cfg_path,
                       params={
                           "impulse_min": IMPULSE_RET_MIN,
                           "vol_mult_min": VOL_MULT_MIN,
                           "touch_pad": TOUCH_PAD,
                           "gate": "1W_MA20_slope_up",
                           "horizons": HORIZONS,
                           "ma_lookahead": {"ma10": MA_CFG[10]["lookahead"],
                                              "ma20": MA_CFG[20]["lookahead"]},
                       },
                       data={
                           "asset": "crypto",
                           "interval": "1h",
                           "cache_dir": "data/cache/crypto/1h",
                           "symbol_count": len(load_symbols()),
                       },
                       results_summary={
                           "n_impulses": n_imp,
                           "n_touched_ma10": n_ma10,
                           "n_touched_ma20": n_ma20,
                           "n_both": n_both,
                           "n_neither": n_neither,
                       })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
