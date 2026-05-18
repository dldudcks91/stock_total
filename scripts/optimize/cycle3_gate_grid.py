"""Cycle 3 — 진입 보조 게이트 OAT (one-at-a-time) 그리드.

Cycle 1 OOS 살아남은 6 조합에 대해 보조 게이트 파라미터를 하나씩 sweep.
- threshold = Cycle 1 OOS best (조합별)
- 청산 룰 = Cycle 1 검증된 hold_252d+trail20+TP30 (1d) / hold_52w+trail20+TP30 (1w)
- IS / OOS 분리 평가 (2024-05-01 기준)

게이트 그리드 (OAT — 한 변수만 바꾸고 나머지는 default):
  trend_pullback:
    rally_lookback ∈ {30, 60, 90}     (default 60)
    depth_lookback ∈ {15, 30, 45}     (default 20  → 그리드에 20 포함하여 baseline)
    near_ma_pct    ∈ {0.02, 0.03, 0.05, 0.07}  (default 0.07)
  trend_chase:
    amount_lookback     ∈ {120, 250, 500}      (default 250)
    fresh_big_th        ∈ {0.04, 0.06, 0.08}   (default 0.05)
    max_prior_extension ∈ {0.30, 0.40, 0.50}   (default 0.30)
  quiet_bottom:
    dd_avg_max  ∈ {-0.40, -0.45, -0.50}        (default -0.45)
    path_r2_max ∈ {0.40, 0.50, 0.60}           (default 0.50)

산출:
  scripts/out/optimize/cycle_3/gate_grid_{asset}_{strategy}.csv
  scripts/out/optimize/cycle_3/gate_summary.md
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

from scripts.optimize_grid import (  # noqa: E402
    STRATEGIES,
    ExitRule,
    simulate,
    COST_RT,
    MIN_BARS,
    _build_universe,
    _files_for,
    load_symbol,
)

OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "cycle_3"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SPLIT_DATE = pd.Timestamp("2024-05-01")
IS_START = pd.Timestamp("2020-05-01")
OOS_END = pd.Timestamp("2026-05-01")
IS_YEARS = (SPLIT_DATE - IS_START).days / 365.25
OOS_YEARS = (OOS_END - SPLIT_DATE).days / 365.25

# Cycle 1 OOS best threshold per combo
TARGETS = [
    # (asset, strategy, interval, score_th, exit_rule)
    ("kr", "trend_pullback", "1d", 60,
     ExitRule("hold_252d_trail20_TP30", max_hold=252, trailing_pct=0.20, take_profit_pct=0.30)),
    ("us", "trend_pullback", "1d", 70,
     ExitRule("hold_252d_trail20_TP30", max_hold=252, trailing_pct=0.20, take_profit_pct=0.30)),
    ("kr", "trend_chase", "1d", 60,
     ExitRule("hold_252d_trail20_TP30", max_hold=252, trailing_pct=0.20, take_profit_pct=0.30)),
    ("us", "trend_chase", "1d", 60,
     ExitRule("hold_252d_trail20_TP30", max_hold=252, trailing_pct=0.20, take_profit_pct=0.30)),
    ("kr", "quiet_bottom", "1w", "binary",
     ExitRule("hold_52w_trail20_TP30", max_hold=52, trailing_pct=0.20, take_profit_pct=0.30)),
    ("us", "quiet_bottom", "1w", "binary",
     ExitRule("hold_52w_trail20_TP30", max_hold=52, trailing_pct=0.20, take_profit_pct=0.30)),
]

# Gate sweeps per strategy (one-at-a-time): dict param_name -> list of values
GATE_SWEEPS = {
    "trend_pullback": {
        "rally_lookback": [30, 60, 90],
        "depth_lookback": [15, 20, 30, 45],
        "near_ma_pct": [0.02, 0.03, 0.05, 0.07],
    },
    "trend_chase": {
        "amount_lookback": [120, 250, 500],
        "fresh_big_th": [0.04, 0.05, 0.06, 0.08],
        "max_prior_extension": [0.30, 0.40, 0.50],
    },
    "quiet_bottom": {
        "dd_avg_max": [-0.40, -0.45, -0.50],
        "path_r2_max": [0.40, 0.50, 0.60],
    },
}


def _summarize(rets: np.ndarray, period_years: float) -> dict:
    if rets.size == 0:
        return {"n": 0, "win%": 0.0, "mean%": 0.0, "MDD%": 0.0,
                "Sharpe_ann": 0.0, "PF": 0.0}
    win = float((rets > 0).mean() * 100)
    mean = float(rets.mean() * 100)
    eq = np.cumprod(1.0 + rets)
    peak = np.maximum.accumulate(eq)
    mdd = float((eq / peak - 1.0).min() * 100)
    if rets.std() > 0:
        sharpe_pt = rets.mean() / rets.std()
        annual_factor = np.sqrt(max(1, len(rets)) / period_years)
        sharpe = float(sharpe_pt * annual_factor)
    else:
        sharpe = 0.0
    gains = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = float(gains / losses) if losses > 0 else 99.99
    return {"n": int(rets.size),
            "win%": round(win, 1),
            "mean%": round(mean, 2),
            "MDD%": round(mdd, 1),
            "Sharpe_ann": round(sharpe, 2),
            "PF": round(pf, 2)}


def _process_combo(asset: str, strategy: str, interval: str,
                    score_th, rule: ExitRule, sweeps: Dict[str, list]) -> List[dict]:
    strat = STRATEGIES[strategy]
    cost = COST_RT[asset]
    min_bars = MIN_BARS[interval]
    universe = _build_universe(asset)
    files = _files_for(asset, interval)
    is_quiet = (strategy == "quiet_bottom")

    print(f"\n=== {asset.upper()} / {strategy} / {interval} "
          f"(universe={len(universe)}, files={len(files)}, "
          f"th={score_th}, rule={rule.name}) ===", flush=True)

    # Load data once
    t0 = time.time()
    cache: Dict[str, Tuple[np.ndarray, pd.DataFrame, np.ndarray, np.ndarray]] = {}
    n_done = 0
    n_skip = 0
    for p in files:
        sym = p.stem
        if sym not in universe:
            continue
        try:
            df = load_symbol(asset, p, interval)
        except Exception:
            n_skip += 1
            continue
        if df is None or df.empty or len(df) < min_bars:
            n_skip += 1
            continue
        df = df.sort_index()
        df_r = df.reset_index(drop=True)
        close = df["close"].astype("float64").to_numpy()
        dt_idx = pd.DatetimeIndex(df.index)
        in_is = np.asarray((dt_idx >= IS_START) & (dt_idx < SPLIT_DATE))
        in_oos = np.asarray((dt_idx >= SPLIT_DATE) & (dt_idx <= OOS_END))
        cache[sym] = (close, df_r, in_is, in_oos)
        n_done += 1
        if n_done % 50 == 0:
            print(f"  loaded {n_done} (skipped {n_skip})", flush=True)
    print(f"  total loaded: {n_done}, skipped {n_skip}, "
          f"elapsed {time.time()-t0:.1f}s", flush=True)
    if n_done == 0:
        return []

    rows = []
    # 0) Baseline (default params)
    print(f"  -- baseline (defaults) --", flush=True)
    base_row = _eval_with_params(strategy, cache, score_th, rule, cost, {},
                                  is_quiet, label_name="baseline",
                                  label_value="default")
    base_row.update({
        "asset": asset, "strategy": strategy, "interval": interval,
        "score_th": score_th, "rule": rule.name,
        "gate_param": "baseline", "gate_value": "default",
    })
    rows.append(base_row)
    _print_row(base_row)

    # 1) OAT sweeps
    for param_name, values in sweeps.items():
        print(f"  -- sweep {param_name} = {values} --", flush=True)
        for v in values:
            params = {param_name: v}
            r = _eval_with_params(strategy, cache, score_th, rule, cost, params,
                                  is_quiet, label_name=param_name,
                                  label_value=v)
            r.update({
                "asset": asset, "strategy": strategy, "interval": interval,
                "score_th": score_th, "rule": rule.name,
                "gate_param": param_name, "gate_value": v,
            })
            rows.append(r)
            _print_row(r)
    return rows


def _eval_with_params(strategy: str, cache, score_th, rule, cost: float,
                       params: dict, is_quiet: bool,
                       label_name: str, label_value) -> dict:
    strat = STRATEGIES[strategy]
    is_rets: List[float] = []
    oos_rets: List[float] = []
    th = None if is_quiet else float(score_th)
    for sym, (close, df_r, in_is, in_oos) in cache.items():
        try:
            if is_quiet:
                sig = strat.signal(df_r, params)
                val = sig.to_numpy().astype("int8")
                sig01 = val
            else:
                sc = strat.score(df_r, params)
                val = sc.to_numpy().astype("float32")
                sig01 = (val >= th).astype("int8")
        except Exception:
            continue
        if len(sig01) < 2:
            continue
        diff = np.diff(sig01.astype("int16"), prepend=0)
        enter_is = np.where((diff == 1) & in_is)[0]
        enter_oos = np.where((diff == 1) & in_oos)[0]
        for pos in enter_is:
            if pos >= len(close) - 1:
                continue
            exit_pos, gross = simulate(close, int(pos), rule)
            if exit_pos == pos:
                continue
            is_rets.append(gross - cost)
        for pos in enter_oos:
            if pos >= len(close) - 1:
                continue
            exit_pos, gross = simulate(close, int(pos), rule)
            if exit_pos == pos:
                continue
            oos_rets.append(gross - cost)
    is_arr = np.asarray(is_rets, dtype="float64")
    oos_arr = np.asarray(oos_rets, dtype="float64")
    is_s = _summarize(is_arr, IS_YEARS)
    oos_s = _summarize(oos_arr, OOS_YEARS)
    return {
        "IS_n": is_s["n"], "IS_win%": is_s["win%"], "IS_mean%": is_s["mean%"],
        "IS_MDD%": is_s["MDD%"], "IS_Sharpe": is_s["Sharpe_ann"], "IS_PF": is_s["PF"],
        "OOS_n": oos_s["n"], "OOS_win%": oos_s["win%"], "OOS_mean%": oos_s["mean%"],
        "OOS_MDD%": oos_s["MDD%"], "OOS_Sharpe": oos_s["Sharpe_ann"], "OOS_PF": oos_s["PF"],
    }


def _print_row(r: dict):
    print(f"    {r.get('gate_param','?'):>20s}={str(r.get('gate_value','?')):>8s} | "
          f"IS n={r['IS_n']:>5} S={r['IS_Sharpe']:>+5.2f} w={r['IS_win%']:>4.1f}% m={r['IS_mean%']:>+5.2f}% | "
          f"OOS n={r['OOS_n']:>5} S={r['OOS_Sharpe']:>+5.2f} w={r['OOS_win%']:>4.1f}% m={r['OOS_mean%']:>+5.2f}%",
          flush=True)


def main():
    all_rows: List[dict] = []
    # group by (asset, strategy) so one CSV per combo
    by_combo: Dict[Tuple[str, str], List[dict]] = {}
    for asset, strategy, interval, score_th, rule in TARGETS:
        sweeps = GATE_SWEEPS[strategy]
        try:
            rows = _process_combo(asset, strategy, interval, score_th, rule, sweeps)
        except Exception as e:
            print(f"FAIL {asset}/{strategy}/{interval}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            import traceback
            traceback.print_exc()
            continue
        all_rows.extend(rows)
        key = (asset, strategy)
        by_combo.setdefault(key, []).extend(rows)
        # write per-combo CSV incrementally
        df_combo = pd.DataFrame(by_combo[key])
        out_csv = OUT_DIR / f"gate_grid_{asset}_{strategy}.csv"
        df_combo.to_csv(out_csv, index=False, encoding="utf-8-sig")
        print(f"  saved: {out_csv}", flush=True)
    if not all_rows:
        print("no rows produced", file=sys.stderr)
        return 1
    df_all = pd.DataFrame(all_rows)
    df_all.to_csv(OUT_DIR / "gate_grid_all.csv", index=False, encoding="utf-8-sig")
    print(f"\nsaved: {OUT_DIR/'gate_grid_all.csv'} ({len(df_all)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
