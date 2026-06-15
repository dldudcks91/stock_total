"""금요일 신규 / 탈락 / 양일포함 — 3그룹의 월요일 수익률 비교 (NEW rule).

신규(only Fri):  Thu 통과 X, Fri 통과 O
탈락(only Thu):  Thu 통과 O, Fri 통과 X
양일(both):      Thu 통과 O, Fri 통과 O

기준: (Mon_close − Fri_close) / Fri_close × 100
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

THU = pd.Timestamp("2026-06-11")
FRI = pd.Timestamp("2026-06-12")
MON = pd.Timestamp("2026-06-15")


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


def mon_returns(symbols, name_map):
    rows = []
    for sym in symbols:
        path = _ROOT / "data" / "cache" / "kr" / f"{sym}.parquet"
        if not path.exists():
            continue
        d = pd.read_parquet(path)
        d.columns = [c.lower() for c in d.columns]
        d = d.sort_index()
        if FRI not in d.index or MON not in d.index:
            continue
        fri_c = float(d.loc[FRI, "close"])
        mon_c = float(d.loc[MON, "close"])
        ret = (mon_c - fri_c) / fri_c * 100
        rows.append({"Symbol": sym, "Name": name_map.get(sym, ""),
                     "Fri_close": fri_c, "Mon_close": mon_c, "ret_pct": ret})
    return pd.DataFrame(rows).sort_values("ret_pct", ascending=False).reset_index(drop=True)


def summarize(df, label):
    s = df["ret_pct"]
    print(f"\n=== {label} (n={len(df)}) ===")
    print(f"  mean    : {s.mean():+.2f}%")
    print(f"  median  : {s.median():+.2f}%")
    print(f"  std     : {s.std():.2f}%")
    print(f"  min     : {s.min():+.2f}%")
    print(f"  max     : {s.max():+.2f}%")
    print(f"  >0      : {(s > 0).sum()}  ({(s > 0).mean()*100:.0f}%)")
    print(f"  ==0     : {(s == 0).sum()}")
    print(f"  <0      : {(s < 0).sum()}  ({(s < 0).mean()*100:.0f}%)")


def main():
    asset = "kr"
    symbols = discover_universe(asset)
    print(f"universe={len(symbols)}", file=sys.stderr)

    thu_set = passers_at(asset, symbols, THU)
    fri_set = passers_at(asset, symbols, FRI)
    only_fri = fri_set - thu_set
    only_thu = thu_set - fri_set
    both = thu_set & fri_set
    print(f"Thu={len(thu_set)}, Fri={len(fri_set)}, new={len(only_fri)}, drop={len(only_thu)}, both={len(both)}",
          file=sys.stderr)

    listing = pd.read_csv(_ROOT / "data" / "cache" / "kr" / "_listing.csv", dtype={"Symbol": str})
    name_map = dict(zip(listing["Symbol"], listing["Name"]))

    new_df = mon_returns(only_fri, name_map)
    drop_df = mon_returns(only_thu, name_map)
    both_df = mon_returns(both, name_map)

    summarize(new_df, "신규 진입 (only Fri)")
    summarize(drop_df, "탈락       (only Thu)")
    summarize(both_df, "양일 모두 (both)")

    print("\n=== 그룹 평균/중앙값 ===")
    for label, df in [("신규", new_df), ("탈락", drop_df), ("양일", both_df)]:
        print(f"  {label}: mean={df['ret_pct'].mean():+.2f}%  median={df['ret_pct'].median():+.2f}%  n={len(df)}")

    # 풀 리스트 (신규/양일) 출력
    print("\n=== 신규 진입 — 상위/하위 5 ===")
    print(new_df.head(5).to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print("---")
    print(new_df.tail(5).iloc[::-1].to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    print("\n=== 탈락 — 상위/하위 5 ===")
    print(drop_df.head(5).to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print("---")
    print(drop_df.tail(5).iloc[::-1].to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    print("\n=== 양일 모두 (전체) ===")
    print(both_df.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    # 저장
    new_df["bucket"] = "new"
    drop_df["bucket"] = "drop"
    both_df["bucket"] = "both"
    combined = pd.concat([new_df, drop_df, both_df], ignore_index=True)
    out_csv = Path(__file__).parent / "_recs_kr_three_way_perf.csv"
    combined.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
