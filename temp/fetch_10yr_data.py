"""10년치 (2016~2026) KOSPI + 외국인 데이터 수집.

소스:
- KOSPI 지수: FinanceDataReader (KS11)
- 외국인 일별 순매수: 네이버 일별 투자자 매매동향 페이지네이션
- 외국인 보유비중: 삼성전자(시총 ~25%) 외인 비중을 단일 프록시로
  + KOSPI 시가총액 + 외인 누적 매도로 시장 전체 비중 변화 검산

저장:
- temp/kospi_10yr_weekly.parquet/csv (주별 합본)
- temp/kospi_10yr_daily.parquet (일별 raw)
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
START = "2016-01-01"
END = "2026-05-13"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"}

# ===== 1. KOSPI 지수 (FDR) =====
print("[1/3] KOSPI 지수 (FDR)...")
import FinanceDataReader as fdr
kospi = fdr.DataReader("KS11", START, END)
kospi.index.name = "date"
print(f"      {kospi.shape}, {kospi.index.min().date()} ~ {kospi.index.max().date()}")


# ===== 2. 외국인 일별 순매수 (네이버) =====
def fetch_flow_page(bizdate: str) -> pd.DataFrame:
    r = requests.get(
        "https://finance.naver.com/sise/investorDealTrendDay.naver",
        params={"bizdate": bizdate, "sosok": "01"},
        headers=HEADERS, timeout=15,
    )
    html = r.content.decode("euc-kr", errors="replace")
    soup = bs4.BeautifulSoup(html, "html.parser")
    t = soup.find_all("table")[0]
    rows = []
    for tr in t.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all("td")]
        if len(cells) >= 11 and len(cells[0]) == 8 and cells[0][2] == "." and cells[0][5] == ".":
            rows.append(cells[:11])
    if not rows:
        return pd.DataFrame()
    cols = ["date", "개인", "외국인", "기관계", "금융투자", "보험", "투신", "기타금융", "은행", "연기금등", "기타법인"]
    df = pd.DataFrame(rows, columns=cols)
    df["date"] = pd.to_datetime("20" + df["date"], format="%Y.%m.%d")
    for c in cols[1:]:
        df[c] = df[c].str.replace(",", "").astype("int64")
    return df.set_index("date").sort_index()


print("[2/3] 외국인 일별 매매동향 (네이버) — 페이지네이션...")
frames: List[pd.DataFrame] = []
bizdate = pd.to_datetime(END).strftime("%Y%m%d")
start_ts = pd.to_datetime(START)
seen_oldest = None
for page_n in range(300):  # 안전상한
    try:
        page = fetch_flow_page(bizdate)
    except Exception as e:
        print(f"      page {page_n+1} ERR: {e}, retry")
        time.sleep(2.0)
        try:
            page = fetch_flow_page(bizdate)
        except Exception:
            break
    if page.empty:
        break
    frames.append(page)
    oldest = page.index.min()
    if oldest <= start_ts:
        break
    if seen_oldest is not None and oldest >= seen_oldest:
        break
    seen_oldest = oldest
    bizdate = (oldest - pd.Timedelta(days=1)).strftime("%Y%m%d")
    if (page_n + 1) % 20 == 0:
        print(f"      {page_n+1} 페이지, 현재 oldest = {oldest.date()}")
    time.sleep(0.3)

flow = pd.concat(frames).sort_index()
flow = flow[~flow.index.duplicated(keep="first")]
flow = flow.loc[(flow.index >= start_ts) & (flow.index <= pd.to_datetime(END))]
print(f"      done: {flow.shape}, {flow.index.min().date()} ~ {flow.index.max().date()}")


# ===== 3. 삼성전자 외인 보유비중 (네이버 종목 페이지) =====
def fetch_samsung_page(page: int) -> pd.DataFrame:
    r = requests.get(
        "https://finance.naver.com/item/frgn.naver",
        params={"code": "005930", "page": page},
        headers=HEADERS, timeout=15,
    )
    html = r.content.decode("euc-kr", errors="replace")
    soup = bs4.BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if len(tables) < 4:
        return pd.DataFrame()
    t = tables[3]
    rows = []
    for tr in t.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all("td")]
        if len(cells) >= 9 and len(cells[0]) == 10 and cells[0][4] == "." and cells[0][7] == ".":
            rows.append({"date": cells[0], "fx_ratio": cells[8].replace("%", "")})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], format="%Y.%m.%d")
    df["fx_ratio"] = df["fx_ratio"].astype("float64")
    return df.set_index("date").sort_index()


print("[3/3] 삼성전자 외인 비중 (네이버) — 페이지네이션...")
sf_frames: List[pd.DataFrame] = []
for page_n in range(1, 140):
    try:
        page = fetch_samsung_page(page_n)
    except Exception as e:
        print(f"      page {page_n} ERR: {e}")
        time.sleep(2.0)
        continue
    if page.empty:
        break
    sf_frames.append(page)
    if page.index.min() <= start_ts:
        break
    if page_n % 20 == 0:
        print(f"      {page_n} 페이지, oldest = {page.index.min().date()}")
    time.sleep(0.25)

ratio = pd.concat(sf_frames).sort_index()
ratio = ratio[~ratio.index.duplicated(keep="first")]
ratio = ratio.loc[ratio.index >= start_ts]
print(f"      done: {ratio.shape}, {ratio.index.min().date()} ~ {ratio.index.max().date()}")


# ===== 통합 =====
print()
print("[merge] 일별 합본 + 주별 집계...")
daily = pd.DataFrame(index=pd.date_range(START, END, freq="D"))
daily["KOSPI_close"] = kospi["Close"].astype(float)
daily["KOSPI_marcap"] = kospi["MarCap"].astype(float)
daily["외국인_순매수_억"] = flow["외국인"].astype(float)
daily["개인_순매수_억"] = flow["개인"].astype(float)
daily["기관_순매수_억"] = flow["기관계"].astype(float)
daily["금융투자_순매수_억"] = flow["금융투자"].astype(float)
daily["삼성전자_외인비중_%"] = ratio["fx_ratio"]
daily = daily.dropna(how="all")

daily.to_parquet(OUT_DIR / "kospi_10yr_daily.parquet")
print(f"      saved daily: {len(daily)} 행")

# 주별 (금요일 종가)
weekly = pd.DataFrame()
weekly["KOSPI_close"] = daily["KOSPI_close"].resample("W-FRI").last()
weekly["KOSPI_marcap_조"] = (daily["KOSPI_marcap"].resample("W-FRI").last() / 1e12).round(1)
weekly["외인_주간_순매수_억"] = daily["외국인_순매수_억"].resample("W-FRI").sum()
weekly["개인_주간_순매수_억"] = daily["개인_순매수_억"].resample("W-FRI").sum()
weekly["기관_주간_순매수_억"] = daily["기관_순매수_억"].resample("W-FRI").sum()
weekly["금융투자_주간_순매수_억"] = daily["금융투자_순매수_억"].resample("W-FRI").sum()
weekly["외인_누적_조"] = (daily["외국인_순매수_억"].cumsum() / 10000).resample("W-FRI").last().round(1)
weekly["삼성전자_외인비중_%"] = daily["삼성전자_외인비중_%"].resample("W-FRI").last()
weekly = weekly.dropna(subset=["KOSPI_close"])

weekly.to_parquet(OUT_DIR / "kospi_10yr_weekly.parquet")
weekly.to_csv(OUT_DIR / "kospi_10yr_weekly.csv", encoding="utf-8-sig")
print(f"      saved weekly: {len(weekly)} 주")

print()
print("=" * 80)
print("HEAD (5)")
print("=" * 80)
print(weekly.head().round(2).to_string())
print()
print("=" * 80)
print("TAIL (5)")
print("=" * 80)
print(weekly.tail().round(2).to_string())
