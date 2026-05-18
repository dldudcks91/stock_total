"""Round 2 — strategy 진입 파라미터 자체를 튜닝하는 그리드 러너.

Round 1 (`stage_runner.py`) 은 score_threshold × exit_rule 만 그리드 — score 를 만드는
파라미터(rally_lookback, rally_min_gain, ret_th 등) 는 default 고정.

이 모듈은:
  - strategy 별 파라미터 그리드를 외부에서 받아
  - 각 파라미터 조합마다 collect_entries (signal 계산) 를 다시 호출
  - (threshold, exit_rule) 은 고정 — 최고 Sharpe 조합으로
  - per-trade Sharpe / win% / mean% / PF / MDD / n 출력

CLI:
  python -m scripts.optimize.strategy_param_grid --task trend_pullback --asset kr --interval 1d
  python -m scripts.optimize.strategy_param_grid --task trend_chase    --asset us --interval 1d
"""
from __future__ import annotations

import argparse
import itertools
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.optimize.threshold_grid import (  # noqa: E402
    BARS_PER_YEAR, COST_RT, MIN_BARS, SINCE, STRATEGIES,
    ExitRule, _files_for, _loader, _universe, _summarize_trades, simulate,
)

OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "round2" / "strategy"
OUT_DIR.mkdir(parents=True, exist_ok=True)

_UNI_CACHE_DIR = OUT_DIR / "_uni"
_UNI_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cached_universe(asset: str, top_n: int = 300) -> set:
    """FDR 호출 실패 (network) 대비 — 한 번 받은 universe 를 디스크 캐시."""
    f = _UNI_CACHE_DIR / f"{asset}_top{top_n}.txt"
    if f.exists():
        syms = {l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()}
        if syms:
            return syms
    # 신규: FDR 시도, 실패 시 cache 디렉터리 file size top-N 으로 fallback
    try:
        uni = _universe(asset)
    except Exception as e:
        print(f"  [warn] FDR universe fail ({e}); fallback to cache file-size proxy", flush=True)
        files = _files_for(asset, "1d")
        # file size 가 큰 종목 = 데이터 길이 긴 종목 = 대형주 proxy
        sized = sorted(files, key=lambda p: p.stat().st_size, reverse=True)
        uni = {p.stem for p in sized[:top_n]}
    f.write_text("\n".join(sorted(uni)), encoding="utf-8")
    return uni

# Round 1 우승 score_threshold + exit_rule (고정)
FIXED_TH = {
    ("kr", "trend_pullback", "1d"): 60.0,   # SUMMARY: KR pullback 1d best=60
    ("us", "trend_pullback", "1d"): 70.0,   # SUMMARY: US pullback 1d best=70
    ("kr", "trend_chase", "1d"): 60.0,
    ("us", "trend_chase", "1d"): 60.0,
}

# KR/US 1d : hold_252d_trail20_TP30 (Round 1 검증 우승룰)
FIXED_EXIT = ExitRule(
    "hold_252d_trail20_TP30",
    max_hold=252, trailing_pct=0.20, take_profit_pct=0.30,
)


def _collect_entries_with_params(
    asset: str, interval: str, strategy: str,
    universe: set, params: dict, verbose: bool = False,
) -> list[dict]:
    """`threshold_grid.collect_entries` 와 동일하지만 외부 params 를 받음."""
    strat = STRATEGIES[strategy]
    loader = _loader(asset)
    files = _files_for(asset, interval)
    min_bars = MIN_BARS[interval]
    is_binary = (strategy == "quiet_bottom")

    out: list[dict] = []
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
            if is_binary:
                sig = strat.signal(df_reset, params)
                score_arr = sig.astype("float64") * 100.0
            else:
                score_arr = strat.score(df_reset, params)
                sig = (score_arr.fillna(0) > 0).astype("int8")
        except Exception:
            continue
        close = df["close"].astype("float64").to_numpy()
        dt_index = df.index
        if isinstance(dt_index, pd.DatetimeIndex):
            mask_recent = np.asarray(dt_index >= SINCE)
        else:
            mask_recent = np.array([pd.Timestamp(d) >= SINCE for d in dt_index])
        out.append({
            "symbol": symbol,
            "close": close,
            "scores": pd.Series(score_arr).reset_index(drop=True).astype("float64").to_numpy(),
            "dt": [str(d.date()) if hasattr(d, "date") else str(d) for d in dt_index],
            "mask_recent": mask_recent,
        })
        n_proc += 1
        if verbose and n_proc % 100 == 0:
            print(f"      collected {n_proc}", flush=True)
    return out


