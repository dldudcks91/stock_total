"""한경 컨센서스에서 종목별 리포트 메타데이터 수집.

목표주가는 PDF 본문 안이라 별도 단계 필요. 본 모듈은 리스트 페이지의
{작성일, 분류, 제목, 애널리스트, 증권사} 만 수집한다.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://consensus.hankyung.com/analysis/list"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
CACHE_DIR = Path(__file__).resolve().parent / "cache" / "broker_reports"


def _request(params: dict) -> str:
    time.sleep(1.0)  # 단시간 대량 요청 방지
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def _clean_title(raw: str, ticker: str) -> str:
    """한경 컨센서스 제목 셀: [잘린제목 + 종목명(코드) + 정상제목 + 정상제목] 패턴 정리.
    문자열 끝에서 길이 k 인 suffix 와 그 직전 k 글자가 같은 가장 긴 k 를 찾으면 그게 정상 제목."""
    s = raw.strip()
    s = re.sub(r"[가-힣A-Za-z0-9&·\-]+\(" + ticker + r"\)\s*", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    n = len(s)
    for k in range(n // 2, 1, -1):
        if s[-k:] == s[-2 * k : -k]:
            return s[-k:].strip()
    return s


_REPORT_IDX_RE = re.compile(r"report_idx=(\d+)")


def _extract_report_idx(tr) -> Optional[str]:
    for a in tr.find_all("a"):
        href = a.get("href", "")
        m = _REPORT_IDX_RE.search(href)
        if m:
            return m.group(1)
    return None


def _parse_list(html: str, ticker: str) -> List[Dict]:
    """리포트 리스트 테이블에서 행 추출."""
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict] = []

    table = soup.find("table")
    if table is None:
        return rows

    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        cells = [td.get_text(strip=True) for td in tds]
        rows.append(
            {
                "date": cells[0],
                "category": cells[1],
                "title": _clean_title(cells[2], ticker),
                "analyst": cells[3],
                "broker": cells[4],
                "report_idx": _extract_report_idx(tr),
            }
        )
    return rows


def fetch_reports(
    ticker: str,
    months: int = 3,
    pages: int = 20,
    use_cache: bool = True,
) -> List[Dict]:
    """종목코드 기준 최근 N개월 리포트 메타데이터 수집."""
    today = date.today()
    sdate = (today - timedelta(days=30 * months)).isoformat()
    edate = today.isoformat()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{ticker}_{sdate}_{edate}.json"
    if use_cache and cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    params = {
        "sdate": sdate,
        "edate": edate,
        "search_text": ticker,
        "search_type": 2,  # 종목명/코드 검색
        "pages": pages,
    }
    html = _request(params)
    rows = _parse_list(html, ticker)
    cache_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


def summarize(rows: List[Dict]) -> Dict:
    """리포트 메타데이터 → 컨센서스 골격."""
    brokers = {}
    for r in rows:
        brokers[r["broker"]] = brokers.get(r["broker"], 0) + 1

    return {
        "total_reports": len(rows),
        "broker_counts": dict(sorted(brokers.items(), key=lambda x: -x[1])),
        "date_range": {
            "from": rows[-1]["date"] if rows else None,
            "to": rows[0]["date"] if rows else None,
        },
        "recent_titles": [
            {"date": r["date"], "broker": r["broker"], "title": r["title"]}
            for r in rows[:10]
        ],
    }


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ticker = sys.argv[1] if len(sys.argv) > 1 else "005930"
    rows = fetch_reports(ticker, months=3)
    summary = summarize(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
