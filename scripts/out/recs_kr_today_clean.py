"""오늘 ma_touch 통과 KR 종목 — 두 그룹 노출.

  ① NEW(오늘 하락/보합 진입) = passers(Mon) − passers(Fri), today_ret ≤ 0
  ② MAINTAINED(유지)        = passers(Mon) ∩ passers(Fri)

추격 위험 큰 'NEW 상승 진입' 그룹은 별도 카운트만.
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

FRI = pd.Timestamp("2026-06-12")
MON = pd.Timestamp("2026-06-15")


def evaluate_one(asset: str, sym: str, cutoff: pd.Timestamp):
    try:
        df_d = load_normalized_daily(asset, sym)
    except Exception:
        return None
    df_d = df_d[df_d.index <= cutoff]
    if len(df_d) < MIN_DAILY_BARS or cutoff not in df_d.index:
        return None
    mtf = resample_multi_tf(df_d)
    allowed = set(select_eval_tfs(mtf))
    today_low = float(df_d["low"].iloc[-1])
    passed_tfs = []
    for tf in EVAL_TFS:
        df_tf = mtf[tf]
        kind = determine_eval_kind(df_tf)
        if (tf not in allowed) or kind == "skip":
            continue
        df_ind = compute_mtf_indicators(df_tf, kind)
        pf, pp, _ = evaluate_tf(df_ind, df_d, kind, today_low=today_low)
        if pf or pp:
            passed_tfs.append(tf)
    return passed_tfs


def main():
    asset = "kr"
    symbols = discover_universe(asset)
    print(f"universe={len(symbols)}", file=sys.stderr)

    fri_set = set()
    for sym in symbols:
        tfs = evaluate_one(asset, sym, FRI)
        if tfs:
            fri_set.add(sym)
    print(f"Fri passers: {len(fri_set)}", file=sys.stderr)

    listing = pd.read_csv(_ROOT / "data" / "cache" / "kr" / "_listing.csv", dtype={"Symbol": str})
    name_map = dict(zip(listing["Symbol"], listing["Name"]))

    new_rows = []
    maintained_rows = []
    for i, sym in enumerate(symbols, 1):
        tfs = evaluate_one(asset, sym, MON)
        if not tfs:
            continue
        path = _ROOT / "data" / "cache" / "kr" / f"{sym}.parquet"
        d = pd.read_parquet(path)
        d.columns = [c.lower() for c in d.columns]
        d = d.sort_index()
        if MON not in d.index or FRI not in d.index:
            continue
        mc = float(d.loc[MON, "close"])
        fc = float(d.loc[FRI, "close"])
        today_ret = (mc - fc) / fc * 100
        row = {"Symbol": sym, "Name": name_map.get(sym, ""),
               "close": mc, "Fri_close": fc, "today_ret_pct": today_ret,
               "passed_TFs": ",".join(tfs)}
        if sym in fri_set:
            maintained_rows.append(row)
        else:
            new_rows.append(row)
        if i % 200 == 0:
            print(f"  [{i}/{len(symbols)}]", file=sys.stderr)

    new_df = pd.DataFrame(new_rows).sort_values("today_ret_pct").reset_index(drop=True)
    maint_df = pd.DataFrame(maintained_rows).sort_values("today_ret_pct").reset_index(drop=True)

    new_no_rally = new_df[new_df["today_ret_pct"] <= 0]
    new_rally = new_df[new_df["today_ret_pct"] > 0]

    print(f"\nMon 통과 합계      : {len(new_df) + len(maint_df)}")
    print(f"  ① 오늘 새 진입   : {len(new_df)}")
    print(f"      하락/보합     : {len(new_no_rally)}  ← 깔끔한 자리")
    print(f"      상승 (추격위험): {len(new_rally)}")
    print(f"  ② 금→월 유지     : {len(maint_df)}")

    print(f"\n=== ① 오늘 새 진입 — 하락/보합 ({len(new_no_rally)}) ===")
    print(new_no_rally.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    print(f"\n=== ② 금→월 유지 ({len(maint_df)}) ===")
    print("(오늘 변동 오름차순 — 약세 유지 = 더 안정적 자리)")
    print(maint_df.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    # 통계
    if len(maint_df) > 0:
        s = maint_df["today_ret_pct"]
        print(f"\n유지 그룹 오늘 변동: mean={s.mean():+.2f}%  median={s.median():+.2f}%  "
              f"상승 {(s>0).sum()}/{len(s)} ({(s>0).mean()*100:.0f}%)")

    out_dir = Path(__file__).parent
    new_no_rally.assign(group="new_no_rally").to_csv(out_dir / "_recs_kr_today_new_no_rally.csv",
                                                    index=False, encoding="utf-8-sig")
    maint_df.assign(group="maintained").to_csv(out_dir / "_recs_kr_today_maintained.csv",
                                               index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_dir.relative_to(_ROOT)}/_recs_kr_today_new_no_rally.csv, _recs_kr_today_maintained.csv")


if __name__ == "__main__":
    main()
