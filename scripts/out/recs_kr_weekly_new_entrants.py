"""지난 주 수/목/금 새 진입 종목 + 오늘(월) 종가 대비 변동 (NEW rule).

각 일자의 "새 진입" = (그 날 통과) − (직전 거래일 통과)
변동 = (Mon_close − entry_day_close) / entry_day_close × 100
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

TUE = pd.Timestamp("2026-06-09")   # 직전 비교 기준
WED = pd.Timestamp("2026-06-10")
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


def build_rows(symbols, entry_date, name_map):
    rows = []
    for sym in sorted(symbols):
        path = _ROOT / "data" / "cache" / "kr" / f"{sym}.parquet"
        if not path.exists():
            continue
        d = pd.read_parquet(path)
        d.columns = [c.lower() for c in d.columns]
        d = d.sort_index()
        if entry_date not in d.index or MON not in d.index:
            continue
        ec = float(d.loc[entry_date, "close"])
        mc = float(d.loc[MON, "close"])
        ret = (mc - ec) / ec * 100
        rows.append({"Symbol": sym, "Name": name_map.get(sym, ""),
                     "entry_close": ec, "Mon_close": mc, "ret_pct": ret})
    return pd.DataFrame(rows).sort_values("ret_pct", ascending=False).reset_index(drop=True)


def summarize(df, label):
    if len(df) == 0:
        print(f"\n=== {label} (n=0) ===  데이터 없음")
        return
    s = df["ret_pct"]
    print(f"\n=== {label} (n={len(df)}) ===")
    print(f"  mean    : {s.mean():+.2f}%")
    print(f"  median  : {s.median():+.2f}%")
    print(f"  min/max : {s.min():+.2f}% / {s.max():+.2f}%")
    print(f"  >0      : {(s > 0).sum()}  ({(s > 0).mean()*100:.0f}%)")
    print(f"  <0      : {(s < 0).sum()}  ({(s < 0).mean()*100:.0f}%)")


def main():
    asset = "kr"
    symbols = discover_universe(asset)
    print(f"universe={len(symbols)}", file=sys.stderr)

    tue_set = passers_at(asset, symbols, TUE)
    print(f"Tue passers: {len(tue_set)}", file=sys.stderr)
    wed_set = passers_at(asset, symbols, WED)
    print(f"Wed passers: {len(wed_set)}", file=sys.stderr)
    thu_set = passers_at(asset, symbols, THU)
    print(f"Thu passers: {len(thu_set)}", file=sys.stderr)
    fri_set = passers_at(asset, symbols, FRI)
    print(f"Fri passers: {len(fri_set)}", file=sys.stderr)

    new_wed = wed_set - tue_set
    new_thu = thu_set - wed_set
    new_fri = fri_set - thu_set

    listing = pd.read_csv(_ROOT / "data" / "cache" / "kr" / "_listing.csv", dtype={"Symbol": str})
    name_map = dict(zip(listing["Symbol"], listing["Name"]))

    wed_df = build_rows(new_wed, WED, name_map)
    thu_df = build_rows(new_thu, THU, name_map)
    fri_df = build_rows(new_fri, FRI, name_map)

    print()
    print(f"수 통과: {len(wed_set)}  → 새 진입: {len(new_wed)}")
    print(f"목 통과: {len(thu_set)}  → 새 진입: {len(new_thu)}")
    print(f"금 통과: {len(fri_set)}  → 새 진입: {len(new_fri)}")

    summarize(wed_df, "수요일 새 진입 → 월요일 변동")
    summarize(thu_df, "목요일 새 진입 → 월요일 변동")
    summarize(fri_df, "금요일 새 진입 → 월요일 변동")

    for label, df in [("수(6/10) 새 진입", wed_df), ("목(6/11) 새 진입", thu_df), ("금(6/12) 새 진입", fri_df)]:
        print(f"\n=== {label} (n={len(df)}) — entry close → Mon(6/15) close ===")
        if len(df) > 0:
            print(df.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    out_dir = Path(__file__).parent
    wed_df["entry_day"] = "Wed"
    thu_df["entry_day"] = "Thu"
    fri_df["entry_day"] = "Fri"
    combined = pd.concat([wed_df, thu_df, fri_df], ignore_index=True)
    out_csv = out_dir / "_recs_kr_weekly_new_entrants.csv"
    combined.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
