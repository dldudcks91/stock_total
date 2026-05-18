"""마지막으로 알림 보낸 추천 종목 set 영속화.

파일 위치: ``data/alerts/last_seen_{asset}.json``
형식:
    {
      "anchor_ms": 1747400000000,
      "symbols": {"005930": "추격d", "000660": "수렴d", ...}
    }

`symbols` 는 {symbol: rec_label} dict — 추후 라벨 변경 알림 모드를 켜고 싶을 때
바로 활용할 수 있게 라벨을 같이 저장한다. 현재 정책 (신규 진입만) 에서는 키 집합
(symbols.keys()) 만 비교한다.

``anchor_ms`` 는 마지막 실행 시점의 anchor (`_recs.parquet` 와는 별개 — 단순 기록용).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[1]
_STATE_DIR = _ROOT / "data" / "alerts"


def _state_path(asset: str) -> Path:
    return _STATE_DIR / f"last_seen_{asset}.json"


def load_last_seen(asset: str) -> dict:
    """{symbol: rec_label} dict 반환. 파일 없거나 파싱 실패 시 빈 dict."""
    p = _state_path(asset)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        symbols = data.get("symbols")
        if isinstance(symbols, dict):
            return {str(k): str(v) for k, v in symbols.items()}
        return {}
    except Exception:
        return {}


def save_last_seen(asset: str, symbols: dict, anchor_ms: Optional[int] = None) -> None:
    """현재 추천 종목 set 을 디스크에 기록. ``symbols`` = {symbol: rec_label}."""
    p = _state_path(asset)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "anchor_ms": int(anchor_ms) if anchor_ms is not None else None,
        "symbols": dict(symbols),
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
