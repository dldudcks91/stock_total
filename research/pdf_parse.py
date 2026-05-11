"""한경 컨센서스 PDF 다운로드 + 목표주가/투자의견 추출.

리스트 페이지에 PDF 링크가 `/analysis/downpdf?report_idx={N}` 형태로 노출됨.
PDF 1페이지 텍스트에서 정규식으로 추출. 모든 리포트가 목표주가를 표기하진 않음
(Issue Comment 등은 미표기). 실패 시 None 반환하고 진행.
"""
from __future__ import annotations

import re
import time
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict

import requests
import pypdf

PDF_URL = "https://consensus.hankyung.com/analysis/downpdf"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
PDF_CACHE = Path(__file__).resolve().parent / "cache" / "broker_reports" / "pdf"

# 정규식 — 한경 컨센서스 리포트 일반 패턴 기반
RE_TARGET = re.compile(r"목표주가[^\d\n]{0,20}([\d,]{4,})\s*원")
RE_TARGET_ALT = re.compile(r"적정주가[^\d\n]{0,20}([\d,]{4,})\s*원")
RE_OPINION = re.compile(r"\b(Buy|Hold|Sell|매수|중립|매도|시장수익률|Strong Buy|N/R)\b")


def _get_pdf_bytes(report_idx: str, use_cache: bool = True) -> Optional[bytes]:
    PDF_CACHE.mkdir(parents=True, exist_ok=True)
    cache_path = PDF_CACHE / f"{report_idx}.pdf"
    if use_cache and cache_path.exists():
        return cache_path.read_bytes()

    time.sleep(1.0)
    try:
        r = requests.get(PDF_URL, params={"report_idx": report_idx}, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except requests.RequestException:
        return None

    if "pdf" not in r.headers.get("Content-Type", "").lower():
        return None
    cache_path.write_bytes(r.content)
    return r.content


def extract_first_page_text(pdf_bytes: bytes) -> str:
    try:
        reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    except Exception:
        return ""
    if not reader.pages:
        return ""
    try:
        return reader.pages[0].extract_text() or ""
    except Exception:
        return ""


def parse_target_and_opinion(text: str) -> Dict[str, Optional[object]]:
    """페이지 텍스트에서 목표주가(int)와 투자의견(str) 추출."""
    target: Optional[int] = None
    m = RE_TARGET.search(text) or RE_TARGET_ALT.search(text)
    if m:
        try:
            target = int(m.group(1).replace(",", ""))
        except ValueError:
            target = None

    opinion: Optional[str] = None
    m2 = RE_OPINION.search(text)
    if m2:
        opinion = m2.group(1)

    return {"target_price": target, "opinion": opinion}


def fetch_target_for_report(report_idx: str) -> Dict[str, Optional[object]]:
    """report_idx 하나에 대해 PDF 받고 목표주가/투자의견 추출."""
    pdf = _get_pdf_bytes(report_idx)
    if pdf is None:
        return {"target_price": None, "opinion": None, "ok": False}
    text = extract_first_page_text(pdf)
    out = parse_target_and_opinion(text)
    out["ok"] = True
    return out


if __name__ == "__main__":
    import sys, json

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    idx = sys.argv[1] if len(sys.argv) > 1 else "648425"
    print(json.dumps(fetch_target_for_report(idx), ensure_ascii=False, indent=2))
