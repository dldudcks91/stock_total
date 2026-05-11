"""Buy-and-Hold 베이스라인을 매트릭스 결과와 비교.

매트릭스 디렉터리의 _summary.csv를 읽어, 각 (전략, 그룹, 심볼)에 대해 같은 기간/인터벌의
B&H total_return과 sharpe를 계산하고 알파(전략 - B&H)를 산출.
출력: <matrix_dir>/_baseline_compare.csv 와 _baseline_aggregate.csv.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.engine.runner import BARS_PER_YEAR, _parse_ts, _slice_df
from data.resample import load as load_ohlcv

CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache"


def buy_hold(symbol: str, interval: str, start: str, end: str) -> dict:
    df = load_ohlcv(symbol, interval)
    df = _slice_df(df, _parse_ts(start), _parse_ts(end))
    if len(df) < 2:
        return {"bh_total_return": np.nan, "bh_sharpe": np.nan, "bh_mdd": np.nan}
    close = df["close"].astype("float64").to_numpy()
    ret = pd.Series(close).pct_change().fillna(0.0).to_numpy()
    total = close[-1] / close[0] - 1.0
    bpy = BARS_PER_YEAR[interval]
    if ret.size > 1 and ret.std(ddof=0) > 0:
        sharpe = float(ret.mean() / ret.std(ddof=0) * math.sqrt(bpy))
    else:
        sharpe = 0.0
    eq = np.cumprod(1.0 + ret)
    peak = np.maximum.accumulate(eq)
    mdd = float((eq / peak - 1.0).min())
    return {"bh_total_return": float(total), "bh_sharpe": float(sharpe), "bh_mdd": float(mdd)}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--matrix-dir", required=True)
    p.add_argument("--start", default="2023-01-01")
    p.add_argument("--end", default="2025-12-31")
    args = p.parse_args(argv)

    md = Path(args.matrix_dir)
    summ = pd.read_csv(md / "_summary.csv")
    summ = summ[summ["status"] == "ok"].copy()

    out_rows = []
    cache: dict[tuple[str, str], dict] = {}
    for _, r in summ.iterrows():
        key = (r["symbol"], r["interval"])
        if key not in cache:
            cache[key] = buy_hold(r["symbol"], r["interval"], args.start, args.end)
        bh = cache[key]
        out_rows.append({**r.to_dict(), **bh,
                         "alpha_total_return": r["total_return"] - bh["bh_total_return"],
                         "alpha_sharpe": r["sharpe"] - bh["bh_sharpe"]})

    cmp_df = pd.DataFrame(out_rows)
    cmp_df.to_csv(md / "_baseline_compare.csv", index=False)

    agg = cmp_df.groupby(["strategy", "interval", "group"]).agg(
        n=("symbol", "count"),
        strat_mean_ret=("total_return", "mean"),
        bh_mean_ret=("bh_total_return", "mean"),
        alpha_mean=("alpha_total_return", "mean"),
        alpha_median=("alpha_total_return", "median"),
        strat_mean_sharpe=("sharpe", "mean"),
        bh_mean_sharpe=("bh_sharpe", "mean"),
        alpha_sharpe_mean=("alpha_sharpe", "mean"),
        win_vs_bh=("alpha_total_return", lambda s: float((s > 0).mean())),
        strat_mean_mdd=("mdd", "mean"),
        bh_mean_mdd=("bh_mdd", "mean"),
    ).round(4).reset_index()
    agg.to_csv(md / "_baseline_aggregate.csv", index=False)
    print(agg.to_string(index=False))


if __name__ == "__main__":
    main()
