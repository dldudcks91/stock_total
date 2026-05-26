"""KR 통합 백테스트 — pullback / chase 동시 채점 + 비교 (단일 데이터 로드).

scripts/misc/kr_backtest_numeric.py 의 main() 인계자. 두 strategy 의 모든 점수
버전 (pb v2/v3, ch v2/v3/v4/v5/v5_1) 을 한 번에 계산 → threshold 별/분위별 비교.

사용:
    .venv/Scripts/python.exe -m scripts.kr.backtest_all
    .venv/Scripts/python.exe -m scripts.kr.backtest_all --start 2025-11-26 --end 2026-05-26
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.backtest_runner import (
    run_backtest,
    analyze_threshold_multi,
    analyze_baseline_multi,
    analyze_quantile_multi,
)
from scripts.kr.trend_pullback.scoring import score_pullback, score_pullback_v3
from scripts.kr.trend_chase.scoring import (
    score_chase, score_chase_v3, score_chase_v4, score_chase_v5, score_chase_v5_1,
)

CACHE_DIR = ROOT / "data" / "cache" / "kr"
OUT_DIR = ROOT / "scripts" / "out"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-11-26")
    ap.add_argument("--end", default="2026-05-26")
    args = ap.parse_args()

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    HOLDS = (5, 10, 20, 30, 60)

    print(f"=== KR 통합 백테스트 v2/v3/v4/v5/v5_1 (numeric, multi-hold) ===\n")
    bt = run_backtest(
        cache_dir=CACHE_DIR,
        start=start, end=end,
        scoring_fns={
            "pb_score": score_pullback,
            "pb_score_v3": score_pullback_v3,
            "ch_score": score_chase,
            "ch_score_v3": score_chase_v3,
            "ch_score_v4": score_chase_v4,
            "ch_score_v5": score_chase_v5,
            "ch_score_v51": score_chase_v5_1,
        },
        hold_periods=HOLDS,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"kr_backtest_all_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.parquet"
    bt.to_parquet(out_path, index=False)
    print(f"저장: {out_path}\n")

    analyze_baseline_multi(bt, HOLDS)

    print("\n" + "=" * 60)
    print(" PULLBACK v2 vs v3 비교 (threshold 별)")
    print("=" * 60)
    for th in (40, 50, 60, 70, 80):
        analyze_threshold_multi(bt, "pb_score", th, "PB v2", HOLDS)
        analyze_threshold_multi(bt, "pb_score_v3", th, "PB v3", HOLDS)

    print("\n" + "=" * 60)
    print(" CHASE v2 vs v3 비교 (threshold 별)")
    print("=" * 60)
    for th in (40, 50, 60, 70, 80):
        analyze_threshold_multi(bt, "ch_score", th, "CH v2", HOLDS)
        analyze_threshold_multi(bt, "ch_score_v3", th, "CH v3", HOLDS)

    print("\n\n" + "=" * 60)
    print(" v3 점수 분위별 (10분위) — 차별력 검증")
    print("=" * 60)
    analyze_quantile_multi(bt, "pb_score_v3", "PB v3", hold_periods=(30, 60))
    analyze_quantile_multi(bt, "ch_score_v3", "CH v3", hold_periods=(30, 60))


if __name__ == "__main__":
    main()
