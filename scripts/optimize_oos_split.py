"""Cycle 1 — IS / OOS split 검증.

기존 optimize_grid.py 의 6년 통합 평가를 IS (2020-05-17 ~ 2024-05-16, 4yr)
와 OOS (2024-05-17 ~ 2026-05-17, 2yr) 로 분리.

핵심:
  - 종목별 데이터/시그널은 1회만 로드 (시간 절약).
  - 각 trade 의 entry 시점이 IS 인지 OOS 인지에 따라 별도 bucket 누적.
  - exit_rule 은 검증된 것 1~2개만 (Cycle 2 가 exit 그리드 담당).

산출:
  scripts/out/optimize/cycle_1/oos_split.csv
  scripts/out/optimize/cycle_1/oos_summary.md
"""
from __future__ import annotations

import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.optimize_grid import (  # noqa: E402
    STRATEGIES,
    ExitRule,
    simulate,
    COST_RT,
    MIN_BARS,
    UNIVERSE_TOP,
    _build_universe,
    _files_for,
    load_symbol,
)

OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "cycle_1"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 분할 경계 (미션: OOS 시작 정확히 2024-05-01)
SPLIT_DATE = pd.Timestamp("2024-05-01")
IS_START = pd.Timestamp("2020-05-01")
OOS_END = pd.Timestamp("2026-05-01")

IS_YEARS = (SPLIT_DATE - IS_START).days / 365.25       # ~4
OOS_YEARS = (OOS_END - SPLIT_DATE).days / 365.25       # ~2


# 검증된 (자산, 인터벌) -> 단일 exit rule (Cycle 2 가 변형 그리드)
EXIT_RULE = {
    ("kr", "1d"): ExitRule("hold_252d_trail20_TP30",
                            max_hold=252, trailing_pct=0.20, take_profit_pct=0.30),
    ("us", "1d"): ExitRule("hold_252d_trail20_TP30",
                            max_hold=252, trailing_pct=0.20, take_profit_pct=0.30),
    ("kr", "1w"): ExitRule("hold_52w_trail20_TP30",
                            max_hold=52, trailing_pct=0.20, take_profit_pct=0.30),
    ("us", "1w"): ExitRule("hold_52w_trail20_TP30",
                            max_hold=52, trailing_pct=0.20, take_profit_pct=0.30),
    ("crypto", "1d"): ExitRule("hold_60d_trail20_TP30",
                                max_hold=60, trailing_pct=0.20, take_profit_pct=0.30),
    ("crypto", "1d_pullback"): ExitRule("hold_60d_trail15_cut3d",
                                         max_hold=60, trailing_pct=0.15,
                                         cut_short_at=3, cut_short_thr=-5),
}


# 검증 대상 그리드 — 미션에 따라 한정.
TARGETS = [
    # (asset, strategy, interval, [thresholds])
    ("kr", "trend_pullback", "1d", [60, 70, 80]),
    ("us", "trend_pullback", "1d", [60, 70, 80]),
    ("kr", "trend_chase", "1d", [60, 70, 80]),
    ("us", "trend_chase", "1d", [60, 70, 80]),
    ("kr", "quiet_bottom", "1w", ["binary"]),
    ("us", "quiet_bottom", "1w", ["binary"]),
    ("crypto", "trend_chase", "1d", [60, 70, 80]),
    ("crypto", "trend_pullback", "1d", [60, 70, 80]),
]


def _pick_exit_rule(asset: str, strategy: str, interval: str) -> ExitRule:
    if asset == "crypto" and strategy == "trend_pullback" and interval == "1d":
        return EXIT_RULE[("crypto", "1d_pullback")]
    return EXIT_RULE[(asset, interval)]


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
    pf = float(gains / losses) if losses > 0 else float("inf")
    if pf == float("inf"):
        pf = 99.99
    return {"n": int(rets.size),
            "win%": round(win, 1),
            "mean%": round(mean, 2),
            "MDD%": round(mdd, 1),
            "Sharpe_ann": round(sharpe, 2),
            "PF": round(pf, 2)}


