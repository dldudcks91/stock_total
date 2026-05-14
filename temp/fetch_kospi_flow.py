"""KOSPI 투자자별 매매동향 — 9주체 일별 (네이버 금융 크롤).

네이버 finance.naver.com/sise/investorDealTrendDay.naver 페이지가 일별 9주체
(개인 + 외국인 + 기관계 + 금융투자 + 보험 + 투신 + 기타금융 + 은행 + 연기금 + 기타법인)
값을 보여준다. KRX 정보데이터시스템 직접 호출이 환경에서 LOGOUT 되는 상황의 차선책.

페이지당 약 10영업일을 보여주므로 bizdate를 옮겨가며 페이지네이션하여 누적 수집.
단위: **억원** (네이버 표 표시 단위).
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
URL = "https://finance.naver.com/sise/investorDealTrendDay.naver"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0",
    "Referer": "https://finance.naver.com/",
}

# sosok=01 → KOSPI, sosok=02 → KOSDAQ
SOSOK_KOSPI = "01"

# 컬럼 라벨 (네이버 테이블 헤더가 cp949 디코딩 깨져서 직접 명시)
COLS = [
    "date",
    "개인",
    "외국인",
    "기관계",
    "금융투자",
    "보험",
    "투신",
    "기타금융",
    "은행",
    "연기금등",
    "기타법인",
]


def _fetch_page(bizdate: str, sosok: str = SOSOK_KOSPI) -> pd.DataFrame:
    """네이버 한 페이지(약 10영업일) 데이터를 DataFrame으로."""
    r = requests.get(
        URL,
        params={"bizdate": bizdate, "sosok": sosok},
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    html = r.content.decode("euc-kr", errors="replace")
    soup = bs4.BeautifulSoup(html, "html.parser")
    table = soup.find_all("table")[0]

    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all("td")]
        # 데이터 row 는 첫 셀이 'YY.MM.DD' 패턴
        if len(cells) >= 11 and len(cells[0]) == 8 and cells[0][2] == "." and cells[0][5] == ".":
            rows.append(cells[:11])

    df = pd.DataFrame(rows, columns=COLS)
    if df.empty:
        return df
    df["date"] = pd.to_datetime("20" + df["date"], format="%Y.%m.%d")
    for c in COLS[1:]:
        df[c] = df[c].str.replace(",", "", regex=False).astype("int64")
    return df.set_index("date").sort_index()


def fetch_range(start: str, end: str, sosok: str = SOSOK_KOSPI) -> pd.DataFrame:
    """[start, end] 기간을 페이지네이션해서 일별 9주체 데이터 수집.

    Args:
        start, end: YYYYMMDD
    """
    start_ts = pd.to_datetime(start)
    end_ts = pd.to_datetime(end)
    bizdate = end_ts.strftime("%Y%m%d")

    frames: List[pd.DataFrame] = []
    seen_oldest = None

    for _ in range(40):  # 안전 상한 (40 * 10일 ~ 400 영업일)
        page = _fetch_page(bizdate, sosok)
        if page.empty:
            break
        frames.append(page)

        oldest = page.index.min()
        if oldest <= start_ts:
            break
        if seen_oldest is not None and oldest >= seen_oldest:
            break  # 더 이상 진척 없음
        seen_oldest = oldest
        # 다음 페이지: 가장 오래된 날짜의 전날을 bizdate 로
        bizdate = (oldest - pd.Timedelta(days=1)).strftime("%Y%m%d")
        time.sleep(0.4)

    if not frames:
        return pd.DataFrame(columns=COLS[1:])

    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df = df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
    # 검산 컬럼: 기관계 vs 6개 하위 합
    df["기관_합산검산"] = df[["금융투자", "보험", "투신", "기타금융", "은행", "연기금등"]].sum(axis=1)
    df["기관_차이"] = df["기관계"] - df["기관_합산검산"]
    return df


if __name__ == "__main__":
    START = "20251113"
    END = "20260513"

    print(f"fetching KOSPI 9-actor daily flow: {START} ~ {END}")
    df = fetch_range(START, END)
    print(f"shape: {df.shape}  range: {df.index.min().date()} ~ {df.index.max().date()}")

    # 검산
    bad = df.loc[df["기관_차이"].abs() > 1]
    if not bad.empty:
        print(f"WARN: 기관계 검산 불일치 {len(bad)}일")
    else:
        print("OK: 기관계 = 6주체 합 (모든 날짜 검산 일치)")

    csv_path = OUT_DIR / "kospi_investor_flow.csv"
    parquet_path = OUT_DIR / "kospi_investor_flow.parquet"
    df.to_csv(csv_path, encoding="utf-8-sig")
    df.to_parquet(parquet_path)
    print(f"saved: {csv_path}")
    print(f"saved: {parquet_path}")
    print()
    print("=== TAIL (5) ===")
    print(df.tail().to_string())
    print()
    print("=== HEAD (5) ===")
    print(df.head().to_string())
