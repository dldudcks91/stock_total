"""지난 주 수/목/금 새 진입 중 '하락 또는 보합으로 들어간' 자리만 추출 + 오늘 변동.

entry_day_return = (entry_close − prev_day_close) / prev_day_close × 100
필터: entry_day_return ≤ 0  (당일 자체가 하락 또는 보합)
오늘 변동: (Mon_close − entry_close) / entry_close × 100
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

TUE = pd.Timestamp("2026-06-09")
WED = pd.Timestamp("2026-06-10")
THU = pd.Timestamp("2026-06-11")
FRI = pd.Timestamp("2026-06-12")
MON = pd.Timestamp("2026-06-15")

DAYS = [("수(6/10)", TUE, WED), ("목(6/11)", WED, THU), ("금(6/12)", THU, FRI)]


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


def filter_no_rally(symbols, prev_date, entry_date, name_map):
    rows = []
    for sym in sorted(symbols):
        path = _ROOT / "data" / "cache" / "kr" / f"{sym}.parquet"
        if not path.exists():
            continue
        d = pd.read_parquet(path)
        d.columns = [c.lower() for c in d.columns]
        d = d.sort_index()
        if prev_date not in d.index or entry_date not in d.index or MON not in d.index:
            continue
        pc = float(d.loc[prev_date, "close"])
        ec = float(d.loc[entry_date, "close"])
        mc = float(d.loc[MON, "close"])
        entry_ret = (ec - pc) / pc * 100
        if entry_ret > 0:
            continue   # 폭등 진입 제외
        mon_ret = (mc - ec) / ec * 100
        rows.append({"Symbol": sym, "Name": name_map.get(sym, ""),
                     "prev_close": pc, "entry_close": ec, "Mon_close": mc,
                     "entry_day_ret": entry_ret, "today_ret": mon_ret})
    return pd.DataFrame(rows).sort_values("entry_day_ret").reset_index(drop=True)


def main():
    asset = "kr"
    symbols = discover_universe(asset)
    print(f"universe={len(symbols)}", file=sys.stderr)

    tue_set = passers_at(asset, symbols, TUE)
    wed_set = passers_at(asset, symbols, WED)
    thu_set = passers_at(asset, symbols, THU)
    fri_set = passers_at(asset, symbols, FRI)

    listing = pd.read_csv(_ROOT / "data" / "cache" / "kr" / "_listing.csv", dtype={"Symbol": str})
    name_map = dict(zip(listing["Symbol"], listing["Name"]))

    new_sets = {
        "수(6/10)": (wed_set - tue_set, TUE, WED),
        "목(6/11)": (thu_set - wed_set, WED, THU),
        "금(6/12)": (fri_set - thu_set, THU, FRI),
    }

    print()
    print(f"{'진입일':10s}  {'전체신규':>8s}  {'하락+보합진입':>12s}  {'그중상승오늘':>10s}  {'평균오늘변동':>10s}")
    print("-" * 65)

    all_rows = []
    for label, (new_set, pd_date, ed_date) in new_sets.items():
        df = filter_no_rally(new_set, pd_date, ed_date, name_map)
        df["entry_day"] = label
        all_rows.append(df)
        total = len(new_set)
        n = len(df)
        pos = (df["today_ret"] > 0).sum() if n > 0 else 0
        mean_today = df["today_ret"].mean() if n > 0 else float("nan")
        print(f"{label:10s}  {total:>8d}  {n:>12d}  {pos:>8d} ({pos/max(n,1)*100:>3.0f}%)  {mean_today:>+9.2f}%")

    for label, (new_set, pd_date, ed_date) in new_sets.items():
        df = filter_no_rally(new_set, pd_date, ed_date, name_map)
        print(f"\n=== {label} 하락/보합 진입 (n={len(df)}) — entry_day_ret 오름차순 ===")
        if len(df) > 0:
            print(df.to_string(index=False,
                               columns=["Symbol", "Name", "prev_close", "entry_close", "Mon_close",
                                        "entry_day_ret", "today_ret"],
                               float_format=lambda v: f"{v:.2f}"))

    combined = pd.concat(all_rows, ignore_index=True)
    out_csv = Path(__file__).parent / "_recs_kr_weekly_new_no_rally.csv"
    combined.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
