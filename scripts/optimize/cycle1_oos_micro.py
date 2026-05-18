"""Cycle 1 재가동: OOS split 검증 + KR 청산 미세 그리드.

원칙:
  - 라이브 fetch 금지. universe 는 _live_snapshot.parquet 의 marketValue (KR),
    또는 amount/marketValueRaw (US) top-N 으로 캐시 stem 교집합.
  - optimize_grid 의 simulate / summarize_trades / ExitRule 재사용.
  - 기간 split:
        train: 2020-05-17 ~ 2024-05-16
        test:  2024-05-17 ~ 2026-05-17
  - 대상 6 combos: KR/US × (trend_pullback 1d, trend_chase 1d, quiet_bottom 1w)
  - 미세 그리드: KR trend_pullback 1d, th=60,
        trail ∈ {0.15, 0.18, 0.20, 0.22, 0.25}
        TP    ∈ {0.20, 0.25, 0.30, 0.35}
        hold  ∈ {180d, 252d}

산출:
  scripts/out/optimize/deep/grids/cycle1_oos_split.csv
  scripts/out/optimize/deep/grids/cycle1_exit_micro_kr.csv
"""
from __future__ import annotations

import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import trend_chase, trend_pullback, quiet_bottom  # noqa: E402
from scripts.optimize_grid import (  # noqa: E402
    ExitRule, simulate, COST_RT,
)
from scripts.trend_strategies.forward_returns import (  # noqa: E402
    load_stock, load_crypto,
    KR_DIR, US_DIR, CRYPTO_1H_DIR, CRYPTO_1D_DIR,
)

OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "deep" / "grids"
OUT_DIR.mkdir(parents=True, exist_ok=True)

STRATEGIES = {
    "trend_chase": trend_chase,
    "trend_pullback": trend_pullback,
    "quiet_bottom": quiet_bottom,
}

UNIVERSE_TOP = 300
MIN_BARS = {"1d": 80, "1w": 30}

TRAIN_START = pd.Timestamp("2020-05-17")
TRAIN_END   = pd.Timestamp("2024-05-16")
TEST_START  = pd.Timestamp("2024-05-17")
TEST_END    = pd.Timestamp("2026-05-17")


# ---------------------------------------------------------------------------
# Universe — cache-only, snapshot-based ranking when available
# ---------------------------------------------------------------------------
def kr_universe_cached(top_n: int) -> set:
    cache_stems = {p.stem for p in KR_DIR.glob("*.parquet") if not p.stem.startswith("_")}
    snap_path = KR_DIR / "_live_snapshot.parquet"
    if snap_path.exists():
        snap = pd.read_parquet(snap_path)
        snap = snap.dropna(subset=["marketValue"]).sort_values("marketValue", ascending=False)
        ranked = snap["itemCode"].astype(str).tolist()
        picked = []
        for code in ranked:
            if code in cache_stems:
                picked.append(code)
            if len(picked) >= top_n:
                break
        if picked:
            return set(picked)
    # fallback: just sorted stems
    return set(sorted(cache_stems)[:top_n])


def us_universe_cached(top_n: int) -> set:
    cache_stems = {p.stem for p in US_DIR.glob("*.parquet") if not p.stem.startswith("_")}
    snap_path = US_DIR / "_live_snapshot.parquet"
    if snap_path.exists():
        snap = pd.read_parquet(snap_path)
        # try multiple possible ranking columns
        rank_col = None
        for c in ("marketValueRaw", "marketValue", "accumulatedTradingValue", "accumulatedTradingVolume"):
            if c in snap.columns and snap[c].notna().any():
                rank_col = c
                break
        if rank_col is not None:
            snap = snap.dropna(subset=[rank_col]).sort_values(rank_col, ascending=False)
            code_col = "symbolCode" if "symbolCode" in snap.columns else "itemCode"
            ranked = snap[code_col].astype(str).str.upper().tolist()
            picked = []
            for code in ranked:
                if code in cache_stems:
                    picked.append(code)
                if len(picked) >= top_n:
                    break
            if picked:
                return set(picked)
    return set(sorted(cache_stems)[:top_n])


