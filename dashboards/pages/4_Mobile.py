"""Mobile-friendly live tickers — Bitget app style.

Single-column compact card list with sort presets (Volume / Gainers / Losers /
Funding). Designed for phone browsers: ``layout="centered"``, larger touch
targets, no heavy computation (no candles), auto-refresh via ``st.fragment``.

Source: same Bitget public REST endpoint as the desktop Tickers page; uses
its own ticker cache so the two pages don't fight.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BITGET_TICKERS_URL = "https://api.bitget.com/api/v2/mix/market/tickers"
PRODUCT_TYPE = "USDT-FUTURES"

NUMERIC_COLS = [
    "lastPr", "askPr", "bidPr", "bidSz", "askSz",
    "high24h", "low24h", "ts", "change24h", "baseVolume",
    "quoteVolume", "usdtVolume", "openUtc", "changeUtc24h",
    "indexPrice", "fundingRate", "holdingAmount",
    "open24h", "markPrice",
]

UP_COLOR = "#2A9D8F"
DOWN_COLOR = "#E63946"
FLAT_COLOR = "#888888"


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_tickers(timeout: float = 10.0) -> pd.DataFrame:
    resp = requests.get(
        BITGET_TICKERS_URL,
        params={"productType": PRODUCT_TYPE},
        timeout=timeout,
    )
    resp.raise_for_status()
    p = resp.json()
    if p.get("msg") != "success":
        raise RuntimeError(f"Bitget API error: code={p.get('code')} msg={p.get('msg')}")
    df = pd.DataFrame(p.get("data") or [])
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def fmt_compact_usd(v: Any) -> str:
    """1,234,567 → ``$1.2M``."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(x):
        return "—"
    a = abs(x)
    if a >= 1e9:
        return f"${x/1e9:.2f}B"
    if a >= 1e6:
        return f"${x/1e6:.1f}M"
    if a >= 1e3:
        return f"${x/1e3:.1f}K"
    return f"${x:.0f}"


def fmt_price(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(x):
        return "—"
    a = abs(x)
    if a >= 1000:
        return f"{x:,.2f}"
    if a >= 1:
        return f"{x:,.4f}"
    if a >= 0.01:
        return f"{x:.5f}"
    return f"{x:.8f}"


def color_for(value: float) -> str:
    if value > 0:
        return UP_COLOR
    if value < 0:
        return DOWN_COLOR
    return FLAT_COLOR


# ---------------------------------------------------------------------------
# Card rendering
# ---------------------------------------------------------------------------

def card_html(row: pd.Series) -> str:
    symbol = str(row.get("symbol", "?"))
    price = fmt_price(row.get("markPrice"))
    chg = row.get("change24h")
    try:
        chg_f = float(chg)
    except (TypeError, ValueError):
        chg_f = 0.0
    chg_str = "—" if pd.isna(chg_f) else f"{'+' if chg_f >= 0 else ''}{chg_f*100:.2f}%"
    chg_color = color_for(chg_f if not pd.isna(chg_f) else 0)

    qv = fmt_compact_usd(row.get("quoteVolume"))
    fr = row.get("fundingRate")
    try:
        fr_f = float(fr)
    except (TypeError, ValueError):
        fr_f = 0.0
    fr_str = "—" if pd.isna(fr_f) else f"{'+' if fr_f >= 0 else ''}{fr_f*100:.3f}%"
    fr_color = color_for(fr_f if not pd.isna(fr_f) else 0)

    return (
        '<div style="'
        'display:flex; justify-content:space-between; align-items:center; '
        'padding:12px 14px; border-bottom:1px solid rgba(120,120,120,0.18);'
        '">'
        '<div style="flex:1; min-width:0;">'
        f'<div style="font-size:16px; font-weight:600; line-height:1.2;">{symbol}</div>'
        '<div style="font-size:12px; color:#888; margin-top:4px;">'
        f'Vol <span style="color:#bbb;">{qv}</span> '
        f'· Fund <span style="color:{fr_color};">{fr_str}</span>'
        '</div>'
        '</div>'
        '<div style="text-align:right; margin-left:8px;">'
        f'<div style="font-size:16px; font-weight:500;">{price}</div>'
        '<div style="'
        'display:inline-block; min-width:74px; text-align:center; '
        'margin-top:4px; padding:3px 8px; border-radius:5px; '
        f'font-size:13px; font-weight:600; color:white; background-color:{chg_color};'
        f'">{chg_str}</div>'
        '</div>'
        '</div>'
    )


def render_card_list(st, df: pd.DataFrame, n: int) -> None:
    if df.empty:
        st.info("결과 없음")
        return
    cards = "".join(card_html(row) for _, row in df.head(n).iterrows())
    container = (
        '<div style="border:1px solid rgba(120,120,120,0.18); '
        'border-radius:8px; overflow:hidden; margin-top:8px;">'
        + cards
        + '</div>'
    )
    st.markdown(container, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

SORT_MODES = {
    "🔥 거래대금": ("quoteVolume", False),    # descending
    "📈 상승": ("change24h", False),
    "📉 하락": ("change24h", True),            # ascending
    "💰 펀딩": ("_abs_funding", False),       # virtual column built per-render
}


def main() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="Mobile — Crypto",
        page_icon="📱",
        layout="centered",
    )
    st.markdown("### 📱 Live Tickers")

    with st.sidebar:
        st.header("Refresh")
        auto = st.toggle("Auto-refresh", value=True)
        interval = st.select_slider("Interval (s)", options=[5, 10, 30, 60], value=10)
        if st.button("Refresh now", use_container_width=True):
            st.cache_data.clear()

        st.markdown("---")
        st.header("Display")
        top_n = st.number_input(
            "Top N", min_value=10, max_value=300, value=50, step=10,
        )

    @st.cache_data(ttl=3, show_spinner=False)
    def _cached_fetch() -> pd.DataFrame:
        return fetch_tickers()

    run_every = interval if auto else None

    @st.fragment(run_every=run_every)
    def render() -> None:
        try:
            df = _cached_fetch()
        except Exception as e:
            st.error(f"Bitget API 실패: {e}")
            return

        col_meta1, col_meta2 = st.columns([3, 2])
        col_meta1.caption(f"⏱ {datetime.now().strftime('%H:%M:%S')}")
        col_meta2.caption(f"📊 {len(df):,} symbols")

        search = st.text_input("🔍 Symbol", value="", key="m_search", label_visibility="collapsed",
                               placeholder="Symbol contains…").strip()
        if search:
            df = df[df["symbol"].astype(str).str.contains(search, case=False, na=False)]

        # Sort preset radio (single render — only one list shown at a time).
        sort_label = st.radio(
            "Sort",
            options=list(SORT_MODES.keys()),
            horizontal=True,
            label_visibility="collapsed",
            key="m_sort",
        )
        sort_col, ascending = SORT_MODES[sort_label]

        # Funding sort uses absolute value to find extremes (both directions)
        if sort_col == "_abs_funding":
            df = df.assign(_abs_funding=df["fundingRate"].abs() if "fundingRate" in df.columns else 0)
        if sort_col in df.columns:
            df = df.sort_values(sort_col, ascending=ascending, na_position="last")

        render_card_list(st, df, int(top_n))

    render()


main()
