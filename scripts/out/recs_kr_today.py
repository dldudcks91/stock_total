"""오늘(2026-06-15 Mon) ma_touch 통과 KR 종목 — NEW rule.

각 종목의 통과 TF, 오늘 일변동, 종가 표시. 오늘 약세로 진입한 자리 우선 노출.
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
    if not passed_tfs:
        return None
    mon_close = float(df_d.loc[MON, "close"])
    fri_close = float(df_d.loc[FRI, "close"]) if FRI in df_d.index else None
    today_ret = (mon_close - fri_close) / fri_close * 100 if fri_close else None
    return {"Symbol": sym, "close": mon_close, "Fri_close": fri_close,
            "today_ret_pct": today_ret, "passed_TFs": ",".join(passed_tfs),
            "n_tf": len(passed_tfs)}


def main():
    asset = "kr"
    symbols = discover_universe(asset)
    print(f"universe={len(symbols)}", file=sys.stderr)

    rows = []
    for i, sym in enumerate(symbols, 1):
        r = evaluate_one(asset, sym, MON)
        if r is not None:
            rows.append(r)
        if i % 200 == 0:
            print(f"  [{i}/{len(symbols)}] passers so far={len(rows)}", file=sys.stderr)

    if not rows:
        print("no passers", file=sys.stderr)
        return

    listing = pd.read_csv(_ROOT / "data" / "cache" / "kr" / "_listing.csv", dtype={"Symbol": str})
    name_map = dict(zip(listing["Symbol"], listing["Name"]))
    for r in rows:
        r["Name"] = name_map.get(r["Symbol"], "")

    df = pd.DataFrame(rows)
    df = df[["Symbol", "Name", "close", "Fri_close", "today_ret_pct", "passed_TFs", "n_tf"]]

    print(f"\n오늘({MON.date()}) ma_touch 통과 KR 종목: {len(df)}")
    print()
    pos = df[df["today_ret_pct"] > 0].sort_values("today_ret_pct", ascending=False)
    flat = df[df["today_ret_pct"].between(-0.01, 0.01, inclusive="both")]
    neg = df[df["today_ret_pct"] < 0].sort_values("today_ret_pct")

    print(f"오늘 상승 진입: {len(pos)}")
    print(f"오늘 보합 진입: {len(flat)}")
    print(f"오늘 하락 진입: {len(neg)}")

    # 하락/보합 진입 우선 노출
    print(f"\n=== 오늘 하락 진입 ({len(neg)}) — 깔끔한 자리 ===")
    print(neg.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    print(f"\n=== 오늘 보합 진입 ({len(flat)}) ===")
    if len(flat) > 0:
        print(flat.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    print(f"\n=== 오늘 상승 진입 ({len(pos)}) — 추격 위험 ===")
    print(pos.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    out_csv = Path(__file__).parent / "_recs_kr_today.csv"
    df.sort_values("today_ret_pct").to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
