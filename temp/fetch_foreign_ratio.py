"""KOSPI 외국인 보유 비중 — 시총 상위 종목 시계열로 근사.

KRX 직접 시계열이 환경에서 막혀있어, 네이버 종목별 외인 일별 매매 페이지
(https://finance.naver.com/item/frgn.naver?code=XXX) 에서 외인 보유율 시계열을
크롤해 시총 가중평균으로 코스피 외인 비중을 근사한다.

대상 종목 (코스피 시총 상위, 합산 시총 ~40%):
- 005930 삼성전자
- 000660 SK하이닉스
- 373220 LG에너지솔루션
- 207940 삼성바이오로직스
- 005380 현대차
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import bs4
import pandas as pd
import requests

sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = Path(__file__).parent

# 대상 종목 + 시총 가중치 (2026.05 추정, 합산이 100% 가 아니어도 정규화)
TICKERS = {
    "005930": ("삼성전자", 1633),     # 시총 1633조원
    "000660": ("SK하이닉스", 800),    # 800조 (가정)
    "373220": ("LG에너지솔루션", 250),
    "207940": ("삼성바이오", 200),
    "005380": ("현대차", 150),
}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"}


def fetch_ticker(code: str, pages: int = 8) -> pd.DataFrame:
    """네이버 종목 외인 일별 표 페이지네이션."""
    rows = []
    for page in range(1, pages + 1):
        url = f"https://finance.naver.com/item/frgn.naver?code={code}&page={page}"
        r = requests.get(url, headers=HEADERS, timeout=15)
        html = r.content.decode("euc-kr", errors="replace")
        soup = bs4.BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        if len(tables) < 4:
            break
        t = tables[3]
        for tr in t.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all("td")]
            if len(cells) >= 9 and len(cells[0]) == 10 and cells[0][4] == "." and cells[0][7] == ".":
                # cells: [날짜, 종가, 전일비, 등락률, 거래량, 기관순매매, 외인순매매, 보유주식수, 보유율]
                rows.append({
                    "date": cells[0],
                    "close": cells[1],
                    "fx_net": cells[6],
                    "fx_holding_shares": cells[7],
                    "fx_ratio_pct": cells[8],
                })
        time.sleep(0.3)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], format="%Y.%m.%d")
    df["close"] = df["close"].str.replace(",", "").astype("int64")
    df["fx_ratio_pct"] = df["fx_ratio_pct"].str.replace("%", "").astype("float64")
    df["fx_holding_shares"] = df["fx_holding_shares"].str.replace(",", "").astype("int64")
    df["fx_net"] = df["fx_net"].str.replace(",", "").str.replace("+", "").astype("int64")
    df = df.set_index("date").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df


# === 수집 ===
print("수집 중...")
data = {}
for code, (name, mcap) in TICKERS.items():
    print(f"  {code} {name} ({mcap}조)... ", end="", flush=True)
    try:
        df = fetch_ticker(code, pages=8)
        if df.empty:
            print("FAIL (empty)")
            continue
        print(f"{len(df)} 행, {df.index.min().date()} ~ {df.index.max().date()}, 현재 외인 {df['fx_ratio_pct'].iloc[-1]:.2f}%")
        data[code] = df
    except Exception as e:
        print(f"ERR: {e}")

# === 시총 가중 평균 ===
ratios = pd.DataFrame({code: d["fx_ratio_pct"] for code, d in data.items()})
weights = pd.Series({code: TICKERS[code][1] for code in data}, dtype=float)
weights = weights / weights.sum()
print()
print(f"가중치 (정규화):")
for code, w in weights.items():
    print(f"  {TICKERS[code][0]:<18s}: {w*100:.1f}%")
print()

ratios_aligned = ratios.dropna(how="any")
weighted = (ratios_aligned * weights).sum(axis=1)
weighted = weighted.sort_index()

result = ratios_aligned.copy()
result["가중평균_외인비중_%"] = weighted.round(2)
result.columns = [TICKERS[c][0] if c in TICKERS else c for c in result.columns[:-1]] + ["가중평균_외인비중_%"]

# === 저장 ===
csv_path = OUT_DIR / "kospi_foreign_ratio_proxy.csv"
parquet_path = OUT_DIR / "kospi_foreign_ratio_proxy.parquet"
result.to_csv(csv_path, encoding="utf-8-sig")
result.to_parquet(parquet_path)

print(f"shape: {result.shape}  range: {result.index.min().date()} ~ {result.index.max().date()}")
print(f"saved: {csv_path}")
print(f"saved: {parquet_path}")
print()
print("=== HEAD (5) ===")
print(result.head().to_string())
print()
print("=== TAIL (5) ===")
print(result.tail().to_string())

# 변화량 요약
first = result["가중평균_외인비중_%"].iloc[0]
last = result["가중평균_외인비중_%"].iloc[-1]
peak = result["가중평균_외인비중_%"].max()
trough = result["가중평균_외인비중_%"].min()
print()
print("=" * 60)
print("[요약] 시총 상위 종목 가중평균 외인 비중")
print("=" * 60)
print(f"  시작 ({result.index[0].date()}): {first:.2f}%")
print(f"  종료 ({result.index[-1].date()}): {last:.2f}%")
print(f"  변화        : {last - first:+.2f}%p")
print(f"  최고        : {peak:.2f}%  ({result['가중평균_외인비중_%'].idxmax().date()})")
print(f"  최저        : {trough:.2f}%  ({result['가중평균_외인비중_%'].idxmin().date()})")
