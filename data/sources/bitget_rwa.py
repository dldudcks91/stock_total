"""Bitget USDT-M 의 RWA(Real World Asset) 심볼 목록 캐시.

RWA = 토큰화 주식 / ETF / 원자재 (AAPLUSDT, QQQUSDT, COPPERUSDT 등). Bitget 의
`contracts` API 가 각 종목에 `isRwa: YES/NO` 플래그를 제공 — 이걸 사용해 추천 시그널에서
RWA 토큰을 자동 제외하는 블랙리스트로 활용.

기존 hardcoded STOCK_TOKENS(19개) 대비 장점:
  - 자동 동기화 (신규 RWA 상장 시 다음 갱신에 자동 반영)
  - 정확도 (현재 108개 정확 식별 vs 19개 manual)
  - 카테고리 무관 (개별 주식, ETF, 원자재, 금속 다 포함)

캐시 파일: `data/cache/crypto/_rwa_symbols.json`
형식:
    {
      "updated_at": "2026-05-27T13:00:00+00:00",
      "source": "bitget v2 contracts API (productType=usdt-futures, isRwa=YES)",
      "count": 108,
      "symbols": ["AAPLUSDT", "AMDUSDT", ...]
    }

CLI:
    .venv/Scripts/python.exe -m data.sources.bitget_rwa            # 갱신
    .venv/Scripts/python.exe -m data.sources.bitget_rwa --print    # 캐시 내용 출력

크립토 추천 코드에서:
    from data.sources.bitget_rwa import load_rwa_cache
    rwa = load_rwa_cache()   # set[str], 캐시 없으면 빈 set
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "data" / "cache" / "crypto" / "_rwa_symbols.json"
API_URL = "https://api.bitget.com/api/v2/mix/market/contracts"


def fetch_rwa_symbols(timeout: int = 10) -> list[str]:
    """Bitget contracts API 호출 → isRwa==YES 인 symbol 리스트."""
    r = requests.get(API_URL, params={"productType": "usdt-futures"}, timeout=timeout)
    r.raise_for_status()
    contracts = r.json().get("data", [])
    return sorted(c["symbol"] for c in contracts if c.get("isRwa") == "YES")


def save_rwa_cache(path: Optional[Path] = None) -> dict:
    """API 호출 → JSON 으로 저장. 반환 = 저장된 dict."""
    path = path or CACHE_PATH
    syms = fetch_rwa_symbols()
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "bitget v2 contracts API (productType=usdt-futures, isRwa=YES)",
        "count": len(syms),
        "symbols": syms,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def load_rwa_cache(path: Optional[Path] = None) -> set[str]:
    """캐시 읽기 → set. 캐시 없으면 빈 set (경고 출력 X — 호출쪽에서 처리)."""
    path = path or CACHE_PATH
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("symbols", []))
    except Exception:
        return set()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", help="저장된 캐시 출력 (갱신 X)")
    args = ap.parse_args()

    if args.print:
        if not CACHE_PATH.exists():
            print(f"캐시 없음: {CACHE_PATH}")
            return
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        print(f"updated_at: {data['updated_at']}")
        print(f"count     : {data['count']}")
        print(f"symbols   :")
        for s in data["symbols"]:
            print(f"  {s}")
        return

    print(f"Fetching RWA symbols from Bitget ...")
    payload = save_rwa_cache()
    print(f"  count = {payload['count']}")
    print(f"  saved → {CACHE_PATH}")


if __name__ == "__main__":
    main()
