"""오늘(또는 지정 날짜) KR 상승률 TOP N — strategy-agnostic 유틸.

scripts/misc/kr_top_gainers_today.py 의 인계자. 구버전의 점수 시스템
(visual_review 라벨 기반 single composite — deprecated) 은 제거하고
**순수 상승률 TOP** 만 남김. 점수가 필요하면 scripts.kr.recommend_all 사용.

사용:
    .venv/Scripts/python.exe -m scripts.kr._common.top_gainers --date 2026-05-26 --topn 10
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

CACHE_DIR = ROOT / "data" / "cache" / "kr"


def get_change_on(sym: str, date: pd.Timestamp) -> tuple[float, float, float]:
    """(change_pct, close, volume_ratio_20d) — 해당 일 데이터 없으면 (nan, nan, nan)."""
    p = CACHE_DIR / f"{sym}.parquet"
    if not p.exists():
        return float("nan"), float("nan"), float("nan")
    df = pd.read_parquet(p)
    if date not in df.index:
        return float("nan"), float("nan"), float("nan")
    row = df.loc[date]
    chg = row.get("Change", float("nan"))
    close = row.get("Close", float("nan"))
    df_prior = df.loc[df.index < date].tail(20)
    vol_avg = df_prior["Volume"].mean() if len(df_prior) else float("nan")
    vol_ratio = row["Volume"] / vol_avg if vol_avg and vol_avg > 0 else float("nan")
    return float(chg), float(close), float(vol_ratio)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-05-26")
    ap.add_argument("--topn", type=int, default=10)
    args = ap.parse_args()

    date = pd.Timestamp(args.date)
    print(f"=== KR 일간 상승률 TOP {args.topn} on {date.date()} ===\n")

    syms = sorted(p.stem for p in CACHE_DIR.glob("[0-9]*.parquet"))
    rows = []
    for sym in syms:
        chg, close, volr = get_change_on(sym, date)
        if chg != chg:  # NaN
            continue
        rows.append({"symbol": sym, "change": chg, "close": close, "vol_ratio": volr})

    df = pd.DataFrame(rows).sort_values("change", ascending=False)
    print(f"전체 거래 종목: {len(df)}\n")

    try:
        import FinanceDataReader as fdr
        uni = fdr.StockListing("KOSPI")[["Code", "Name", "Marcap"]].rename(columns={"Code": "symbol"})
        df = df.merge(uni, on="symbol", how="left")
    except Exception:
        df["Name"] = ""
        df["Marcap"] = 0

    top = df.head(args.topn).copy()
    top["change"] = (top["change"] * 100).round(2).astype(str) + "%"
    top["close"] = top["close"].round(0).astype(int)
    top["vol_ratio"] = top["vol_ratio"].round(1)
    cols = [c for c in ["symbol", "Name", "change", "close", "vol_ratio", "Marcap"] if c in top.columns]
    print(top[cols].to_string(index=False))


if __name__ == "__main__":
    main()
