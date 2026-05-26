"""trend_pullback 단독 백테스트 — pb_score_v3 만 채점.

사용:
    .venv/Scripts/python.exe -m scripts.kr.trend_pullback.backtest
    .venv/Scripts/python.exe -m scripts.kr.trend_pullback.backtest --start 2025-11-26 --end 2026-05-26

양쪽(pb+ch) 동시 비교는 scripts/kr/backtest_all.py 사용.
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
from scripts.kr.trend_pullback.scoring import score_pullback, score_pullback_v3

CACHE_DIR = ROOT / "data" / "cache" / "kr"
OUT_DIR = ROOT / "scripts" / "out"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-11-26")
    ap.add_argument("--end", default="2026-05-26")
    ap.add_argument("--out", default=None, help="결과 parquet 저장 경로 (default: scripts/out/)")
    args = ap.parse_args()

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    HOLDS = (5, 10, 20, 30, 60)

    print(f"=== KR trend_pullback 백테스트 (numeric, multi-hold) ===\n")
    bt = run_backtest(
        cache_dir=CACHE_DIR,
        start=start, end=end,
        scoring_fns={"pb_score": score_pullback, "pb_score_v3": score_pullback_v3},
        hold_periods=HOLDS,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else (
        OUT_DIR / f"kr_pullback_bt_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.parquet"
    )
    bt.to_parquet(out_path, index=False)
    print(f"\n저장: {out_path}\n")

    analyze_baseline_multi(bt, HOLDS)

    print("\n" + "=" * 60)
    print(" PULLBACK v2 vs v3 비교 (threshold 별)")
    print("=" * 60)
    for th in (40, 50, 60, 70, 80):
        analyze_threshold_multi(bt, "pb_score", th, "PB v2", HOLDS)
        analyze_threshold_multi(bt, "pb_score_v3", th, "PB v3", HOLDS)

    print("\n\n" + "=" * 60)
    print(" PULLBACK v3 점수 분위별 (10분위) — 차별력 검증")
    print("=" * 60)
    analyze_quantile_multi(bt, "pb_score_v3", "PB v3", hold_periods=(30, 60))


if __name__ == "__main__":
    main()