def _eval_param_set(
    asset: str, interval: str, strategy: str,
    universe: set, params: dict,
    threshold: float, exit_rule: ExitRule,
) -> dict:
    """한 파라미터 세트에 대한 (n, win%, mean%, Sharpe, ...) 측정."""
    cost = COST_RT[asset]
    bars_per_year = BARS_PER_YEAR[interval]
    entries_data = _collect_entries_with_params(asset, interval, strategy, universe, params)

    trades = []
    for rec in entries_data:
        scores = rec["scores"]
        mask = rec["mask_recent"]
        close = rec["close"]
        dts = rec["dt"]
        sig_th = (scores >= threshold).astype("int8")
        sig_th = sig_th * mask.astype("int8")
        if sig_th.sum() == 0:
            continue
        prev = np.concatenate([[0], sig_th[:-1]])
        entries_idx = np.where((sig_th == 1) & (prev == 0))[0]
        if len(entries_idx) == 0:
            continue
        last_exit = -1
        for pos in entries_idx:
            if pos <= last_exit:
                continue
            exit_pos, gross = simulate(close, int(pos), exit_rule)
            net = gross - cost
            trades.append({
                "symbol": rec["symbol"],
                "entry_dt": dts[pos],
                "held_bars": exit_pos - pos,
                "gross_ret": gross,
                "net_ret": net,
            })
            last_exit = exit_pos
    summary = _summarize_trades(trades, bars_per_year)
    return summary


# ---------------------------------------------------------------------------
# Task 1 — trend_pullback grids
# ---------------------------------------------------------------------------
def trend_pullback_grid() -> list[dict]:
    """rally_lookback × rally_min_gain × depth_lookback."""
    grid = []
    for rl in (30, 45, 60, 90, 120):
        for rmg in (0.10, 0.20, 0.30, 0.50):
            for dl in (5, 10, 15, 20):
                grid.append({
                    "rally_lookback": rl,
                    "rally_min_gain": rmg,
                    "depth_lookback": dl,
                })
    return grid  # 5 * 4 * 4 = 80 (요구 60+, OK)


# ---------------------------------------------------------------------------
# Task 2 — trend_chase grids
# ---------------------------------------------------------------------------
RET_TH_PATTERNS = {
    "default":   [0.03, 0.05, 0.07, 0.10],   # 베이스라인
    "tight":     [0.02, 0.04, 0.06, 0.08],   # 더 잘 진입 (낮은 임계)
    "loose":     [0.05, 0.07, 0.10, 0.15],   # 더 엄격 (높은 임계)
    "stretched": [0.03, 0.06, 0.10, 0.15],   # 펼친 분포
    "big":       [0.05, 0.08, 0.12, 0.18],   # 큰 양봉만
}


