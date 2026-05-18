"""Cycle 2: 청산 미세 그리드 확장 + (선택) 전략 내부 파라미터 + quiet KR 진단.

A. 청산 미세 그리드 (필수)
    - US trend_pullback 1d, th=70
    - KR trend_chase    1d, th=60
    - US trend_chase    1d, th=60
   각각 trail ∈ {0.15,0.18,0.20,0.22,0.25} × TP ∈ {0.20,0.25,0.30,0.35} × hold ∈ {180,252}

B. KR trend_pullback 1d 전략 내부 파라미터 (시간 남으면)
    rally_lookback ∈ {30,45,60,80,100}
    depth_lookback ∈ {15,25,35}
    react_volume_ma ∈ {15,20,30}
    score_th=60, 청산 = Cycle1 best (hold=252, trail=0.25, TP=0.35)

C. KR quiet_bottom 1w score 게이트 강화 진단 (보너스)
    (avg_dd_104w, path_r2_52w) ∈ {(-0.45,0.50)(base),(-0.50,0.50),(-0.45,0.40),(-0.50,0.40)}
    청산 = hold_52w_trail20_TP30

전부 캐시 전용. 라이브 fetch 금지.
산출:
  scripts/out/optimize/deep/grids/cycle2_exit_micro_us_pullback.csv
  scripts/out/optimize/deep/grids/cycle2_exit_micro_kr_chase.csv
  scripts/out/optimize/deep/grids/cycle2_exit_micro_us_chase.csv
  scripts/out/optimize/deep/grids/cycle2_strategy_params_kr_pullback.csv (B 수행 시)
  scripts/out/optimize/deep/grids/cycle2_quiet_kr_gate.csv (C 수행 시)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import trend_chase, trend_pullback, quiet_bottom  # noqa: E402
from scripts.optimize_grid import ExitRule, simulate, COST_RT  # noqa: E402
from scripts.trend_strategies.forward_returns import (  # noqa: E402
    load_stock, KR_DIR, US_DIR,
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
TEST_END    = pd.Timestamp("2026-05-17")


# ---------------------------------------------------------------------------
# Universe (mirror of cycle1)
# ---------------------------------------------------------------------------
def kr_universe_cached(top_n: int) -> set:
    cache_stems = {p.stem for p in KR_DIR.glob("*.parquet") if not p.stem.startswith("_")}
    snap_path = KR_DIR / "_live_snapshot.parquet"
    if snap_path.exists():
        try:
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
        except Exception:
            pass
    return set(sorted(cache_stems)[:top_n])


def us_universe_cached(top_n: int) -> set:
    cache_stems = {p.stem for p in US_DIR.glob("*.parquet") if not p.stem.startswith("_")}
    snap_path = US_DIR / "_live_snapshot.parquet"
    if snap_path.exists():
        try:
            snap = pd.read_parquet(snap_path)
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
        except Exception:
            pass
    return set(sorted(cache_stems)[:top_n])


# ---------------------------------------------------------------------------
# build_cache stores raw close + dt only; we compute score/signal lazily so
# that parts B & C (which vary internal params) can reuse the price cache.
# ---------------------------------------------------------------------------
def build_price_cache(asset: str, interval: str) -> Dict[str, Tuple[np.ndarray, np.ndarray, pd.DataFrame]]:
    """Returns {symbol: (close, dt_arr, df_reset)} for given asset/interval."""
    min_bars = MIN_BARS[interval]
    if asset == "kr":
        universe = kr_universe_cached(UNIVERSE_TOP)
        files = [p for p in sorted(KR_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    elif asset == "us":
        universe = us_universe_cached(UNIVERSE_TOP)
        files = [p for p in sorted(US_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    else:
        raise ValueError(asset)

    cache: Dict[str, Tuple[np.ndarray, np.ndarray, pd.DataFrame]] = {}
    n_done = n_skip = 0
    t0 = time.time()
    for p in files:
        symbol = p.stem
        if symbol not in universe:
            continue
        try:
            df = load_stock(p, interval)
        except Exception:
            n_skip += 1
            continue
        if df is None or df.empty or len(df) < min_bars:
            n_skip += 1
            continue
        df = df.sort_index()
        df_r = df.reset_index(drop=True)
        close = df["close"].astype("float64").to_numpy()
        dt_arr = pd.DatetimeIndex(df.index).to_numpy()
        cache[symbol] = (close, dt_arr, df_r)
        n_done += 1
        if n_done % 100 == 0:
            print(f"    [{asset}/{interval}] loaded {n_done} (skip {n_skip})", flush=True)
    print(f"    [{asset}/{interval}] price cache done: {n_done} symbols, skip {n_skip}, {time.time()-t0:.1f}s", flush=True)
    return cache


def compute_signal_cache(
    price_cache: Dict[str, Tuple[np.ndarray, np.ndarray, pd.DataFrame]],
    strategy_name: str,
    params: dict,
) -> Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Returns {symbol: (close, value, dt_arr)} where value is score or signal."""
    strat = STRATEGIES[strategy_name]
    is_quiet = strategy_name == "quiet_bottom"
    cache: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    n_done = n_skip = 0
    t0 = time.time()
    for symbol, (close, dt_arr, df_r) in price_cache.items():
        try:
            if is_quiet:
                v = strat.signal(df_r, params).to_numpy().astype("int8")
            else:
                v = strat.score(df_r, params).to_numpy().astype("float32")
        except Exception:
            n_skip += 1
            continue
        cache[symbol] = (close, v, dt_arr)
        n_done += 1
    print(f"    signal cache [{strategy_name}] params={params}: {n_done} symbols, skip {n_skip}, {time.time()-t0:.1f}s", flush=True)
    return cache


