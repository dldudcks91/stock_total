"""KR ma_touch — 목(2026-06-11) vs 금(2026-06-12) 통과 종목 비교.

각 cutoff 일자까지의 일봉만 사용해 mtf 재구성 후 평가. Friday에 새로 진입한 종목 출력.
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
    """cutoff 일자까지의 일봉으로 ma_touch 통과한 symbol set 반환."""
    passed: set[str] = set()
    n = len(symbols)
    for i, sym in enumerate(symbols, 1):
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
        if i % 100 == 0:
            print(f"  [{cutoff.date()}] {i}/{n}", file=sys.stderr)
    return passed


def main():
    asset = "kr"
    thu = pd.Timestamp("2026-06-11")
    fri = pd.Timestamp("2026-06-12")

    symbols = discover_universe(asset)
    print(f"[{asset}] universe={len(symbols)}", file=sys.stderr)

    print(f"=== Thu={thu.date()} ===", file=sys.stderr)
    thu_set = passers_at(asset, symbols, thu)
    print(f"Thu passers: {len(thu_set)}", file=sys.stderr)

    print(f"=== Fri={fri.date()} ===", file=sys.stderr)
    fri_set = passers_at(asset, symbols, fri)
    print(f"Fri passers: {len(fri_set)}", file=sys.stderr)

    only_fri = fri_set - thu_set        # 금요일 새 진입
    only_thu = thu_set - fri_set        # 금요일 탈락
    both = thu_set & fri_set

    listing = pd.read_csv(_ROOT / "data" / "cache" / "kr" / "_listing.csv", dtype={"Symbol": str})
    name_map = dict(zip(listing["Symbol"], listing["Name"]))

    def rows(syms):
        return sorted([(s, name_map.get(s, "")) for s in syms], key=lambda x: x[0])

    out_dir = Path(__file__).parent
    fri_new_path = out_dir / "_recs_kr_fri_new.csv"
    fri_drop_path = out_dir / "_recs_kr_fri_drop.csv"
    pd.DataFrame(rows(only_fri), columns=["Symbol", "Name"]).to_csv(fri_new_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(rows(only_thu), columns=["Symbol", "Name"]).to_csv(fri_drop_path, index=False, encoding="utf-8-sig")

    print()
    print(f"Thursday 통과: {len(thu_set)} 종목")
    print(f"Friday   통과: {len(fri_set)} 종목")
    print(f"양일 모두 : {len(both)}")
    print(f"금요일 새 진입 (only Fri): {len(only_fri)}")
    print(f"금요일 탈락   (only Thu): {len(only_thu)}")
    print()
    print(f"== 금요일 새 진입 ({len(only_fri)}) ==")
    for s, n in rows(only_fri):
        print(f"  {s}  {n}")
    print(f"\nCSV: {fri_new_path.relative_to(_ROOT)}, {fri_drop_path.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