def trend_chase_grid() -> list[dict]:
    """ret_th pattern × base_lookback × fresh_big_th × max_prior_extension."""
    grid = []
    for ret_th_key in RET_TH_PATTERNS:
        for bl in (30, 60, 90, 120):
            for fbt in (0.03, 0.05, 0.08, 0.12):
                for mpe in (0.20, 0.30, 0.50):
                    p = {
                        "ret_th": RET_TH_PATTERNS[ret_th_key],
                        "base_lookback": bl,
                        "fresh_big_th": fbt,
                        "max_prior_extension": mpe,
                        # ret_pts 는 ret_th 와 길이만 맞으면 default 와 동일
                    }
                    grid.append({"_ret_th_key": ret_th_key, **p})
    return grid  # 5 * 4 * 4 * 3 = 240


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------
def run_task(task: str, asset: str, interval: str = "1d") -> pd.DataFrame:
    """task ∈ {trend_pullback, trend_chase}."""
    key = (asset, task, interval)
    if key not in FIXED_TH:
        raise ValueError(f"no fixed threshold for {key}")
    th = FIXED_TH[key]
    exit_rule = FIXED_EXIT

    print(f"\n=== TASK {task} / {asset} / {interval} (threshold={th}, exit={exit_rule.name}) ===", flush=True)

    print(f"  building universe ({asset}, top 300)...", flush=True)
    t0 = time.time()
    uni = _cached_universe(asset, top_n=300)
    print(f"  universe={len(uni)} symbols ({time.time()-t0:.1f}s)", flush=True)

    if task == "trend_pullback":
        grid = trend_pullback_grid()
    elif task == "trend_chase":
        grid = trend_chase_grid()
    else:
        raise ValueError(task)

    print(f"  evaluating {len(grid)} param combinations...", flush=True)

    # Baseline (default params)
    base_t = time.time()
    base_summary = _eval_param_set(asset, interval, task, uni, {}, th, exit_rule)
    print(f"  [baseline] {base_summary} ({time.time()-base_t:.1f}s)", flush=True)

    rows = []
    rows.append({
        "rank": -1, "label": "BASELINE",
        **{k: ("default" if k == "_ret_th_key" else None) for k in grid[0].keys()},
        **base_summary,
    })

    for i, params in enumerate(grid):
        t1 = time.time()
        eval_params = {k: v for k, v in params.items() if not k.startswith("_")}
        try:
            summary = _eval_param_set(asset, interval, task, uni, eval_params, th, exit_rule)
        except Exception as e:
            summary = {"n": 0, "win_pct": 0, "mean_pct": 0, "median_pct": 0,
                       "total_pct": 0, "mdd_pct": 0, "sharpe": 0, "profit_factor": 0,
                       "avg_held_bars": 0}
            print(f"  [{i+1}/{len(grid)}] ERROR {type(e).__name__}: {e}", flush=True)
        elapsed = time.time() - t1
        row = {"rank": i, "label": f"p{i:03d}", **params, **summary}
        rows.append(row)
        if (i + 1) % 10 == 0 or i < 5:
            print(f"  [{i+1}/{len(grid)}] {params} -> n={summary['n']} "
                  f"win%={summary['win_pct']:.1f} mean%={summary['mean_pct']:+.2f} "
                  f"sharpe={summary['sharpe']:+.2f} ({elapsed:.1f}s)", flush=True)

    df = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    out_csv = OUT_DIR / f"{task}_{asset}_{interval}_grid.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n  saved: {out_csv}", flush=True)

    # Top 10 출력
    print("\n  ===== TOP 10 (by Sharpe) =====", flush=True)
    cols_show = [c for c in ("label", "rank", "_ret_th_key", "rally_lookback",
                              "rally_min_gain", "depth_lookback",
                              "base_lookback", "fresh_big_th", "max_prior_extension",
                              "n", "win_pct", "mean_pct", "sharpe", "profit_factor", "mdd_pct")
                 if c in df.columns]
    print(df[cols_show].head(10).to_string(index=False), flush=True)

    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=["trend_pullback", "trend_chase"], required=True)
    ap.add_argument("--asset", choices=["kr", "us"], required=True)
    ap.add_argument("--interval", default="1d")
    args = ap.parse_args()
    run_task(args.task, args.asset, args.interval)


if __name__ == "__main__":
    main()
