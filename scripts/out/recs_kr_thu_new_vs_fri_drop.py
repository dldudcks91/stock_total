"""목요일 새 진입 vs 금요일 탈락 — 같은 종목인지 확인.

  Thu_new = passers(Thu) − passers(Wed)
  Fri_drop = passers(Thu) − passers(Fri)
  교집합 / 비교
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.mtf_loader import load_normalized_daily, resample_multi_tf
from scripts._common.mtf_indicators import compute_mtf_indicators
from scripts._common.signals import evaluate_tf
from scripts._common.tf_selector import determine_eval_kind, select_eval_tfs
from scripts._common.recommend_runner import EVAL_TFS, MIN_DAILY_BARS, discover_universe


def passers_at(asset: str, symbols, cutoff: pd.Timestamp) -> set[str]:
    passed: set[str] = set()
    for sym in symbols:
        try:
            df_d = load_normalized_daily(asset, sym)
        except Exception:
            continue
        df_d = df_d[df_d.index <= cutoff]
        if len(df_d) < MIN_DAILY_BARS:
            continue
        mtf = resample_multi_tf(df_d)
        allowed = set(select_eval_tfs(mtf))
        today_low = float(df_d["low"].iloc[-1])
        for tf in EVAL_TFS:
            df_tf = mtf[tf]
            kind = determine_eval_kind(df_tf)
            if (tf not in allowed) or kind == "skip":
                continue
            df_ind = compute_mtf_indicators(df_tf, kind)
            pf, pp, _ = evaluate_tf(df_ind, df_d, kind, today_low=today_low)
            if pf or pp:
                passed.add(sym)
                break
    return passed


def main():
    asset = "kr"
    wed = pd.Timestamp("2026-06-10")
    thu = pd.Timestamp("2026-06-11")
    fri = pd.Timestamp("2026-06-12")

    symbols = discover_universe(asset)
    print(f"universe={len(symbols)}", file=sys.stderr)

    wed_set = passers_at(asset, symbols, wed)
    print(f"Wed passers: {len(wed_set)}", file=sys.stderr)
    thu_set = passers_at(asset, symbols, thu)
    print(f"Thu passers: {len(thu_set)}", file=sys.stderr)
    fri_set = passers_at(asset, symbols, fri)
    print(f"Fri passers: {len(fri_set)}", file=sys.stderr)

    thu_new = thu_set - wed_set                 # 목요일에 새로 진입
    fri_drop = thu_set - fri_set                # 금요일에 탈락
    overlap = thu_new & fri_drop                # 두 set 의 교집합

    listing = pd.read_csv(_ROOT / "data" / "cache" / "kr" / "_listing.csv", dtype={"Symbol": str})
    name_map = dict(zip(listing["Symbol"], listing["Name"]))

    def fmt(syms):
        return sorted([(s, name_map.get(s, "")) for s in syms], key=lambda x: x[0])

    print()
    print(f"수요일 통과: {len(wed_set)}")
    print(f"목요일 통과: {len(thu_set)}  (그중 새 진입 {len(thu_new)})")
    print(f"금요일 통과: {len(fri_set)}  (그중 새 진입 {len(fri_set - thu_set)})")
    print(f"금요일 탈락: {len(fri_drop)}")
    print()
    print(f"=== 목요일 새 진입 ({len(thu_new)}) ∩ 금요일 탈락 ({len(fri_drop)}) ===")
    print(f"교집합: {len(overlap)}")
    print(f"  → 목 새 진입의 {len(overlap)/max(len(thu_new),1)*100:.0f}% 가 금에 즉시 탈락")
    print(f"  → 금 탈락 73 중 {len(overlap)/max(len(fri_drop),1)*100:.0f}% 가 목요일 신규 진입자")
    print()
    print("=== 교집합 종목 (목 새진입 + 금 탈락, 1일 천하) ===")
    for s, n in fmt(overlap):
        print(f"  {s}  {n}")

    only_thu_new_kept = thu_new - fri_drop      # 목에 들어와서 금에도 살아남음
    print(f"\n=== 목 새진입 중 금에도 살아남은 ({len(only_thu_new_kept)}) ===")
    for s, n in fmt(only_thu_new_kept):
        print(f"  {s}  {n}")

    fri_drop_not_thu_new = fri_drop - thu_new   # 금 탈락인데 목엔 새진입 아님 (그 전부터 있던 종목)
    print(f"\n=== 금 탈락이지만 목 이전부터 있던 ({len(fri_drop_not_thu_new)}) ===")
    for s, n in fmt(fri_drop_not_thu_new):
        print(f"  {s}  {n}")


if __name__ == "__main__":
    main()
