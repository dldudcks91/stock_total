"""Shared helpers for the Streamlit dashboards.

Pure / IO-only code lives here so that pages can `from dashboards._lib import ...`
without re-defining boilerplate. Streamlit & plotly imports stay inside the
page modules (so this file is safe to import in test or CLI contexts).
"""
from __future__ import annotations

import pandas as pd


# ---------------------------------------------------------------------------
# Sidebar: last-fetch ledger
# ---------------------------------------------------------------------------

def _fmt_age(updated_at: str) -> str:
    """ISO 시각을 'N분/시간/일 전' 짧은 표기로."""
    try:
        ts = pd.Timestamp(updated_at)
        if ts.tzinfo is None:
            ts = ts.tz_localize("Asia/Seoul")
        now = pd.Timestamp.now(tz="Asia/Seoul")
        delta_sec = (now - ts).total_seconds()
    except Exception:
        return ""
    if delta_sec < 0:
        return "방금"
    if delta_sec < 60:
        return f"{int(delta_sec)}초 전"
    if delta_sec < 3600:
        return f"{int(delta_sec // 60)}분 전"
    if delta_sec < 86400:
        return f"{int(delta_sec // 3600)}시간 전"
    return f"{int(delta_sec // 86400)}일 전"


def render_fetch_log_sidebar(st, *, embedded: bool = False) -> None:
    """사이드바에 Bitget / KOSPI / NASDAQ 의 마지막 fetch 시각을 한 줄씩 그린다.

    - ``embedded=False`` (기본): 호출자가 ``with st.sidebar:`` 밖에서 부를 때.
    - ``embedded=True``: 호출자가 이미 ``with st.sidebar:`` 안에 있을 때.
    """
    from data import fetch_log

    log = fetch_log.read()

    # 자산 → 후보 key 리스트 (가장 최근에 갱신된 key 를 채택).
    ASSET_KEYS: list[tuple[str, tuple[str, ...]]] = [
        ("Bitget", ("crypto_1h", "crypto_4h", "crypto_1d", "crypto_1w")),
        ("KOSPI", ("kr_1d",)),
        ("NASDAQ", ("us_1d",)),
    ]

    def _latest_ts(keys: tuple[str, ...]) -> str:
        latest = ""
        for k in keys:
            e = log.get(k) or {}
            ts = e.get("updated_at", "")
            if ts and ts > latest:
                latest = ts
        return latest

    target = st if embedded else st.sidebar
    target.markdown("**📥 마지막 데이터 수신**")
    for asset, keys in ASSET_KEYS:
        ts = _latest_ts(keys)
        if not ts:
            target.caption(f"{asset}: _기록 없음_")
            continue
        date_part = ts.split("T", 1)[0] if "T" in ts else ts
        short_ts = ts.split("T", 1)[1][:5] if "T" in ts else ""
        age = _fmt_age(ts)
        target.caption(f"{asset}: {date_part} {short_ts} ({age})")
