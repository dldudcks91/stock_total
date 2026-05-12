"""Last-fetch ledger (`data/last_fetch.json`).

자산/주기별로 "마지막으로 페처를 돌린 시각" 만 작게 기록하는 단일 JSON.
사이드바에서 사용자가 "지금 캐시가 얼마나 신선한지" 한눈에 보기 위한 용도.

위치: 프로젝트 `data/last_fetch.json` (json 은 `.gitignore` 의 parquet/csv 룰에
걸리지 않으므로 git 에 올라간다 — 작은 파일이라 충돌 위험 적음).

Schema (flat):
    {
        "<key>": {"updated_at": "<KST ISO>", "n_symbols": <int|null>},
        ...
    }

Keys (현재 사용 중):
    crypto_1h, crypto_4h, crypto_1d, crypto_1w   ← Bitget
    kr_1d                                         ← FDR KOSPI
    us_1d                                         ← FDR NASDAQ

"현재 가격 데이터" = 1h (intraday)
"1d 데이터"       = 1d / 1w
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    _KST = ZoneInfo("Asia/Seoul")
except Exception:  # pragma: no cover — Python 3.9 미만 등
    _KST = None

LOG_PATH = Path(__file__).resolve().parent / "last_fetch.json"

# 카테고리 매핑 (사이드바 그루핑용).
CURRENT_PRICE_KEYS = ("crypto_1h", "crypto_4h")
DAILY_KEYS = ("crypto_1d", "crypto_1w", "kr_1d", "us_1d")

KEY_LABELS = {
    "crypto_1h": "Crypto 1H",
    "crypto_4h": "Crypto 4H",
    "crypto_1d": "Crypto 1D",
    "crypto_1w": "Crypto 1W",
    "kr_1d": "KOSPI 1D",
    "us_1d": "NASDAQ 1D",
}


def _now_kst_iso() -> str:
    if _KST is not None:
        return datetime.now(_KST).isoformat(timespec="seconds")
    return datetime.now().isoformat(timespec="seconds")


def read() -> dict:
    if not LOG_PATH.exists():
        return {}
    try:
        return json.loads(LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def mark(key: str, n_symbols: Optional[int] = None) -> None:
    """주어진 key 의 updated_at 을 지금(KST)으로 덮어쓴다."""
    data = read()
    entry = {"updated_at": _now_kst_iso()}
    if n_symbols is not None:
        entry["n_symbols"] = int(n_symbols)
    data[key] = entry
    LOG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
