"""Bitget 스타일 인터랙티브 차트 — crypto / KR / US 통합.

URL query params로 직접 진입 가능:
    ?asset=crypto&symbol=BTCUSDT&interval=1d
"""
from __future__ import annotations

import sys
from pathlib import Path

# allow `from dashboards.X` and `from data.X` regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from data.loader import list_symbols, load_ohlcv
from dashboards._lib import render_fetch_log_sidebar
from dashboards.charts import plot_ohlcv

ASSET_LABELS = {"crypto": "🪙 Crypto (Bitget)", "kr": "🇰🇷 KOSPI", "us": "🇺🇸 NASDAQ"}
ASSET_DEFAULTS = {"crypto": "BTCUSDT", "kr": "005930", "us": "AAPL"}
INTERVAL_OPTIONS = {
    "crypto": ["1h", "4h", "1d", "1w"],
    "kr": ["1d", "1w"],
    "us": ["1d", "1w"],
}
MA_PRESET = [5, 7, 10, 20, 25, 50, 60, 99, 120, 240]
VWMA_PRESET = [20, 50, 100, 200]

st.set_page_config(page_title="Chart", page_icon="📈", layout="wide")
render_fetch_log_sidebar(st)
st.title("📈 Chart")


# --- Read query params (for deep links from other pages) ---
qp = st.query_params
qp_asset = qp.get("asset", "crypto")
qp_symbol = qp.get("symbol")
qp_interval = qp.get("interval")


# --- Sidebar controls ---
with st.sidebar:
    st.header("Selection")
    asset = st.radio(
        "자산",
        options=list(ASSET_LABELS.keys()),
        format_func=lambda a: ASSET_LABELS[a],
        index=list(ASSET_LABELS.keys()).index(qp_asset) if qp_asset in ASSET_LABELS else 0,
        horizontal=False,
    )

    symbols = list_symbols(asset)
    if not symbols:
        st.warning(
            f"{asset} 캐시가 비어 있습니다. `/{asset}-fetch` 스킬을 먼저 실행하세요."
        )
        st.stop()

    default_sym = qp_symbol if qp_symbol in symbols else ASSET_DEFAULTS.get(asset, symbols[0])
    if default_sym not in symbols:
        default_sym = symbols[0]
    symbol = st.selectbox("심볼", options=symbols, index=symbols.index(default_sym))

    interval_opts = INTERVAL_OPTIONS[asset]
    default_iv = qp_interval if qp_interval in interval_opts else interval_opts[-2 if len(interval_opts) >= 2 else 0]
    interval = st.select_slider("인터벌", options=interval_opts, value=default_iv)

    bars = st.slider("표시 봉 개수", min_value=50, max_value=2000, value=300, step=50)

    st.markdown("---")
    st.header("Indicators")
    ma_choice = st.multiselect("이동평균 (SMA)", options=MA_PRESET, default=[10, 20, 50])
    vwma_choice = st.multiselect("거래량가중 이동평균 (VWMA)", options=VWMA_PRESET, default=[100])
    show_volume = st.toggle("거래량", value=True)
    show_rsi = st.toggle("RSI(14)", value=False)


# Sync query params so the URL reflects current selection (sharable link)
st.query_params.update({"asset": asset, "symbol": symbol, "interval": interval})


# --- Load data ---
try:
    df = load_ohlcv(asset, symbol, interval)
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()
except Exception as e:  # noqa: BLE001
    st.error(f"로드 실패: {e}")
    st.stop()

if df is None or len(df) == 0:
    st.warning("데이터가 비어 있습니다.")
    st.stop()

df_view = df.tail(bars)


# --- Metrics row ---
def _col(name_lower: str, name_title: str) -> pd.Series:
    return df_view[name_lower] if name_lower in df_view.columns else df_view[name_title]

close = _col("close", "Close")
high = _col("high", "High")
low = _col("low", "Low")
last = float(close.iloc[-1])
prev = float(close.iloc[-2]) if len(close) >= 2 else last
chg_pct = (last - prev) / prev * 100 if prev else 0.0

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Last", f"{last:,.4f}", f"{chg_pct:+.2f}%")
m2.metric("Period High", f"{high.max():,.4f}")
m3.metric("Period Low", f"{low.min():,.4f}")
m4.metric("Bars", f"{len(df_view):,}")
total_ret = (last / float(close.iloc[0]) - 1) * 100 if float(close.iloc[0]) else 0.0
m5.metric("Period Return", f"{total_ret:+.2f}%")


# --- Chart ---
fig = plot_ohlcv(
    df_view,
    title=f"{symbol} · {interval.upper()} · {ASSET_LABELS[asset]}",
    ma_periods=tuple(sorted(ma_choice)) if ma_choice else (),
    vwma_periods=tuple(sorted(vwma_choice)) if vwma_choice else (),
    show_volume=show_volume,
    show_rsi=show_rsi,
    height=760 + (120 if show_rsi else 0),
    skip_weekends=(asset in ("kr", "us")),
)

st.plotly_chart(
    fig,
    use_container_width=True,
    config={
        "scrollZoom": True,
        "displayModeBar": True,
        "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"],
    },
)

with st.expander("Data peek (마지막 10행)"):
    st.dataframe(df_view.tail(10), use_container_width=True)