# ---------------------------------------------------------------------------
# Cached signal/score build per symbol
# ---------------------------------------------------------------------------
def build_cache(asset: str, strategy_name: str, interval: str) -> Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Returns {symbol: (close, val, dt_array)}."""
    strat = STRATEGIES[strategy_name]
    is_quiet = strategy_name == "quiet_bottom"
    min_bars = MIN_BARS[interval]

    if asset == "kr":
        universe = kr_universe_cached(UNIVERSE_TOP)
        files = [p for p in sorted(KR_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
        loader = load_stock
    elif asset == "us":
        universe = us_universe_cached(UNIVERSE_TOP)
        files = [p for p in sorted(US_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
        loader = load_stock
    else:
        raise ValueError(asset)

    cache: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    n_done = n_skip = 0
    t0 = time.time()
    for p in files:
        symbol = p.stem
        if symbol not in universe:
            continue
        try:
            df = loader(p, interval)
        except Exception:
            n_skip += 1
            continue
        if df is None or df.empty or len(df) < min_bars:
            n_skip += 1
            continue
        df = df.sort_index()
        df_r = df.reset_index(drop=True)
        try:
            if is_quiet:
                v = strat.signal(df_r, {}).to_numpy().astype("int8")
            else:
                v = strat.score(df_r, {}).to_numpy().astype("float32")
        except Exception:
            n_skip += 1
            continue
        close = df["close"].astype("float64").to_numpy()
        dt_arr = pd.DatetimeIndex(df.index).to_numpy()  # datetime64[ns]
        cache[symbol] = (close, v, dt_arr)
        n_done += 1
        if n_done % 100 == 0:
            print(f"    [{asset}/{strategy_name}/{interval}] loaded {n_done} (skip {n_skip})", flush=True)
    print(f"    [{asset}/{strategy_name}/{interval}] cache done: {n_done} symbols, skip {n_skip}, {time.time()-t0:.1f}s", flush=True)
    return cache


# ---------------------------------------------------------------------------
# Run a single combo on a date window using fixed rule + threshold
# ---------------------------------------------------------------------------
def run_window(
    cache: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]],
    asset: str,
    strategy_name: str,
    interval: str,
    score_th,
    rule: ExitRule,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> dict:
    is_quiet = strategy_name == "quiet_bottom"
    cost = COST_RT[asset]
    start64 = np.datetime64(window_start, "ns")
    end64 = np.datetime64(window_end, "ns")
    trades: List[dict] = []
    for symbol, (close, val, dt_arr) in cache.items():
        if len(val) < 2:
            continue
        if is_quiet:
            sig01 = val
        else:
            sig01 = (val >= float(score_th)).astype("int8")
        diff = np.diff(sig01.astype("int16"), prepend=0)
        in_period = (dt_arr >= start64) & (dt_arr <= end64)
        enter_mask = (diff == 1) & in_period
        positions = np.where(enter_mask)[0]
        for pos in positions:
            if pos >= len(close) - 1:
                continue
            exit_pos, gross_ret = simulate(close, int(pos), rule)
            if exit_pos == pos:
                continue
            trades.append({
                "symbol": symbol,
                "held": exit_pos - pos,
                "gross_ret": gross_ret,
                "net_ret": gross_ret - cost,
            })
    # local summary (mirrors summarize_trades but with per-window Sharpe annualization)
    if not trades:
        return {"n": 0, "win%": 0, "mean%": 0, "median%": 0, "held": 0,
                "total%": 0, "MDD%": 0, "Sharpe_ann": 0, "PF": 0}
    df = pd.DataFrame(trades)
    rets = df["net_ret"].to_numpy()
    win = float((rets > 0).mean() * 100)
    mean = float(rets.mean() * 100)
    median = float(np.median(rets) * 100)
    held = float(df["held"].mean())
    eq = np.cumprod(1.0 + rets)
    total = float((eq[-1] - 1.0) * 100)
    peak = np.maximum.accumulate(eq)
    dd = float((eq / peak - 1.0).min() * 100)
    years = max(1e-9, (window_end - window_start).days / 365.25)
    if rets.std() > 0:
        sharpe_pt = rets.mean() / rets.std()
        annual_factor = np.sqrt(max(1, len(rets)) / years)
        sharpe_ann = float(sharpe_pt * annual_factor)
    else:
        sharpe_ann = 0.0
    gains = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = float(gains / losses) if losses > 0 else float("inf")
    return {
        "n": int(len(rets)), "win%": round(win, 1),
        "mean%": round(mean, 2), "median%": round(median, 2),
        "held": round(held, 1), "total%": round(total, 1),
        "MDD%": round(dd, 1), "Sharpe_ann": round(sharpe_ann, 2),
        "PF": round(pf, 2) if pf != float("inf") else 99.99,
    }


# ---------------------------------------------------------------------------
# B. OOS split
# ---------------------------------------------------------------------------
DEFAULT_RULE_1D = ExitRule("hold_252d_trail20_TP30", max_hold=252, trailing_pct=0.20, take_profit_pct=0.30)
DEFAULT_RULE_1W = ExitRule("hold_52w_trail20_TP30", max_hold=52, trailing_pct=0.20, take_profit_pct=0.30)

OOS_COMBOS = [
    # (asset, strategy, interval, score_th, rule)
    ("kr", "trend_pullback", "1d", 60, DEFAULT_RULE_1D),
    ("us", "trend_pullback", "1d", 70, DEFAULT_RULE_1D),
    ("kr", "trend_chase",    "1d", 60, DEFAULT_RULE_1D),
    ("us", "trend_chase",    "1d", 60, DEFAULT_RULE_1D),
    ("kr", "quiet_bottom",   "1w", "binary", DEFAULT_RULE_1W),
    ("us", "quiet_bottom",   "1w", "binary", DEFAULT_RULE_1W),
]


def run_oos_split() -> pd.DataFrame:
    rows = []
    # Cache per (asset, strategy, interval) so we don't recompute
    cache_pool: Dict[Tuple[str, str, str], Dict] = {}
    for (asset, strategy, interval, th, rule) in OOS_COMBOS:
        key = (asset, strategy, interval)
        if key not in cache_pool:
            print(f"\n=== build cache {key} ===", flush=True)
            try:
                cache_pool[key] = build_cache(asset, strategy, interval)
            except Exception as e:
                print(f"    cache build FAIL {key}: {type(e).__name__}: {e}", flush=True)
                cache_pool[key] = {}
        cache = cache_pool[key]
        if not cache:
            continue
        th_val = 0 if th == "binary" else th
        for period_name, ws, we in [
            ("train", TRAIN_START, TRAIN_END),
            ("test",  TEST_START,  TEST_END),
        ]:
            try:
                summary = run_window(cache, asset, strategy, interval, th_val, rule, ws, we)
            except Exception as e:
                print(f"    run_window FAIL {key} {period_name}: {type(e).__name__}: {e}", flush=True)
                summary = {"n": 0, "win%": 0, "mean%": 0, "median%": 0, "held": 0,
                           "total%": 0, "MDD%": 0, "Sharpe_ann": 0, "PF": 0}
            row = {
                "asset": asset, "strategy": strategy, "interval": interval,
                "score_th": th, "rule": rule.name,
                "period": period_name,
                "window_start": ws.date().isoformat(),
                "window_end": we.date().isoformat(),
                **summary,
            }
            rows.append(row)
            print(f"  {asset}/{strategy}/{interval} th={th} [{period_name}]: "
                  f"n={summary['n']} win={summary['win%']}% mean={summary['mean%']}% "
                  f"Sharpe={summary['Sharpe_ann']} PF={summary['PF']}", flush=True)
    df = pd.DataFrame(rows)
    out_csv = OUT_DIR / "cycle1_oos_split.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nsaved: {out_csv}", flush=True)
    return df


# ---------------------------------------------------------------------------
# C. Micro grid (KR trend_pullback 1d)
# ---------------------------------------------------------------------------
def run_micro_kr() -> pd.DataFrame:
    print(f"\n=== build cache for micro grid: kr/trend_pullback/1d ===", flush=True)
    cache = build_cache("kr", "trend_pullback", "1d")
    if not cache:
        print("  empty cache — skipping micro grid", flush=True)
        return pd.DataFrame()
    th = 60
    trails = [0.15, 0.18, 0.20, 0.22, 0.25]
    tps    = [0.20, 0.25, 0.30, 0.35]
    holds  = [180, 252]
    # Use full period (train+test) for evaluation
    ws, we = TRAIN_START, TEST_END
    rows = []
    total = len(trails) * len(tps) * len(holds)
    i = 0
    for h in holds:
        for tr in trails:
            for tp in tps:
                i += 1
                rule = ExitRule(
                    name=f"hold_{h}d_trail{int(tr*100)}_TP{int(tp*100)}",
                    max_hold=h, trailing_pct=tr, take_profit_pct=tp,
                )
                try:
                    s = run_window(cache, "kr", "trend_pullback", "1d", th, rule, ws, we)
                except Exception as e:
                    print(f"  FAIL {rule.name}: {type(e).__name__}: {e}", flush=True)
                    s = {"n": 0, "win%": 0, "mean%": 0, "median%": 0, "held": 0,
                         "total%": 0, "MDD%": 0, "Sharpe_ann": 0, "PF": 0}
                row = {
                    "asset": "kr", "strategy": "trend_pullback", "interval": "1d",
                    "score_th": th, "rule": rule.name,
                    "hold": h, "trail_pct": tr, "take_profit_pct": tp,
                    **s,
                }
                rows.append(row)
                print(f"  [{i}/{total}] {rule.name}: n={s['n']} mean={s['mean%']}% "
                      f"Sharpe={s['Sharpe_ann']} PF={s['PF']}", flush=True)
    df = pd.DataFrame(rows)
    out_csv = OUT_DIR / "cycle1_exit_micro_kr.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"saved: {out_csv}", flush=True)
    return df


def main():
    t0 = time.time()
    print("=== Cycle 1 OOS + Micro (cache-only) ===", flush=True)
    df_oos = pd.DataFrame()
    df_mic = pd.DataFrame()
    try:
        df_oos = run_oos_split()
    except Exception as e:
        import traceback
        print(f"OOS split FAIL: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
    try:
        df_mic = run_micro_kr()
    except Exception as e:
        import traceback
        print(f"Micro grid FAIL: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
    print(f"\nTotal elapsed: {time.time()-t0:.1f}s", flush=True)
    return df_oos, df_mic


if __name__ == "__main__":
    main()
