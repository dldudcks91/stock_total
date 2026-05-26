"""KR 통합 추천 — pullback / chase 두 전략 분리 TOP N (**사용자 표준**).

scripts/misc/kr_recommend_split.py 의 인계자. visual_review 5/21 라벨 + cutoff 시점
fresh facts 를 결합해 두 전략 각각 점수 매김.

점수 함수는 strategy 폴더에 분산 보관:
  - scripts.kr.trend_pullback.scoring_label.score_pullback_label
  - scripts.kr.trend_chase.scoring_label.score_chase_label

사용:
    .venv/Scripts/python.exe -m scripts.kr.recommend_all
    .venv/Scripts/python.exe -m scripts.kr.recommend_all --cutoff 2026-05-26 --topn 15
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.facts_loader import load_fresh_facts, load_visual_label
from scripts.kr.trend_pullback.scoring_label import score_pullback_label, PB_MAX
from scripts.kr.trend_chase.scoring_label import score_chase_label, CH_MAX

CACHE_DIR = ROOT / "data" / "cache" / "kr"
REVIEW_DIR = ROOT / "data" / "cache" / "kr" / "visual_review" / "reviews"
LABEL_DATE = "20260521"
OUT_DIR = ROOT / "scripts" / "out"


def fmt_marcap(m):
    if pd.isna(m) or m == 0:
        return "-"
    if m >= 1e12:
        return f"{m/1e12:.2f}조"
    if m >= 1e8:
        return f"{m/1e8:.0f}억"
    return f"{m:.0f}"


def fmt_amount(a):
    if pd.isna(a):
        return "-"
    if a >= 1e12:
        return f"{a/1e12:.2f}조"
    if a >= 1e10:
        return f"{a/1e8:.0f}억"
    if a >= 1e8:
        return f"{a/1e8:.1f}억"
    return f"{a/1e8:.2f}억"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", default="2026-05-26")
    ap.add_argument("--topn", type=int, default=15)
    ap.add_argument("--label-date", default=LABEL_DATE,
                    help="visual_review JSON 라벨 날짜 (default: 20260521)")
    args = ap.parse_args()

    cutoff = pd.Timestamp(args.cutoff)
    print(f"cutoff = {cutoff.date()} (visual label은 {args.label_date} 그대로)\n")

    rows = []
    syms = sorted(p.stem for p in CACHE_DIR.glob("[0-9]*.parquet"))
    for i, sym in enumerate(syms):
        if i % 200 == 0:
            print(f"  [{i}/{len(syms)}] ...")
        label = load_visual_label(REVIEW_DIR, sym, args.label_date)
        if not label:
            continue
        fresh, today = load_fresh_facts(CACHE_DIR / f"{sym}.parquet", cutoff)
        if not fresh.get("tf_1d"):
            continue

        pb = score_pullback_label(label, fresh)
        ch = score_chase_label(label, fresh, today["vol_ratio"] or 0)

        tf_1d = fresh["tf_1d"]
        row = {
            "symbol": sym,
            "last_close": today["close"],
            "today_chg": today["change"],
            "vol_ratio": today["vol_ratio"],
            "today_amount": today["amount"],
            "s_1m": (label.get("tf_1m") or {}).get("state"),
            "s_1w": (label.get("tf_1w") or {}).get("state"),
            "s_1d": (label.get("tf_1d") or {}).get("state"),
            "m_1w": (label.get("tf_1w") or {}).get("micro_action"),
            "m_1d": (label.get("tf_1d") or {}).get("micro_action"),
            "v_1w": (label.get("tf_1w") or {}).get("volume_flag"),
            "acc_w": round((fresh.get("tf_1w", {}).get("accumulation") or {}).get("accumulation_score", 0), 2),
            "acc_d": round((tf_1d.get("accumulation") or {}).get("accumulation_score", 0), 2),
            "ret_30d": round(tf_1d.get("ret_30d", 0), 3),
            "ret_90d": round(tf_1d.get("ret_90d", 0), 3),
            "from_high": round(tf_1d.get("from_period_high_pct", 0), 3),
            "verdict": label.get("verdict"),
            "risk_flags": ",".join(label.get("risk_flags", []) or []),
            **pb,
            **ch,
        }
        rows.append(row)

    df = pd.DataFrame(rows)

    # 종목명
    try:
        import FinanceDataReader as fdr
        uni = fdr.StockListing("KOSPI")[["Code", "Name", "Marcap"]].rename(columns={"Code": "symbol"})
        df = df.merge(uni, on="symbol", how="left")
    except Exception:
        df["Name"] = ""

    df["Marcap_fmt"] = df.get("Marcap", pd.Series(dtype=float)).apply(fmt_marcap) if "Marcap" in df.columns else "-"
    df["today_amount_fmt"] = df["today_amount"].apply(fmt_amount)

    # ─── PULLBACK 출력 ───
    fmt_cols_common = ["symbol", "Name", "Marcap_fmt", "today_chg", "today_amount_fmt", "vol_ratio"]
    pb_df = df[~df["cut_pb"]].copy().sort_values("pb_score", ascending=False)
    pb_cols = fmt_cols_common + ["pb_score", "pb_pct", "s_1m", "s_1w", "s_1d", "m_1w", "m_1d",
                                  "v_1w", "acc_w", "acc_d", "ret_30d", "from_high", "verdict", "risk_flags"]
    pb_show = pb_df[pb_cols].head(args.topn).copy()
    pb_show["today_chg"] = (pb_show["today_chg"] * 100).round(2).astype(str) + "%"
    pb_show["pb_score"] = pb_show["pb_score"].astype(str) + f" / {PB_MAX}"
    pb_show["pb_pct"] = pb_show["pb_pct"].astype(str) + "%"
    pb_show["vol_ratio"] = pb_show["vol_ratio"].round(1)
    pb_show = pb_show.rename(columns={"Marcap_fmt": "시총", "today_amount_fmt": "거래대금"})
    print(f"=== PULLBACK 추천 TOP {args.topn} (눌림목 매수) ===")
    print(pb_show.to_string(index=False))

    # ─── CHASE 출력 ───
    ch_df = df[~df["cut_ch"]].copy().sort_values("ch_score", ascending=False)
    ch_cols = fmt_cols_common + ["ch_score", "ch_pct", "s_1m", "s_1w", "s_1d", "m_1w", "m_1d",
                                  "v_1w", "ret_30d", "ret_90d", "from_high", "verdict", "risk_flags"]
    ch_show = ch_df[ch_cols].head(args.topn).copy()
    ch_show["today_chg"] = (ch_show["today_chg"] * 100).round(2).astype(str) + "%"
    ch_show["ch_score"] = ch_show["ch_score"].astype(str) + f" / {CH_MAX}"
    ch_show["ch_pct"] = ch_show["ch_pct"].astype(str) + "%"
    ch_show["vol_ratio"] = ch_show["vol_ratio"].round(1)
    ch_show = ch_show.rename(columns={"Marcap_fmt": "시총", "today_amount_fmt": "거래대금"})
    print(f"\n=== CHASE 추천 TOP {args.topn} (추격) ===")
    print(ch_show.to_string(index=False))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = OUT_DIR / f"kr_recommend_all_{cutoff.strftime('%Y%m%d')}.csv"
    df.sort_values("pb_score", ascending=False).to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n전체 저장: {out_csv}")


if __name__ == "__main__":
    main()