# ---------------------------------------------------------------------------
# run_window — identical to cycle1
# ---------------------------------------------------------------------------
def run_window(
    cache: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]],
    asset: str,
    strategy_name: str,
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
# A. exit micro grid
# ---------------------------------------------------------------------------
TRAILS = [0.15, 0.18, 0.20, 0.22, 0.25]
TPS = [0.20, 0.25, 0.30, 0.35]
HOLDS = [180, 252]


def run_exit_micro_grid(
    cache: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]],
    asset: str,
    strategy_name: str,
    interval: str,
    score_th: int,
    out_name: str,
) -> pd.DataFrame:
    ws, we = TRAIN_START, TEST_END
    rows = []
    total = len(TRAILS) * len(TPS) * len(HOLDS)
    i = 0
    print(f"\n--- exit micro grid: {asset}/{strategy_name}/{interval} th={score_th} ({total} combos) ---", flush=True)
    for h in HOLDS:
        for tr in TRAILS:
            for tp in TPS:
                i += 1
                rule = ExitRule(
                    name=f"hold_{h}d_trail{int(tr*100)}_TP{int(tp*100)}",
                    max_hold=h, trailing_pct=tr, take_profit_pct=tp,
                )
                try:
                    s = run_window(cache, asset, strategy_name, score_th, rule, ws, we)
                except Exception as e:
                    print(f"  FAIL {rule.name}: {type(e).__name__}: {e}", flush=True)
                    s = {"n": 0, "win%": 0, "mean%": 0, "median%": 0, "held": 0,
                         "total%": 0, "MDD%": 0, "Sharpe_ann": 0, "PF": 0}
                row = {
                    "asset": asset, "strategy": strategy_name, "interval": interval,
                    "score_th": score_th, "rule": rule.name,
                    "hold": h, "trail_pct": tr, "take_profit_pct": tp,
                    **s,
                }
                rows.append(row)
                print(f"  [{i}/{total}] {rule.name}: n={s['n']} mean={s['mean%']}% "
                      f"Sharpe={s['Sharpe_ann']} PF={s['PF']}", flush=True)
    df = pd.DataFrame(rows)
    out_csv = OUT_DIR / out_name
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"saved: {out_csv}", flush=True)
    return df