def _process_combo(asset: str, strategy: str, interval: str,
                    thresholds: List) -> List[dict]:
    strat = STRATEGIES[strategy]
    cost = COST_RT[asset]
    min_bars = MIN_BARS[interval]
    universe = _build_universe(asset)
    files = _files_for(asset, interval)
    rule = _pick_exit_rule(asset, strategy, interval)
    is_quiet = (strategy == "quiet_bottom")

    print(f"\n=== {asset.upper()} / {strategy} / {interval} "
          f"(universe={len(universe)}, files={len(files)}, "
          f"rule={rule.name}, thresholds={thresholds}) ===", flush=True)

    t0 = time.time()
    cache: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
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
        try:
            if is_quiet:
                sig = strat.signal(df_r, {})
                val = sig.to_numpy().astype("int8")
            else:
                sc = strat.score(df_r, {})
                val = sc.to_numpy().astype("float32")
        except Exception:
            n_skip += 1
            continue
        close = df["close"].astype("float64").to_numpy()
        dt_idx = pd.DatetimeIndex(df.index)
        in_is = np.asarray((dt_idx >= IS_START) & (dt_idx < SPLIT_DATE))
        in_oos = np.asarray((dt_idx >= SPLIT_DATE) & (dt_idx <= OOS_END))
        cache[sym] = (close, val, in_is, in_oos)
        n_done += 1
        if n_done % 50 == 0:
            print(f"  loaded {n_done} (skipped {n_skip})", flush=True)

    print(f"  total loaded: {n_done} symbols, skipped {n_skip}, "
          f"elapsed {time.time()-t0:.1f}s", flush=True)
    if n_done == 0:
        return []

    rows = []
    for th in thresholds:
        t1 = time.time()
        is_rets: List[float] = []
        oos_rets: List[float] = []
        for sym, (close, val, in_is, in_oos) in cache.items():
            if is_quiet:
                sig01 = val
            else:
                sig01 = (val >= float(th)).astype("int8")
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
        row = {
            "asset": asset, "strategy": strategy, "interval": interval,
            "score_th": th, "rule": rule.name,
            "IS_n": is_s["n"], "IS_win%": is_s["win%"],
            "IS_mean%": is_s["mean%"], "IS_MDD%": is_s["MDD%"],
            "IS_Sharpe": is_s["Sharpe_ann"], "IS_PF": is_s["PF"],
            "OOS_n": oos_s["n"], "OOS_win%": oos_s["win%"],
            "OOS_mean%": oos_s["mean%"], "OOS_MDD%": oos_s["MDD%"],
            "OOS_Sharpe": oos_s["Sharpe_ann"], "OOS_PF": oos_s["PF"],
        }
        # Sharpe decay = (OOS - IS) / |IS|
        if is_s["Sharpe_ann"] != 0:
            row["Sharpe_decay"] = round(
                (oos_s["Sharpe_ann"] - is_s["Sharpe_ann"]) / abs(is_s["Sharpe_ann"]), 3)
        else:
            row["Sharpe_decay"] = None
        rows.append(row)
        print(f"  th={th!s:>6} IS n={is_s['n']:>5} S={is_s['Sharpe_ann']:>+5.2f} "
              f"win={is_s['win%']:>4.1f}% mean={is_s['mean%']:>+5.2f}% | "
              f"OOS n={oos_s['n']:>5} S={oos_s['Sharpe_ann']:>+5.2f} "
              f"win={oos_s['win%']:>4.1f}% mean={oos_s['mean%']:>+5.2f}% "
              f"({time.time()-t1:.1f}s)", flush=True)
    return rows


def main():
    all_rows: List[dict] = []
    for asset, strategy, interval, ths in TARGETS:
        try:
            rows = _process_combo(asset, strategy, interval, ths)
            all_rows.extend(rows)
        except Exception as e:
            print(f"FAIL {asset}/{strategy}/{interval}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            import traceback
            traceback.print_exc()
    if not all_rows:
        print("no rows produced", file=sys.stderr)
        return 1
    df = pd.DataFrame(all_rows)
    out_csv = OUT_DIR / "oos_split.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nsaved: {out_csv}  ({len(df)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
