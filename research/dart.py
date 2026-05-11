"""DART OpenAPI 클라이언트 — 분기 재무제표 + 사업보고서 데이터.

사전 준비: 프로젝트 루트의 `.env` 에 `DART_API_KEY=...` 1줄.
.gitignore 에 `.env` 등록되어 있어야 함.

주요 엔드포인트:
- corpCode.xml: 6자리 종목코드 → 8자리 DART corp_code 매핑 (zip)
- fnlttSinglAcntAll.json: 단일회사 전체 재무제표 (계정 다수)
- fnlttSinglAcnt.json: 단일회사 주요계정 (매출액·영업이익·순이익 핵심)

⚠️ 분기 데이터 reprt_code (5자리 — 4자리로 호출 시 API 가 조용히 연간으로 폴백):
- 11013 = 1분기보고서 (3월 누적, Q1)
- 11012 = 반기보고서 (6월 누적, 1H)
- 11014 = 3분기보고서 (9월 누적, 3Q 누적)
- 11011 = 사업보고서 (12월 누적, 연간)

분기 단독 값(QoQ)이 필요하면 누적값 차분 필요.
"""
from __future__ import annotations

import io
import json
import os
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Optional, Dict, List

import requests

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache" / "dart"
CORP_CODE_CACHE = CACHE_DIR / "corpCode.xml"
BASE = "https://opendart.fss.or.kr/api"


def _load_env_key() -> Optional[str]:
    """프로젝트 루트의 .env 에서 DART_API_KEY 추출. python-dotenv 의존성 회피용."""
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DART_API_KEY"):
                _, _, val = line.partition("=")
                return val.strip().strip('"').strip("'")
    return os.getenv("DART_API_KEY")


def _api_key() -> str:
    k = _load_env_key()
    if not k:
        raise RuntimeError("DART_API_KEY missing — .env 또는 환경변수 확인")
    return k


def _corp_code_xml() -> bytes:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CORP_CODE_CACHE.exists():
        return CORP_CODE_CACHE.read_bytes()
    r = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": _api_key()}, timeout=30)
    r.raise_for_status()
    # 응답이 zip 임
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = next(n for n in z.namelist() if n.endswith(".xml"))
        xml_bytes = z.read(name)
    CORP_CODE_CACHE.write_bytes(xml_bytes)
    return xml_bytes


def get_corp_code(ticker: str) -> Optional[str]:
    """6자리 종목코드(stock_code) → 8자리 DART corp_code."""
    xml_bytes = _corp_code_xml()
    root = ET.fromstring(xml_bytes)
    for el in root.findall("list"):
        sc = el.findtext("stock_code", "").strip()
        if sc == ticker:
            return el.findtext("corp_code", "").strip()
    return None


REPRT_CODES = {"1Q": "11013", "2Q": "11012", "3Q": "11014", "4Q": "11011"}


def fetch_quarterly_main(ticker: str, year: int, quarter: str) -> List[Dict]:
    """fnlttSinglAcnt.json — 매출액·영업이익·순이익 등 주요 계정만.
    quarter ∈ {1Q,2Q,3Q,4Q}.
    ⚠️ DART thstrm_amount 동작: 1Q/반기/3Q 보고서는 **단독 분기 (3개월)** 값,
    사업보고서(4Q 매핑)만 **연간 12개월** 값. thstrm_dt 의 기간은 누적 범위로 표기되지만
    금액 자체는 당분기 값임. Q4 단독값은 별도 계산 필요(연간 - Q1 - Q2 - Q3)."""
    corp_code = get_corp_code(ticker)
    if corp_code is None:
        return []
    cache_path = CACHE_DIR / f"main_{ticker}_{year}_{quarter}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    time.sleep(0.5)
    r = requests.get(
        f"{BASE}/fnlttSinglAcnt.json",
        params={
            "crtfc_key": _api_key(),
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": REPRT_CODES[quarter],
        },
        timeout=20,
    )
    data = r.json() if r.status_code == 200 else {"status": "ERR"}
    items = data.get("list", []) if data.get("status") == "000" else []
    cache_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return items