# ---------------------------------------------------------------------------
# B. strategy internal params (KR pullback 1d)
# ---------------------------------------------------------------------------
BEST_KR_PULLBACK_RULE = ExitRule(
    name="hold_252d_trail25_TP35",
    max_hold=252, trailing_pct=0.25, take_profit_pct=0.35,
)


def run_strategy_params_kr_pullback(
    price_cache: Dict[str, Tuple[np.ndarray, np.ndarray, pd.DataFrame]],
    short: bool = False,
) -> pd.DataFrame:
    rallies = [30, 45, 60, 80, 100]
    depths = [15, 25, 35]
    rvols = [15, 20, 30]
    if short:
        depths = [25]
        rvols = [20]
    ws, we = TRAIN_START, TEST_END
    rows = []
    total = len(rallies) * len(depths) * len(rvols)
    i = 0
    print(f"\n--- strategy param grid: kr/trend_pullback/1d ({total} combos) ---", flush=True)
    for rl in rallies:
        for dl in depths:
            for rv in rvols:
                i += 1
                params = {"rally_lookback": rl, "depth_lookback": dl, "react_volume_ma": rv}
                try:
                    sig_cache = compute_signal_cache(price_cache, "trend_pullback", params)
                    s = run_window(sig_cache, "kr", "trend_pullback", 60,
                                   BEST_KR_PULLBACK_RULE, ws, we)
                except Exception as e:
                    print(f"  FAIL params={params}: {type(e).__name__}: {e}", flush=True)
                    s = {"n": 0, "win%": 0, "mean%": 0, "median%": 0, "held": 0,
                         "total%": 0, "MDD%": 0, "Sharpe_ann": 0, "PF": 0}
                row = {
                    "asset": "kr", "strategy": "trend_pullback", "interval": "1d",
                    "score_th": 60, "rule": BEST_KR_PULLBACK_RULE.name,
                    "rally_lookback": rl, "depth_lookback": dl, "react_volume_ma": rv,
                    **s,
                }
                rows.append(row)
                print(f"  [{i}/{total}] rally={rl} depth={dl} rvol={rv}: "
                      f"n={s['n']} mean={s['mean%']}% Sharpe={s['Sharpe_ann']} PF={s['PF']}", flush=True)
    df = pd.DataFrame(rows)
    out_csv = OUT_DIR / "cycle2_strategy_params_kr_pullback.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"saved: {out_csv}", flush=True)
    return df


# ---------------------------------------------------------------------------
# C. quiet_bottom KR 1w gate tightening
# ---------------------------------------------------------------------------
QUIET_RULE = ExitRule(
    name="hold_52w_trail20_TP30",
    max_hold=52, trailing_pct=0.20, take_profit_pct=0.30,
)


