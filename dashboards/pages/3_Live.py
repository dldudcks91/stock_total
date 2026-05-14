"""Live ticker dashboard — Bitget / KOSPI / NASDAQ in one tabbed page.

Replaces the previous one-page-per-market layout
(``3_Bitget.py`` / ``4_KOSPI.py`` / ``5_NASDAQ.py``). Routing the three markets
through ``st.tabs`` keeps each market's AgGrid component mounted across tab
switches — Streamlit renders all tab panes into the DOM and only toggles
visibility via CSS when the user clicks a tab, so the iframe-remount cost of
navigating between separate pages goes away.

The actual market views live in ``dashboards/live/{bitget,kospi,nasdaq}.py``;
this page is just the assembly point.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboards._lib import render_fetch_log_sidebar  # noqa: E402
from dashboards.live import bitget, kospi, nasdaq  # noqa: E402


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Live", page_icon="📡", layout="wide")

    # Shared sidebar: last-fetch timestamps for all three markets.
    # Per-market controls (snapshot age + 라이브 가격 갱신 + 데이터 받기 buttons)
    # live in the tab body so they're contextual to the active tab.
    render_fetch_log_sidebar(st)

    tab_bitget, tab_kospi, tab_nasdaq = st.tabs(["📡 Bitget", "🇰🇷 KOSPI", "🇺🇸 NASDAQ"])
    with tab_bitget:
        bitget.render(st)
    with tab_kospi:
        kospi.render(st)
    with tab_nasdaq:
        nasdaq.render(st)


main()
