"""삼전/하이닉스 일별 외인/기관 순매수 + 시장 전체 비교.

데이터 소스:
  - Daum 종목별 일별 (api/charts/investors/days?symbolCode=AXXXXXX)
  - Daum 시장 시간대별 (api/investor/KOSPI/times) — 오늘 시장 합계
  - 개인 순매수 = 별도 컬럼 미제공 → -(외인+기관) 근사

오늘 (6/8) 외인/기관 절대값은 NaN (KRX 마감 정산 미공시).
외인 지분율 (foreignOwnSharesRate) 은 갱신되므로 변화량 × 발행주식수 로 추정.
"""

from __future__ import annotations

import sys
import requests
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

STOCKS = {"삼성전자": "A005930", "SK하이닉스": "A000660"}


def fetch_stock_days(code: str) -> pd.DataFrame:
    r = requests.get(
        f"https://finance.daum.net/api/charts/investors/days?symbolCode={code}&perPage=30",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                 "Referer": f"https://finance.daum.net/chart/{code}/investors"},
        timeout=15,
    )
    df = pd.DataFrame(r.json()["data"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values("date").reset_index(drop=True)
    # 발행주식수 = foreignOwnShares / foreignOwnSharesRate
    df["shares_outstanding"] = df["foreignOwnShares"] / df["foreignOwnSharesRate"]
    # 외인 지분율 변화로 외인 매도 추정 (만주 단위)
    df["foreign_diff_from_rate"] = (
        df["foreignOwnSharesRate"].diff() * df["shares_outstanding"]
    )
    return df


def fetch_market_today() -> dict:
    r = requests.get(
        "https://finance.daum.net/api/investor/KOSPI/times?perPage=2000",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                 "Referer": "https://finance.daum.net/domestic/investors/KOSPI"},
        timeout=15,
    )
    last = r.json()["data"][0]  # data 는 최신순
    return {
        "indiv": last["individualStraightPurchasePrice"] / 1e8,   # 억원
        "foreign": last["foreignStraightPurchasePrice"] / 1e8,
        "inst": last["institutionStraightPurchasePrice"] / 1e8,
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 250)

    dfs = {}
    for name, code in STOCKS.items():
        df = fetch_stock_days(code)
        dfs[name] = df
        last = df.iloc[-1]
        print(f"\n=== {name} ({code}) — 최근 10일 ===")
        # 표 정리 (만주 단위, 종가)
        show = df.tail(10).copy()
        show["외인순매수(만주)"] = show["foreignStraightPurchaseVolume"] / 1e4
        show["기관순매수(만주)"] = show["institutionStraightPurchaseVolume"] / 1e4
        # 개인 근사 (만주) — 시장 net 0 가정
        show["개인근사(만주)"] = -(show["외인순매수(만주)"] + show["기관순매수(만주)"])
        show["종가"] = show["tradePrice"].astype(int)
        show["전일대비%"] = show["tradePrice"].pct_change() * 100
        show["외인지분율"] = (show["foreignOwnSharesRate"] * 100).round(3)
        show["지분율_차"] = (show["foreignOwnSharesRate"].diff() * 100).round(4)
        show["외인추정(만주)"] = (show["foreign_diff_from_rate"] / 1e4).round(0)
        print(show[["date","종가","전일대비%","외인순매수(만주)","기관순매수(만주)","개인근사(만주)",
                     "외인지분율","지분율_차","외인추정(만주)"]].to_string(index=False))

    # 오늘 시장 vs 종목 (오늘만 별도)
    print("\n=== 2026-06-08 비교 — 종목별 (Daum 지분율 추정) vs 시장 전체 (Daum 시간대별) ===")
    mkt = fetch_market_today()
    rows = []
    for name, df in dfs.items():
        last = df.iloc[-1]
        prev = df.iloc[-2]
        # 외인 매도 (주) — 지분율 변화 × 발행
        est_foreign = last["foreign_diff_from_rate"]
        rows.append({
            "구분": name,
            "오늘 종가": f"{int(last['tradePrice']):,}",
            "전일 대비%": f"{(last['tradePrice']/prev['tradePrice']-1)*100:+.2f}%",
            "외인 (만주)": f"{est_foreign/1e4:+,.0f} (지분율 추정)",
            "기관 (만주)": "미공시",
            "개인 (만주)": "미공시",
        })
    rows.append({
        "구분": "KOSPI 시장 전체",
        "오늘 종가": "7,484.41",
        "전일 대비%": "-8.29%",
        "외인 (만주)": f"{mkt['foreign']:+,.0f} 억원",
        "기관 (만주)": f"{mkt['inst']:+,.0f} 억원",
        "개인 (만주)": f"{mkt['indiv']:+,.0f} 억원",
    })
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
