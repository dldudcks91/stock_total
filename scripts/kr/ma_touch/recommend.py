"""KR ma_touch recommend — KOSPI 전 종목 × 5 TF.

실행:
  .venv/Scripts/python.exe -m scripts.kr.ma_touch.recommend

산출:
  data/cache/kr/_ma_touch.parquet  (1 row / 종목)
"""
from __future__ import annotations

import sys

from scripts._common.recommend_runner import (
    discover_universe,
    evaluate_universe,
    save_recommendations,
)

ASSET = "kr"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    syms = discover_universe(ASSET)
    print(f"[KR ma_touch] universe={len(syms)} symbols", file=sys.stderr)
    df = evaluate_universe(ASSET, syms, verbose=True)
    out = save_recommendations(df, ASSET)
    n_full = (df.filter(regex=r"signal_ma_touch_.*_full").fillna(False).sum(axis=1) > 0).sum()
    n_partial = (df.filter(regex=r"signal_ma_touch_.*_partial").fillna(False).sum(axis=1) > 0).sum()
    print(f"Saved {len(df)} rows → {out}", file=sys.stderr)
    print(f"  passed_full (any TF):    {n_full}", file=sys.stderr)
    print(f"  passed_partial (any TF): {n_partial}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
