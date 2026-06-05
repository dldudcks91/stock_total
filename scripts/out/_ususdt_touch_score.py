"""USUSDT 주봉 MA10 터치 시점에서의 pullback 점수 + 전체 rank 조회."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
from data.resample import load
from scripts.crypto._common.mtf_recs import compute_score_matrix


def main():
    df_1d = load("USUSDT", "1d").copy()
    df_1d["dt"] = pd.to_datetime(df_1d["timestamp"], unit="ms")
    df_1d = df_1d.set_index("dt")

    agg_w = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "amount" in df_1d.columns:
        agg_w["amount"] = "sum"
    df_1w = df_1d.resample("W-MON", label="left", closed="left").agg(agg_w).dropna(subset=["close"])
    df_1w["ma10"] = df_1w["close"].rolling(10).mean()
    df_1w["low_to_ma10_pct"] = (df_1w["low"] - df_1w["ma10"]) / df_1w["ma10"] * 100

    # 최근 7주 — 각 주의 low 시점 찾기
    recent = df_1w.tail(7).copy()
    low_days = []
    for week_start, row in recent.iterrows():
        week_end = week_start + pd.Timedelta(days=6, hours=23)
        week_1d = df_1d.loc[week_start:week_end]
        if len(week_1d) == 0:
            continue
        low_day = week_1d["low"].idxmin()
        low_days.append((week_start, low_day, row.low_to_ma10_pct))

    print("=== 주별 low 시점 cutoff 채점 ===")
    print(f"{'week_start':<12} {'low_day':<12} {'low/ma10':>8}  {'score':>5} {'rank':>10} {'top15컷':>7}")
    for week_start, low_day, pct in low_days:
        # 그 날 23시 (UTC) cutoff
        cutoff = low_day.replace(hour=23, minute=0)
        mats = compute_score_matrix(cutoff, hours=1, workers=6)
        pb = mats["pullback"].iloc[-1].sort_values(ascending=False)
        if "USUSDT" not in pb.index:
            print(f"{str(week_start.date()):<12} {str(low_day.date()):<12} {pct:>+7.2f}%  USUSDT not in matrix")
            continue
        rank = pb.index.get_loc("USUSDT") + 1
        score = pb["USUSDT"]
        top15_cutoff = pb.iloc[14] if len(pb) >= 15 else pb.iloc[-1]
        print(f"{str(week_start.date()):<12} {str(low_day.date()):<12} {pct:>+7.2f}%  {score:>5.0f}  {rank:>4}/{len(pb):<4}   {top15_cutoff:>5.0f}")


if __name__ == "__main__":
    main()