def _to_int(s: str) -> Optional[int]:
    if not s:
        return None
    s = s.replace(",", "").strip()
    if not s or s == "-":
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return None


def parse_main_accounts(items: List[Dict]) -> Dict[str, Optional[int]]:
    """fnlttSinglAcnt 결과 → 매출액·영업이익·당기순이익 (당기 누적, 연결 우선)."""
    out = {"revenue": None, "op_profit": None, "net_income": None, "fs_div": None}
    target_names = {
        "revenue": ["매출액", "수익(매출액)", "영업수익"],
        "op_profit": ["영업이익", "영업이익(손실)"],
        "net_income": ["당기순이익", "당기순이익(손실)", "분기순이익"],
    }
    # 연결재무제표(CFS) 우선
    for fs_div in ("CFS", "OFS"):
        for key, names in target_names.items():
            if out[key] is not None:
                continue
            for it in items:
                if it.get("fs_div") != fs_div:
                    continue
                if it.get("account_nm") in names:
                    val = _to_int(it.get("thstrm_amount"))
                    if val is not None:
                        out[key] = val
                        if out["fs_div"] is None:
                            out["fs_div"] = fs_div
                        break
        if all(out[k] is not None for k in ("revenue", "op_profit", "net_income")):
            break
    return out


def quarterly_series(ticker: str, last_n_quarters: int = 8) -> List[Dict]:
    """최근 N분기 단독값 반환.
    1Q/2Q/3Q 는 fnlttSinglAcnt 응답이 이미 단독 분기값. 4Q 만 연간 - Q1 - Q2 - Q3 로 계산.
    각 항목: {year, quarter, revenue, op_profit, net_income, fs_div}
    """
    from datetime import date

    today = date.today()
    candidates: List = []
    y = today.year
    q_now = (today.month - 1) // 3 + 1
    qy, qq = y, q_now
    for _ in range(last_n_quarters + 4):
        qq -= 1
        if qq <= 0:
            qq = 4
            qy -= 1
        candidates.append((qy, qq))

    raw_by_quarter: Dict = {}
    for (yr, q) in candidates:
        items = fetch_quarterly_main(ticker, yr, f"{q}Q")
        parsed = parse_main_accounts(items)
        if parsed["revenue"] is not None:
            raw_by_quarter[(yr, q)] = parsed

    out = []
    for (yr, q), raw in sorted(raw_by_quarter.items()):
        if q < 4:
            single = dict(raw)
        else:
            # Q4 = 연간 - Q1 - Q2 - Q3
            q1 = raw_by_quarter.get((yr, 1))
            q2 = raw_by_quarter.get((yr, 2))
            q3 = raw_by_quarter.get((yr, 3))
            if not (q1 and q2 and q3):
                continue
            def _diff(a, b1, b2, b3):
                if a is None or any(b is None for b in (b1, b2, b3)):
                    return None
                return a - b1 - b2 - b3
            single = {
                "revenue": _diff(raw["revenue"], q1["revenue"], q2["revenue"], q3["revenue"]),
                "op_profit": _diff(raw["op_profit"], q1["op_profit"], q2["op_profit"], q3["op_profit"]),
                "net_income": _diff(raw["net_income"], q1["net_income"], q2["net_income"], q3["net_income"]),
                "fs_div": raw["fs_div"],
            }
        out.append({"year": yr, "quarter": q, **single})

    return out[-last_n_quarters:]


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ticker = sys.argv[1] if len(sys.argv) > 1 else "005930"
    cc = get_corp_code(ticker)
    print(f"corp_code({ticker}) = {cc}")
    series = quarterly_series(ticker, last_n_quarters=8)
    print(f"분기별 단독 값 (단위: 원, 연결={series[0]['fs_div'] if series else '?'})")
    print(f"{'분기':<10}{'매출':>20}{'영업이익':>20}{'순이익':>20}")
    for s in series:
        rev = f"{s['revenue']:,}" if s.get("revenue") else "—"
        op = f"{s['op_profit']:,}" if s.get("op_profit") is not None else "—"
        ni = f"{s['net_income']:,}" if s.get("net_income") is not None else "—"
        print(f"{s['year']}-{s['quarter']}Q   {rev:>20}{op:>20}{ni:>20}")
