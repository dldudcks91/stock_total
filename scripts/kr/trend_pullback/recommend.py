"""trend_pullback 단독 추천 — v3 (numeric) 기반 TOP N.

scripts/misc/kr_recommend_v3.py 의 PULLBACK 절반을 그대로 분리. visual_review 라벨
없이 일봉 캐시만으로 점수 매김 → label 가용 여부에 영향 X (매일 신선).

운영 threshold: PB v3 ≥ 45 (백테스트 기반 sweet spot).
사용:
    .venv/Scripts/python.exe -m scripts.kr.trend_pullback.recommend
    .venv/Scripts/python.exe -m scripts.kr.trend_pullback.recommend --cutoff 2026-05-26 --topn 20

양쪽(pb+ch) 동시 추천은 scripts/kr/recommend_all.py 사용 (label-based 통합).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.indicators import compute_indicators, compute_weekly_acc
from scripts.kr.trend_pullback.scoring import score_pullback_v3, PB_V3_MAX

CACHE_DIR = ROOT / "data" / "cache" / "kr"
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
    ap.add_argument("--topn", type=int, default=5)
    args = ap.parse_args()

    cutoff = pd.Timestamp(args.cutoff)
    print(f"=== KR PULLBACK 추천 (cutoff={cutoff.date()}, v3 numeric) ===\n")

    syms = sorted(p.stem for p in CACHE_DIR.glob("[0-9]*.parquet"))
    rows = []
    for sym in syms:
        try:
            df = pd.read_parquet(CACHE_DIR / f"{sym}.parquet")
            df = df[df.index <= cutoff]
            if len(df) < 120:
                continue
            df = compute_indicators(df)
            df["acc_w"] = compute_weekly_acc(df)
            df["pb_score_v3"] = score_pullback_v3(df)

            last = df.iloc[-1]
            today_vol = float(last["Volume"])
            last_close = float(last["Close"])
            prior_vol = df.iloc[-21:-1]["Volume"].mean()
            today_vol_ratio = float(today_vol / prior_vol) if prior_vol and prior_vol > 0 else float("nan")

            rows.append({
                "symbol": sym,
                "last_close": last_close,
                "today_chg": float(last.get("Change", 0)),
                "today_amount": today_vol * last_close,
                "vol_ratio": today_vol_ratio,
                "pb_score": float(last["pb_score_v3"]),
                "bull_stack": int(last["bull_stack"]),
                "dist_ma10": float(last["dist_ma10"]),
                "dist_ma20": float(last["dist_ma20"]),
                "ret_30d": float(last["ret_30d"]),
                "ret_90d": float(last["ret_90d"]),
                "from_high_1y": float(last["from_high_1y"]),
                "acc_d": float(last["acc_d"]),
                "vol_recent_vs_prior": float(last["vol_recent_vs_prior"]),
                "recent_strong_bull_10d": int(last["recent_strong_bull_10d"]),
            })
        except Exception:
            continue

    df_all = pd.DataFrame(rows)

    try:
        import FinanceDataReader as fdr
        uni = fdr.StockListing("KOSPI")[["Code", "Name", "Marcap"]].rename(columns={"Code": "symbol"})
        df_all = df_all.merge(uni, on="symbol", how="left")
    except Exception:
        df_all["Name"] = ""
        df_all["Marcap"] = 0

    df_all["시총"] = df_all["Marcap"].apply(fmt_marcap)
    df_all["거래대금"] = df_all["today_amount"].apply(fmt_amount)
    df_all["today_chg_str"] = (df_all["today_chg"] * 100).round(2).astype(str) + "%"
    df_all["vol_x"] = df_all["vol_ratio"].round(1)
    df_all["pb_pct"] = (df_all["pb_score"] / PB_V3_MAX * 100).round(1)

    pb = df_all.sort_values("pb_score", ascending=False).head(args.topn).copy()
    pb["pb_score_fmt"] = pb["pb_score"].round(0).astype(int).astype(str) + f"/{PB_V3_MAX}"
    cols = ["symbol", "Name", "시총", "today_chg_str", "거래대금", "vol_x",
            "pb_score_fmt", "pb_pct", "dist_ma10", "dist_ma20",
            "ret_30d", "ret_90d", "from_high_1y", "acc_d",
            "vol_recent_vs_prior", "recent_strong_bull_10d", "bull_stack"]
    pb_show = pb[cols].rename(columns={
        "today_chg_str": "today_chg", "vol_x": "vol_ratio",
        "pb_score_fmt": "pb_score", "vol_recent_vs_prior": "vol10/30",
        "recent_strong_bull_10d": "bull10d",
    })
    for c in ["dist_ma10", "dist_ma20", "ret_30d", "ret_90d", "from_high_1y", "vol10/30"]:
        pb_show[c] = pb_show[c].round(3)
    pb_show["acc_d"] = pb_show["acc_d"].round(2)
    print(pb_show.to_string(index=False))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = OUT_DIR / f"kr_pullback_recommend_{cutoff.strftime('%Y%m%d')}.csv"
    df_all.sort_values("pb_score", ascending=False).to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n전체 저장: {out_csv}")


if __name__ == "__main__":
    main()
