"""Task 3 — quiet_bottom v2 보강 지표 평가.

backtest/strategies/_v2/quiet_bottom_v2 의 보강 (slope R² + 박치기 카운트) 가
KR/US 1w Sharpe 를 개선하는지 baseline (보강 off, 기존 quiet_bottom 과 동일) 대비 측정.

평가 조합:
  - baseline               : 보강 둘 다 off (= 기존 quiet_bottom 재현 sanity check)
  - slope_only             : slope R² 만 on (R²_min ∈ {0.50, 0.60, 0.70})
  - crossup_only           : 박치기만 on (max ∈ {2, 3})
  - both                   : 둘 다 on (조합)

자산: KR / US 1w (Round 1 best: KR Sharpe 5.70, US 4.01)
청산: hold_52w + trail 0.20 + TP 0.30
universe: 자산별 top 300
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.optimize.threshold_grid import (  # noqa: E402
    BARS_PER_YEAR, COST_RT, MIN_BARS, SINCE,
    ExitRule, _files_for, _loader, _summarize_trades, simulate,
)
from scripts.optimize.strategy_param_grid import _cached_universe, OUT_DIR

from backtest.strategies import quiet_bottom as qb_v1  # noqa: E402
from backtest.strategies._v2 import quiet_bottom_v2 as qb_v2  # noqa: E402


def _eval_signal(asset: str, interval: str, strat_mod, params: dict,
                 universe: set, exit_rule: ExitRule, verbose=False) -> dict:
    loader = _loader(asset)
    files = _files_for(asset, interval)
    min_bars = MIN_BARS[interval]
    cost = COST_RT[asset]
    bars_per_year = BARS_PER_YEAR[interval]

    trades = []
    n_proc = 0
    for p in files:
        symbol = p.stem
        if symbol not in universe:
            continue
        try:
            df = loader(p, interval)
        except Exception:
            continue
        if df is None or df.empty or len(df) < min_bars:
            continue
        try:
            df_reset = df.reset_index(drop=True)
            sig = strat_mod.signal(df_reset, params).astype("int8").to_numpy()
        except Exception as e:
            if verbose:
                print(f"  {symbol}: signal fail {type(e).__name__}: {e}")
            continue
        close = df["close"].astype("float64").to_numpy()
        dt_index = df.index
        if isinstance(dt_index, pd.DatetimeIndex):
            mask = np.asarray(dt_index >= SINCE).astype("int8")
        else:
            mask = np.array([1 if pd.Timestamp(d) >= SINCE else 0 for d in dt_index], dtype="int8")
        sig = sig * mask
        if sig.sum() == 0:
            continue
        prev = np.concatenate([[0], sig[:-1]])
        entries = np.where((sig == 1) & (prev == 0))[0]
        if len(entries) == 0:
            continue
        last_exit = -1
        for pos in entries:
            if pos <= last_exit:
                continue
            exit_pos, gross = simulate(close, int(pos), exit_rule)
            net = gross - cost
            trades.append({"held_bars": exit_pos - pos, "net_ret": net})
            last_exit = exit_pos
        n_proc += 1
    return _summarize_trades(trades, bars_per_year)


def main():
    exit_rule = ExitRule("hold_52w_trail20_TP30", max_hold=52,
                         trailing_pct=0.20, take_profit_pct=0.30)
    interval = "1w"

    configs = [
        # name, strat_mod, params
        ("v1_baseline_kr", qb_v1, {}),  # 기존 quiet_bottom (sanity check)
        ("v2_off",         qb_v2, {"use_slope_r2_filter": False, "use_crossup_filter": False}),
        # slope R² only
        ("v2_slope_r2_0.50", qb_v2, {"use_slope_r2_filter": True, "slope_r2_min": 0.50, "use_crossup_filter": False}),
        ("v2_slope_r2_0.60", qb_v2, {"use_slope_r2_filter": True, "slope_r2_min": 0.60, "use_crossup_filter": False}),
        ("v2_slope_r2_0.70", qb_v2, {"use_slope_r2_filter": True, "slope_r2_min": 0.70, "use_crossup_filter": False}),
        # crossup only
        ("v2_crossup_2",     qb_v2, {"use_slope_r2_filter": False, "use_crossup_filter": True, "crossup_max": 2}),
        ("v2_crossup_3",     qb_v2, {"use_slope_r2_filter": False, "use_crossup_filter": True, "crossup_max": 3}),
        # both combined
        ("v2_both_r0.60_c2", qb_v2, {"use_slope_r2_filter": True, "slope_r2_min": 0.60, "use_crossup_filter": True, "crossup_max": 2}),
        ("v2_both_r0.60_c3", qb_v2, {"use_slope_r2_filter": True, "slope_r2_min": 0.60, "use_crossup_filter": True, "crossup_max": 3}),
        ("v2_both_r0.70_c2", qb_v2, {"use_slope_r2_filter": True, "slope_r2_min": 0.70, "use_crossup_filter": True, "crossup_max": 2}),
        ("v2_both_r0.70_c3", qb_v2, {"use_slope_r2_filter": True, "slope_r2_min": 0.70, "use_crossup_filter": True, "crossup_max": 3}),
    ]

    all_rows = []
    for asset in ("kr", "us"):
        print(f"\n=== quiet_bottom v2 — asset={asset} interval={interval} ===", flush=True)
        uni = _cached_universe(asset, 300)
        print(f"  universe={len(uni)}", flush=True)
        for name, strat_mod, params in configs:
            # v1 baseline 은 KR/US 모두에서 동일하게 한 번씩 평가
            t0 = time.time()
            try:
                s = _eval_signal(asset, interval, strat_mod, params, uni, exit_rule)
            except Exception as e:
                print(f"  {name}: FAIL {e}", flush=True)
                s = {"n": 0, "win_pct": 0, "mean_pct": 0, "median_pct": 0,
                     "total_pct": 0, "mdd_pct": 0, "sharpe": 0, "profit_factor": 0,
                     "avg_held_bars": 0}
            elapsed = time.time() - t0
            print(f"  {name:<22} n={s['n']:>4} win%={s['win_pct']:>5.1f} "
                  f"mean%={s['mean_pct']:>+6.2f} sharpe={s['sharpe']:>+5.2f} "
                  f"PF={s['profit_factor']:>5.2f} MDD%={s['mdd_pct']:>+5.1f} "
                  f"({elapsed:.1f}s)", flush=True)
            row = {"asset": asset, "config": name, "strat_mod": strat_mod.NAME,
                   **{f"p_{k}": v for k, v in params.items()}, **s}
            all_rows.append(row)

    df = pd.DataFrame(all_rows)
    out_csv = OUT_DIR / "quiet_bottom_v2_eval.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nsaved: {out_csv}", flush=True)


if __name__ == "__main__":
    main()