def run_quiet_kr_gate(
    price_cache_1w: Dict[str, Tuple[np.ndarray, np.ndarray, pd.DataFrame]],
) -> pd.DataFrame:
    gate_grid = [
        (-0.45, 0.50),  # base
        (-0.50, 0.50),
        (-0.45, 0.40),
        (-0.50, 0.40),
    ]
    ws, we = TRAIN_START, TEST_END
    rows = []
    print(f"\n--- quiet_bottom KR 1w gate grid ({len(gate_grid)} combos) ---", flush=True)
    for i, (dd_max, r2_max) in enumerate(gate_grid, 1):
        params = {"dd_avg_max": dd_max, "path_r2_max": r2_max}
        try:
            sig_cache = compute_signal_cache(price_cache_1w, "quiet_bottom", params)
            s = run_window(sig_cache, "kr", "quiet_bottom", 0, QUIET_RULE, ws, we)
        except Exception as e:
            print(f"  FAIL params={params}: {type(e).__name__}: {e}", flush=True)
            s = {"n": 0, "win%": 0, "mean%": 0, "median%": 0, "held": 0,
                 "total%": 0, "MDD%": 0, "Sharpe_ann": 0, "PF": 0}
        row = {
            "asset": "kr", "strategy": "quiet_bottom", "interval": "1w",
            "rule": QUIET_RULE.name,
            "dd_avg_max": dd_max, "path_r2_max": r2_max,
            **s,
        }
        rows.append(row)
        print(f"  [{i}/{len(gate_grid)}] dd_max={dd_max} r2_max={r2_max}: "
              f"n={s['n']} mean={s['mean%']}% Sharpe={s['Sharpe_ann']} PF={s['PF']}", flush=True)
    df = pd.DataFrame(rows)
    out_csv = OUT_DIR / "cycle2_quiet_kr_gate.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"saved: {out_csv}", flush=True)
    return df


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    t0 = time.time()
    print("=== Cycle 2 (cache-only) ===", flush=True)
    BUDGET_SEC = 50 * 60  # 50 min safety budget (target 55 min total incl. overhead)

    # --- Part A (mandatory) ----------------------------------------------
    # Build price caches once
    print("\n[A.1] US 1d price cache", flush=True)
    us_1d_prices = build_price_cache("us", "1d")
    print("\n[A.2] KR 1d price cache", flush=True)
    kr_1d_prices = build_price_cache("kr", "1d")

    # Build signal caches per strategy (default params)
    print("\n[A.3] signal caches (default params)", flush=True)
    us_pullback_sig = compute_signal_cache(us_1d_prices, "trend_pullback", {})
    us_chase_sig    = compute_signal_cache(us_1d_prices, "trend_chase",    {})
    kr_chase_sig    = compute_signal_cache(kr_1d_prices, "trend_chase",    {})

    # Run 3 micro grids
    try:
        run_exit_micro_grid(us_pullback_sig, "us", "trend_pullback", "1d", 70,
                            "cycle2_exit_micro_us_pullback.csv")
    except Exception as e:
        import traceback
        print(f"A.US pullback FAIL: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()

    try:
        run_exit_micro_grid(kr_chase_sig, "kr", "trend_chase", "1d", 60,
                            "cycle2_exit_micro_kr_chase.csv")
    except Exception as e:
        import traceback
        print(f"A.KR chase FAIL: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()

    try:
        run_exit_micro_grid(us_chase_sig, "us", "trend_chase", "1d", 60,
                            "cycle2_exit_micro_us_chase.csv")
    except Exception as e:
        import traceback
        print(f"A.US chase FAIL: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()

    elapsed = time.time() - t0
    print(f"\n=== Part A done in {elapsed:.1f}s ===", flush=True)

    # --- Part B (optional) -----------------------------------------------
    if elapsed < BUDGET_SEC - 12 * 60:
        # at least 12 min budget left → run param grid (likely 5x3x3=45 combos
        # but signal recompute is heavy; we'll let it run and stop after the time budget if needed)
        print(f"\n[B] strategy params (full grid) — budget remaining {BUDGET_SEC - elapsed:.0f}s", flush=True)
        try:
            short = (BUDGET_SEC - elapsed) < 25 * 60  # under 25 min → short variant (rally only)
            run_strategy_params_kr_pullback(kr_1d_prices, short=short)
        except Exception as e:
            import traceback
            print(f"B FAIL: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
    else:
        print(f"\n[B] skipped — only {BUDGET_SEC - elapsed:.0f}s budget left", flush=True)

    elapsed = time.time() - t0
    print(f"\n=== After Part B: {elapsed:.1f}s ===", flush=True)

    # --- Part C (bonus) --------------------------------------------------
    if elapsed < BUDGET_SEC - 5 * 60:
        print(f"\n[C] quiet_bottom KR 1w gate — budget remaining {BUDGET_SEC - elapsed:.0f}s", flush=True)
        try:
            kr_1w_prices = build_price_cache("kr", "1w")
            run_quiet_kr_gate(kr_1w_prices)
        except Exception as e:
            import traceback
            print(f"C FAIL: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
    else:
        print(f"\n[C] skipped — only {BUDGET_SEC - elapsed:.0f}s budget left", flush=True)

    print(f"\nTotal elapsed: {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
