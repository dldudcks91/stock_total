"""삼전/하이닉스 시간대별 가격 + KOSPI 시장 시간대별 투자자 동향 합성 표.

한계:
  종목별 (개인/외국인/기관) 시간대별 매매동향 데이터는 무료 path 에서 제공 안 됨
  (KRX 인증 막힘, 네이버/Daum 모두 일별만). broker API (KIS/키움) 필수.
  대안으로:
    - 종목별: 시간대별 가격 + 거래대금 (네이버 분봉)
    - 시장 전체 (KOSPI): 시간대별 개인/외국인/기관 순매수 (Daum)
  두 데이터를 같은 표에 배치해 종목 흐름이 시장 외인/기관 흐름과 동기화되는지 확인.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

STOCKS = {
    "삼성전자": "005930",
    "SK하이닉스": "000660",
}


def fetch_stock_minute(code: str) -> pd.DataFrame:
    url = f"https://api.stock.naver.com/chart/domestic/item/{code}/minute"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=15)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    df["dt"] = pd.to_datetime(df["localDateTime"], format="%Y%m%d%H%M%S")
    df = df.rename(columns={
        "currentPrice": "close", "openPrice": "open",
        "highPrice": "high", "lowPrice": "low",
        "accumulatedTradingVolume": "volume_cum",
    })
    df["volume"] = df["volume_cum"].diff().fillna(df["volume_cum"]).clip(lower=0)
    return df[["dt", "open", "high", "low", "close", "volume"]]


def fetch_daum_market_times(market: str = "KOSPI") -> pd.DataFrame:
    url = f"https://finance.daum.net/api/investor/{market}/times?perPage=1000"
    r = requests.get(url, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json",
        "Referer": f"https://finance.daum.net/domestic/investors/{market}",
    }, timeout=15)
    r.raise_for_status()
    df = pd.DataFrame(r.json()["data"])
    df["dt"] = pd.to_datetime(df["date"])
    df = df.rename(columns={
        "individualStraightPurchasePrice": "indiv_cum",
        "foreignStraightPurchasePrice": "foreign_cum",
        "institutionStraightPurchasePrice": "inst_cum",
    })
    return df.sort_values("dt").reset_index(drop=True)[["dt", "indiv_cum", "foreign_cum", "inst_cum"]]


def hourly_stock(df_min: pd.DataFrame) -> pd.DataFrame:
    g = df_min.set_index("dt").resample("1h", origin="start_day", offset="9h")
    out = pd.DataFrame({
        "open": g["open"].first(),
        "high": g["high"].max(),
        "low": g["low"].min(),
        "close": g["close"].last(),
        "volume": g["volume"].sum(),
    }).dropna()
    out["amount_M"] = (out["volume"] * (out["open"] + out["close"]) / 2 / 1e8)  # 억원
    out["ret_pct"] = (out["close"] / out["open"] - 1) * 100
    return out


def hourly_market_diff(df_cum: pd.DataFrame) -> pd.DataFrame:
    """09:00 → 16:00 의 1시간 누적 차분 → 구간별 순매수 (억원)."""
    day = df_cum["dt"].iloc[0].normalize()
    open_dt = day + pd.Timedelta(hours=9)
    # 0 prepend
    zero = pd.DataFrame({"dt": [open_dt - pd.Timedelta(seconds=1)],
                          "indiv_cum": [0.0], "foreign_cum": [0.0], "inst_cum": [0.0]})
    df = pd.concat([zero, df_cum], ignore_index=True).sort_values("dt").reset_index(drop=True)
    hours = pd.date_range(open_dt, day + pd.Timedelta(hours=16), freq="1h")
    rows = []
    for h in hours:
        sub = df[df["dt"] <= h]
        if sub.empty:
            continue
        prev = sub.iloc[-1]
        rows.append({"hour": h, "indiv_cum": prev["indiv_cum"],
                      "foreign_cum": prev["foreign_cum"], "inst_cum": prev["inst_cum"]})
    out = pd.DataFrame(rows)
    out["indiv"] = out["indiv_cum"].diff().fillna(out["indiv_cum"]) / 1e8
    out["foreign"] = out["foreign_cum"].diff().fillna(out["foreign_cum"]) / 1e8
    out["inst"] = out["inst_cum"].diff().fillna(out["inst_cum"]) / 1e8
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    # 종목 분봉
    stock_hours = {}
    for name, code in STOCKS.items():
        print(f"[fetch] {name} ({code}) ...")
        df_min = fetch_stock_minute(code)
        stock_hours[name] = hourly_stock(df_min)
        print(f"  {len(df_min)} min bars, open {df_min['close'].iloc[0]:,.0f} → close {df_min['close'].iloc[-1]:,.0f} ({(df_min['close'].iloc[-1]/df_min['close'].iloc[0]-1)*100:+.2f}%)")

    print("\n[fetch] KOSPI market intraday investor (Daum) ...")
    df_inv = fetch_daum_market_times("KOSPI")
    mh = hourly_market_diff(df_inv)
    # 첫 09:00 행 (=0) 제거
    mh = mh.iloc[1:].reset_index(drop=True)

    # 합성 표 (시간대 종료점 기준)
    rows = []
    for _, m in mh.iterrows():
        h = m["hour"]
        row = {"시간": h.strftime("%H:%M")}
        for name in STOCKS:
            sh = stock_hours[name]
            if h in sh.index:
                r = sh.loc[h]
                row[f"{name} 종가"] = f"{r['close']:,.0f}"
                row[f"{name} 구간%"] = f"{r['ret_pct']:+.2f}"
                row[f"{name} 거래대금(억)"] = f"{r['amount_M']:,.0f}"
            else:
                row[f"{name} 종가"] = "-"
                row[f"{name} 구간%"] = "-"
                row[f"{name} 거래대금(억)"] = "-"
        row["시장 개인(억)"] = f"{m['indiv']:+,.0f}"
        row["시장 외인(억)"] = f"{m['foreign']:+,.0f}"
        row["시장 기관(억)"] = f"{m['inst']:+,.0f}"
        rows.append(row)
    df_out = pd.DataFrame(rows)

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 250)
    print("\n=== KOSPI 2026-06-08 시간대별 가격 + 시장 투자자 동향 ===")
    print(df_out.to_string(index=False))

    # 종목 일별 합계 (오늘) — Daum 종목별 일별 endpoint 시도 X (KRX 막힘),
    # 대신 단순 시장 보조용으로 분봉 누적값 출력
    print("\n주의: 종목별 (삼전/하이닉스) 시간대별 투자자별 매매 동향은 무료 API 부재.")
    print("      종목 분리값은 broker API (KIS/키움) 필요.")
    print("      위 표의 시장 외인/기관/개인 컬럼은 KOSPI 전체 (Daum 출처).")


if __name__ == "__main__":
    main()
