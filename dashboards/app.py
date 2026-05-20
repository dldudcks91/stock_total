"""Multi-page Streamlit dashboard entry point.

Run with (ALWAYS use the project .venv — do NOT use global / anaconda streamlit,
mismatched pandas versions break resample("ME") and other 2.2+ APIs):
    .venv/Scripts/streamlit.exe run dashboards/app.py

Pages live in `dashboards/pages/` and are auto-discovered by Streamlit. The
home page just shows a quick page index and routes the user to the relevant
page from the sidebar.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root (parent of `dashboards/`) is on sys.path so
# `from dashboards._lib import ...` works under `streamlit run`.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboards._lib import render_fetch_log_sidebar


def main() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="Research Dashboards",
        page_icon="📊",
        layout="wide",
    )
    st.title("Research Dashboards")
    st.caption(
        "왼쪽 사이드바에서 페이지를 선택하세요."
    )
    render_fetch_log_sidebar(st)

    st.markdown(
        "- **Bitget** — Bitget USDT-M 전 종목 라이브 표 (REST 직접 폴링)\n"
        "- **KOSPI** — 시총 상위 KOSPI 종목 라이브 표 (Naver 비공식)\n"
        "- **NASDAQ** — 캐시된 NASDAQ 심볼 라이브 표 (Naver 비공식)\n"
        "- **Mobile** — 모바일 친화 카드 리스트 (Bitget 앱 스타일)\n"
    )


if __name__ == "__main__":
    main()
