"""업종 분류 + 동종 업종 피어 추출. KSIC(한국표준산업분류) 기반.

⚠️ KSIC 분류는 단일 사업 회사(SK하이닉스=반도체)엔 정확하지만,
다각화 기업(삼성전자=통신/방송 장비, 메모리·가전·디스플레이 다 묶임)엔 피어가 부정확.
다각화 기업의 경우 manual peer override 사용을 권장한다.
"""
from __future__ import annotations

from typing import List, Dict, Optional
import FinanceDataReader as fdr

# 다각화 기업 수동 피어 오버라이드 (실제 비즈니스 모델 기반)
MANUAL_PEERS: Dict[str, List[str]] = {
    "005930": ["000660", "066570", "011070"],  # 삼성전자 → SK하이닉스, LG전자, LG이노텍 (사업부별 비교)
}


def _krx_desc():
    """KRX-DESC + Marcap 결합. 호출당 1회 캐시 안 함 (FDR 자체 캐시 사용)."""
    desc = fdr.StockListing("KRX-DESC")
    mc = fdr.StockListing("KRX")[["Code", "Marcap"]]
    return desc.merge(mc, on="Code")


def get_company_info(ticker: str) -> Dict:
    df = _krx_desc()
    row = df[df["Code"] == ticker]
    if row.empty:
        return {"ticker": ticker, "found": False}
    r = row.iloc[0]
    return {
        "ticker": ticker,
        "name": r["Name"],
        "market": r["Market"],
        "sector": r["Sector"] if not _isnan(r["Sector"]) else None,
        "industry_ksic": r["Industry"] if not _isnan(r["Industry"]) else None,
        "products": r["Products"] if not _isnan(r["Products"]) else None,
        "listing_date": str(r["ListingDate"])[:10] if r["ListingDate"] else None,
        "settle_month": r["SettleMonth"] if not _isnan(r["SettleMonth"]) else None,
        "representative": r["Representative"] if not _isnan(r["Representative"]) else None,
        "homepage": r["HomePage"] if not _isnan(r["HomePage"]) else None,
        "region": r["Region"] if not _isnan(r["Region"]) else None,
        "marcap": int(r["Marcap"]) if r["Marcap"] else None,
        "found": True,
    }


def _isnan(x):
    try:
        import math
        return isinstance(x, float) and math.isnan(x)
    except Exception:
        return False


def get_peers(ticker: str, n: int = 5, use_manual: bool = True) -> List[Dict]:
    """동종 업종 피어 N개. manual override 우선, 없으면 KSIC 기준."""
    df = _krx_desc()

    if use_manual and ticker in MANUAL_PEERS:
        peer_codes = MANUAL_PEERS[ticker]
        rows = df[df["Code"].isin(peer_codes)].sort_values("Marcap", ascending=False)
        source = "manual_override"
    else:
        target = df[df["Code"] == ticker]
        if target.empty:
            return []
        industry = target.iloc[0]["Industry"]
        if _isnan(industry):
            return []
        rows = (
            df[(df["Industry"] == industry) & (df["Code"] != ticker)]
            .sort_values("Marcap", ascending=False)
            .head(n)
        )
        source = f"KSIC: {industry}"

    return [
        {
            "code": r["Code"],
            "name": r["Name"],
            "market": r["Market"],
            "marcap": int(r["Marcap"]),
            "_source": source,
        }
        for _, r in rows.iterrows()
    ]


def industry_brief(ticker: str) -> Dict:
    """리포트 2번 섹션(업황/업계 구조) 입력용 구조화 자료."""
    info = get_company_info(ticker)
    peers = get_peers(ticker)
    return {
        "company": info,
        "peers": peers,
        "notes": [
            "KSIC 분류는 다각화 기업에 부정확할 수 있음. 피어가 부적절해 보이면 MANUAL_PEERS 에 종목코드 직접 명시.",
            "업황 사이클·규제·정책은 본 모듈에서 다루지 않음 — WebSearch / 산업 리포트로 별도 보강 필요.",
        ],
    }


if __name__ == "__main__":
    import sys, json

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ticker = sys.argv[1] if len(sys.argv) > 1 else "005930"
    print(json.dumps(industry_brief(ticker), ensure_ascii=False, indent=2, default=str))
