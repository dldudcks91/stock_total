"""KOSPI 과열 지표 수집 — 신용잔고 + 예탁금 + 거래대금 + 시총/GDP.

소스:
- 신용잔고/예탁금: 네이버 sise_deposit (페이지네이션)
- 거래대금/시총: kospi_10yr_daily.parquet 에 이미 있음
- GDP: 한국 명목 GDP 연간 (한국은행 ECOS 공식, 하드코딩)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List

import bs4
import pandas as pd
import requests

sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = Path(__file__).parent
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0",
           "Referer": "https://finance.naver.com/"}

# ===== 한국 명목 GDP (연간, 한국은행 ECOS 기준) =====
GDP_KRW_TRILLION = {
    2016: 1742, 2017: 1836, 2018: 1898, 2019: 1924,
    2020: 1941, 2021: 2072, 2022: 2162, 2023: 2236,
    2024: 2300,        # 추정 (2024년 4분기 합계, 한은 잠정치 기준)
    2025: 2380,        # 추정 (2025년 GDP, 잠정)
    2026: 2470,        # 추정 (2026년 GDP, 잠정)
}


def fetch_deposit_page(page: int) -> pd.DataFrame:
    """네이버 시장 자금 페이지 1장 — 약 20영업일."""
    r = requests.get(
        "https://finance.naver.com/sise/sise_deposit.naver",
        params={"page": page}, headers=HEADERS, timeout=15,
    )
    html = r.content.decode("euc-kr", errors="replace")
    soup = bs4.BeautifulSoup(html, "html.parser")
    t = soup.find_all("table")[0]
    rows = []
    for tr in t.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all("td")]
        # 데이터 row: [날짜, 예탁금, 예탁금증감, 신용잔고, 신용증감, 펀드_주식, ..., ...]
        if len(cells) >= 4 and len(cells[0]) == 8 and cells[0][2] == "." and cells[0][5] == ".":
            try:
                d = pd.to_datetime("20" + cells[0], format="%Y.%m.%d")
                deposit = int(cells[1].replace(",", ""))  # 투자자예탁금 (억원)
                credit = int(cells[3].replace(",", ""))   # 신용잔고 (억원)
                rows.append({"date": d, "예탁금_억": deposit, "신용잔고_억": credit})
            except Exception:
                continue
    return pd.DataFrame(rows)


print("[1] 신용잔고 + 예탁금 (네이버) — 페이지네이션...")
frames: List[pd.DataFrame] = []
start_ts = pd.to_datetime("2016-01-01")
for page in range(1, 200):
    try:
        df = fetch_deposit_page(page)
    except Exception as e:
        print(f"  page {page} ERR: {e}")
        time.sleep(2.0)
        continue
    if df.empty:
        break
    frames.append(df)
    oldest = df["date"].min()
    if oldest <= start_ts:
        break
    if page % 20 == 0:
        print(f"  {page} 페이지, oldest = {oldest.date()}")
    time.sleep(0.25)

deposit = pd.concat(frames).set_index("date").sort_index()
deposit = deposit[~deposit.index.duplicated(keep="first")]
deposit = deposit.loc[deposit.index >= start_ts]
print(f"  done: {deposit.shape}, {deposit.index.min().date()} ~ {deposit.index.max().date()}")

# ===== 기존 10년 데이터 + GDP 결합 =====
print("\n[2] 결합...")
daily = pd.read_parquet(OUT_DIR / "kospi_10yr_daily.parquet")
# FDR Amount는 daily에 안 들어가 있을 수 있음 — 다시 가져오기
import FinanceDataReader as fdr
kospi = fdr.DataReader("KS11", "2016-01-01", "2026-05-13")
daily["KOSPI_amount_조"] = (kospi["Amount"] / 1e12).reindex(daily.index)
daily["GDP_조"] = daily.index.year.map(GDP_KRW_TRILLION).astype(float)
daily["시총GDP_%"] = (daily["KOSPI_marcap"] / 1e12 / daily["GDP_조"] * 100)
daily["신용잔고_억"] = deposit["신용잔고_억"]
daily["예탁금_억"] = deposit["예탁금_억"]

# 주별 (금요일)
weekly = pd.DataFrame()
weekly["KOSPI"] = daily["KOSPI_close"].resample("W-FRI").last()
weekly["시총_조"] = (daily["KOSPI_marcap"] / 1e12).resample("W-FRI").last()
weekly["GDP_조"] = daily["GDP_조"].resample("W-FRI").last()
weekly["시총GDP_%"] = daily["시총GDP_%"].resample("W-FRI").last()
weekly["거래대금_주간_조"] = daily["KOSPI_amount_조"].resample("W-FRI").sum()
weekly["거래대금_일평균_조"] = daily["KOSPI_amount_조"].resample("W-FRI").mean()
weekly["신용잔고_조"] = (deposit["신용잔고_억"] / 10000).resample("W-FRI").last()
weekly["예탁금_조"] = (deposit["예탁금_억"] / 10000).resample("W-FRI").last()
weekly["외인비중_%"] = daily["삼성전자_외인비중_%"].resample("W-FRI").last()
weekly = weekly.dropna(subset=["KOSPI"])

weekly.to_parquet(OUT_DIR / "kospi_overheating_weekly.parquet")
weekly.to_csv(OUT_DIR / "kospi_overheating_weekly.csv", encoding="utf-8-sig")
print(f"saved weekly: {weekly.shape}")

print()
print("=== TAIL (10주) ===")
print(weekly.tail(10).round(2).to_string())
