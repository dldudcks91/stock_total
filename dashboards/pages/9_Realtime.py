"""Realtime dashboard page (stub).

TODO: 실시간 수집기 DB 연결 (외부 cron이 채우는 DB 읽기 전용)
    - 데이터 출처: 별도 프로젝트 `crypto_realtime_collector` 의 DB
    - 이 앱은 그 DB를 읽기만 하며, 쓰기/스케줄링은 절대 하지 않음
    - 예상 화면: 최근 N분 가격, 미체결 시그널, 최근 알림 로그
"""
from __future__ import annotations


def main() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="Realtime — Crypto",
        page_icon="🛰️",
        layout="wide",
    )
    st.title("Realtime Dashboard")
    st.info("Coming soon — 실시간 수집기 DB 연결 후 구현")
    st.caption(
        "이 페이지는 외부 `crypto_realtime_collector` 가 채우는 DB를 "
        "읽기 전용으로 표시할 예정입니다."
    )


main()
