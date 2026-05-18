"""Task 4 — Ensemble composite score (trend_chase + trend_pullback).

각 종목별로 두 전략의 score 시계열을 동시에 계산해서 composite score 를 만들고
threshold 적용 후 entry → Sharpe 측정.

compose modes:
  mean    : (chase + pullback) / 2
  max     : max(chase, pullback)
  weighted: 0.3 * chase + 0.7 * pullback (pullback 우위 가중)
  or      : chase>=th OR pullback>=th (둘 중 하나)

기준 (단일):
  chase th=60, pullback KR th=60 / US th=70

KR/US 1d, exit=hold_252d_trail20_TP30.
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
from backtest.strategies import trend_chase, trend_pullback  # noqa: E402

EXIT = ExitRule("hold_252d_trail20_TP30", max_hold=252,
                trailing_pct=0.20, take_profit_pct=0.30)


def _entries(close: np.ndarray, sig: np.ndarray, exit_rule: ExitRule, cost: float):
    if sig.sum() == 0:
        return []
    prev = np.concatenate([[0], sig[:-1]])
    pos_idx = np.where((sig == 1) & (prev == 0))[0]
    trades = []
    last_exit = -1
    for pos in pos_idx:
        if pos <= last_exit:
            continue
        exit_pos, gross = simulate(close, int(pos), exit_rule)
        trades.append({"held_bars": exit_pos - pos, "net_ret": gross - cost})
        last_exit = exit_pos
    return trades


def main():
    interval = "1d"
    bars_per_year = BARS_PER_YEAR[interval]

    rows = []
    for asset in ("kr", "us"):
        print(f"\n=== asset={asset} ===", flush=True)
        cost = COST_RT[asset]
        uni = _cached_universe(asset, 300)
        min_bars = MIN_BARS[interval]
        loader = _loader(asset)
        files = _files_for(asset, interval)

        # 각 종목별 close + chase_score + pullback_score 시계열 cache
        cache = []
        t0 = time.time()
        for p in files:
            if p.stem not in uni:
                continue
            try:
                df = loader(p, interval)
            except Exception:
                continue
            if df is None or df.empty or len(df) < min_bars:
                continue
            df_r = df.reset_index(drop=True)
            try:
                sc_c = trend_chase.score(df_r, {}).fillna(0).to_numpy()
                sc_p = trend_pullback.score(df_r, {}).fillna(0).to_numpy()
            except Exception:
                continue
            close = df["close"].astype("float64").to_numpy()
            dt = df.index
            mask = np.asarray(dt >= SINCE).astype("int8") if isinstance(dt, pd.DatetimeIndex) else \
                np.array([1 if pd.Timestamp(d) >= SINCE else 0 for d in dt], dtype="int8")
            cache.append((p.stem, close, sc_c, sc_p, mask))
        print(f"  loaded {len(cache)} symbols ({time.time()-t0:.1f}s)", flush=True)

        # 단일 베이스라인 + composites
        configs = [
            ("chase_only_th60",    "chase", 60),
            ("pullback_only_th60", "pullback", 60),
            ("pullback_only_th70", "pullback", 70),
            # composites: mean / max / weighted / or
            ("mean_th60",          "mean", 60),
            ("mean_th70",          "mean", 70),
            ("max_th60",           "max", 60),
            ("max_th70",           "max", 70),
            ("weighted_30_70_th60", "weighted_30_70", 60),
            ("weighted_30_70_th70", "weighted_30_70", 70),
            ("or_chase60_pull60",  "or", 60),
            ("or_chase60_pull70",  "or", 70),
        ]

        for name, mode, th in configs:
            trades = []
            for symbol, close, sc_c, sc_p, mask in cache:
                if mode == "chase":
                    sig = ((sc_c >= th) * mask).astype("int8")
                elif mode == "pullback":
                    sig = ((sc_p >= th) * mask).astype("int8")
                elif mode == "mean":
                    comp = (sc_c + sc_p) / 2.0
                    sig = ((comp >= th) * mask).astype("int8")
                elif mode == "max":
                    comp = np.maximum(sc_c, sc_p)
                    sig = ((comp >= th) * mask).astype("int8")
                elif mode == "weighted_30_70":
                    comp = 0.3 * sc_c + 0.7 * sc_p
                    sig = ((comp >= th) * mask).astype("int8")
                elif mode == "or":
                    # name 에서 둘 threshold 분리
                    if "60_pull60" in name:
                        sig = (((sc_c >= 60) | (sc_p >= 60)) * mask).astype("int8")
                    else:
                        sig = (((sc_c >= 60) | (sc_p >= 70)) * mask).astype("int8")
                else:
                    raise ValueError(mode)
                trades.extend(_entries(close, sig, EXIT, cost))
            s = _summarize_trades(trades, bars_per_year)
            print(f"  {name:<22} n={s['n']:>5} win%={s['win_pct']:>5.1f} "
                  f"mean%={s['mean_pct']:>+6.2f} sharpe={s['sharpe']:>+5.2f} "
                  f"PF={s['profit_factor']:>5.2f}", flush=True)
            rows.append({"asset": asset, "config": name, "mode": mode, "threshold": th, **s})

    df = pd.DataFrame(rows)
    out_csv = OUT_DIR / "ensemble_eval.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nsaved: {out_csv}", flush=True)


if __name__ == "__main__":
    main()
