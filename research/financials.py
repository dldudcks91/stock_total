"""증권사 PDF 1페이지의 Financial Data 표에서 5개년 펀더멘털 추출.

증권사별로 포맷이 다양함:
- 컬럼 수: 4년 vs 5년 (직전 1~2년 + 추정 2~3년)
- 단위 표기 위치: "EPS (원)" 처럼 라벨 옆 / "(십억원) 2024 2025 ..." 처럼 헤더 별도
- 수치 구분자: 쉼표·점·소수점 혼재

→ 라벨별 라인을 찾아 그 라인의 모든 숫자 토큰 추출. 모든 리포트가 모든 항목을 표기하진 않음.
"""
from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict, List

import pypdf

PDF_CACHE = Path(__file__).resolve().parent / "cache" / "broker_reports" / "pdf"

# 추출할 라벨. 별칭은 동일 키로 매핑.
LABELS = {
    "revenue": ["매출액"],
    "op_profit": ["영업이익"],
    "net_income": ["순이익", "지배주주순이익", "당기순이익"],
    "eps": ["EPS"],
    "per": ["PER"],
    "pbr": ["PBR"],
    "roe": ["ROE"],
    "ebitda_margin": ["EBITDA 마진", "EBITDA마진"],
    "op_margin": ["영업이익률"],
    "ebitda": ["EBITDA"],
}

# Financial Data 표가 시작될 만한 위치 마커 (헤더에 있는 연도 패턴)
RE_YEAR_HEADER = re.compile(r"(20\d{2}E?\s+){2,}20\d{2}E?")

# 한 줄에서 숫자만 뽑기 (음수·쉼표·소수점 허용)
RE_NUM = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")


def _read_text(pdf_bytes: bytes, max_pages: int = 1) -> str:
    try:
        reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    except Exception:
        return ""
    pages = reader.pages[:max_pages]
    return "\n".join((p.extract_text() or "") for p in pages)


def _find_year_header(text: str) -> Optional[List[str]]:
    """헤더 라인에서 연도 리스트 추출 (예: ['2024','2025','2026E','2027E','2028E'])."""
    m = RE_YEAR_HEADER.search(text)
    if not m:
        return None
    line = m.group(0)
    return re.findall(r"20\d{2}E?", line)


def _extract_row_numbers(line: str) -> List[float]:
    nums = []
    for tok in RE_NUM.findall(line):
        try:
            nums.append(float(tok.replace(",", "")))
        except ValueError:
            pass
    return nums


def _alias_match_pattern(alias: str) -> re.Pattern:
    """알리아스 + 즉시 (괄호 단위) 또는 공백 + 숫자. 산문 라인 매칭 차단용."""
    return re.compile(rf"^{re.escape(alias)}\s*(?:\([^)]*\))?\s*-?\d")


def parse_financials_from_text(text: str) -> Dict:
    """텍스트 → {label_key: {year: value}} + raw."""
    years = _find_year_header(text)
    result: Dict[str, Dict[str, float]] = {}
    raw_rows: Dict[str, List[float]] = {}

    lines = text.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        matched_key = None
        for key, aliases in LABELS.items():
            if key in result:
                continue
            for alias in aliases:
                if _alias_match_pattern(alias).match(stripped):
                    nums = _extract_row_numbers(stripped[len(alias):])
                    if nums:
                        raw_rows[key] = nums
                        if years and len(nums) == len(years):
                            result[key] = dict(zip(years, nums))
                        elif years and len(nums) >= len(years):
                            result[key] = dict(zip(years, nums[-len(years):]))
                    matched_key = key
                    break
            if matched_key:
                break

    return {"years": years, "by_label": result, "raw_rows": raw_rows}


def parse_financials_from_pdf(report_idx: str) -> Dict:
    pdf_path = PDF_CACHE / f"{report_idx}.pdf"
    if not pdf_path.exists():
        return {"error": "pdf_not_cached"}
    text = _read_text(pdf_path.read_bytes(), max_pages=1)
    out = parse_financials_from_text(text)
    out["report_idx"] = report_idx
    return out


def aggregate_across_reports(report_idxs: List[str]) -> Dict:
    """여러 리포트의 펀더멘털 추정치를 라벨×연도 별로 중앙값/min/max 집계."""
    import statistics

    bucket: Dict[str, Dict[str, List[float]]] = {}  # label -> year -> [values]
    parsed_count = 0

    for idx in report_idxs:
        parsed = parse_financials_from_pdf(idx)
        if not parsed.get("by_label"):
            continue
        parsed_count += 1
        for label, year_map in parsed["by_label"].items():
            bucket.setdefault(label, {})
            for year, val in year_map.items():
                bucket[label].setdefault(year, []).append(val)

    summary = {}
    for label, year_map in bucket.items():
        summary[label] = {}
        for year, vals in year_map.items():
            summary[label][year] = {
                "n": len(vals),
                "median": statistics.median(vals),
                "min": min(vals),
                "max": max(vals),
            }

    return {"parsed_count": parsed_count, "n_input": len(report_idxs), "summary": summary}


if __name__ == "__main__":
    import sys, json

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    idx = sys.argv[1] if len(sys.argv) > 1 else "648425"
    print(json.dumps(parse_financials_from_pdf(idx), ensure_ascii=False, indent=2))
