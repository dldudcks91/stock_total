"""K=0.2 의 임계가 실제 close 대비 몇 % 인지 KR 전 종목 × 5 TF 분포로 측정.

  임계 = K × range_7 (절대값)
  pct = 임계 / close × 100
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.mtf_loader import load_normalized_daily, resample_multi_tf
from scripts._common.signals import K_DIST_THRESHOLD, N_ATR_WINDOW
from scripts._common.recommend_runner import EVAL_TFS, MIN_DAILY_BARS, discover_universe


def main():
    asset = "kr"
    symbols = discover_universe(asset)

    rows = []
    for sym in symbols:
        try:
            df_d = load_normalized_daily(asset, sym)
        except Exception:
            continue
        if len(df_d) < MIN_DAILY_BARS:
            continue
        mtf = resample_multi_tf(df_d)
        for tf in EVAL_TFS:
            df_tf = mtf[tf]
            if len(df_tf) < 1:
                continue
            close = float(df_tf["close"].iloc[-1])
            rng = float((df_tf["high"] - df_tf["low"]).tail(N_ATR_WINDOW).mean())
            if close <= 0 or not np.isfinite(rng):
                continue
            th_abs = K_DIST_THRESHOLD * rng
            pct = th_abs / close * 100
            rows.append({"tf": tf, "pct": pct})

    df = pd.DataFrame(rows)
    print(f"K = {K_DIST_THRESHOLD}, range window = {N_ATR_WINDOW}, asset = {asset}")
    print(f"표본 {len(df)} (종목 × TF, KR 전체)")
    print()
    summary = df.groupby("tf")["pct"].agg(["count", "mean", "median",
                                           lambda s: s.quantile(0.10),
                                           lambda s: s.quantile(0.25),
                                           lambda s: s.quantile(0.75),
                                           lambda s: s.quantile(0.90)])
    summary.columns = ["n", "mean", "median", "p10", "p25", "p75", "p90"]
    summary = summary.reindex(["1D", "1W", "1M", "1Q", "1Y"])
    print("임계 / close × 100 (%) ---")
    print(summary.to_string(float_format=lambda v: f"{v:.2f}"))


if __name__ == "__main__":
    main()
