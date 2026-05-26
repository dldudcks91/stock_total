"""trend_chase 단독 백테스트 — ch_score v2/v3/v4/v5/v5_1 채점.

사용:
    .venv/Scripts/python.exe -m scripts.kr.trend_chase.backtest
    .venv/Scripts/python.exe -m scripts.kr.trend_chase.backtest --start 2025-11-26 --end 2026-05-26

양쪽 동시 비교는 scripts/kr/backtest_all.py 사용.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.backtest_runner import (
    run_backtest,
    analyze_threshold_multi,
    analyze_baseline_multi,
    analyze_quantile_multi,
)
from scripts.kr.trend_chase.scoring import (
    score_chase, score_chase_v3, score_chase_v4, score_chase_v5, score_chase_v5_1,
)

CACHE_DIR = ROOT / "data" / "cache" / "kr"
OUT_DIR = ROOT / "scripts" / "out"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-11-26")
    ap.add_argument("--end", default="2026-05-26")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    HOLDS = (5, 10, 20, 30, 60)

    print(f"=== KR trend_chase 백테스트 (numeric, multi-hold, v2~v5.1) ===\n")
    bt = run_backtest(
        cache_dir=CACHE_DIR,
        start=start, end=end,
        scoring_fns={
            "ch_score": score_chase,
            "ch_score_v3": score_chase_v3,
            "ch_score_v4": score_chase_v4,
            "ch_score_v5": score_chase_v5,
            "ch_score_v51": score_chase_v5_1,
        },
        hold_periods=HOLDS,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else (
        OUT_DIR / f"kr_chase_bt_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.parquet"
    )
    bt.to_parquet(out_path, index=False)
    print(f"\n저장: {out_path}\n")

    analyze_baseline_multi(bt, HOLDS)

    print("\n" + "=" * 60)
    print(" CHASE v2 vs v3 vs v5.1 비교 (threshold 별)")
    print("=" * 60)
    for th in (10, 20, 30, 40, 50):
        analyze_threshold_multi(bt, "ch_score", th, "CH v2", HOLDS)
        analyze_threshold_multi(bt, "ch_score_v3", th, "CH v3", HOLDS)
        analyze_threshold_multi(bt, "ch_score_v51", th, "CH v5.1", HOLDS)

    print("\n\n" + "=" * 60)
    print(" CHASE v5.1 점수 분위별 (10분위) — 차별력 검증")
    print("=" * 60)
    analyze_quantile_multi(bt, "ch_score_v51", "CH v5.1", hold_periods=(30, 60))


if __name__ == "__main__":
    main()
