"""Bitget/TradingView 스타일 OHLC 차트 (재사용 가능한 Plotly 모듈).

자산 무관(crypto/kr/us) — 컬럼 케이스, 시간 컬럼 차이를 내부에서 정규화.

사용 예
-------
>>> from data.loader import load_ohlcv
>>> from dashboards.charts import plot_ohlcv
>>> df = load_ohlcv("crypto", "BTCUSDT", "1d")
>>> fig = plot_ohlcv(df, title="BTCUSDT · 1D", ma_periods=(7, 25, 99))
>>> # Streamlit:  st.plotly_chart(fig, use_container_width=True)
>>> # 노트북:      fig.show()
"""
from __future__ import annotations

from typing import Optional, Sequence

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

KST = "Asia/Seoul"

# Bitget 팔레트
COLOR_UP = "#1FCC81"
COLOR_DOWN = "#F6465D"
MA_COLORS = ("#F0B90B", "#9B70F6", "#5CC8FA", "#FF8A65", "#42A5F5")
BG = "#ffffff"
GRID = "rgba(0,0,0,0.08)"
TEXT = "#1a1a1a"


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """입력 DataFrame을 차트 내부 표준(dt KST + 소문자 OHLCV)으로 변환.

    crypto: timestamp(UTC ms) + 소문자  →  dt(KST tz-aware) + 그대로
    kr/us:  DatetimeIndex(naive) + 대문자 → dt(naive) + 소문자로 rename
    """
    out = df.copy()

    case_map = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
    out = out.rename(columns={k: v for k, v in case_map.items() if k in out.columns})

    if "timestamp" in out.columns:
        out["dt"] = pd.to_datetime(out["timestamp"], unit="ms", utc=True).dt.tz_convert(KST)
    elif isinstance(out.index, pd.DatetimeIndex):
        out["dt"] = out.index
    elif "Date" in out.columns:
        out["dt"] = pd.to_datetime(out["Date"])
    else:
        raise ValueError("Cannot determine datetime: need 'timestamp', DatetimeIndex, or 'Date'")

    missing = {"open", "high", "low", "close"} - set(out.columns)
    if missing:
        raise ValueError(f"Missing OHLC columns: {sorted(missing)}")
    if "volume" not in out.columns:
        out["volume"] = 0

    return out


def plot_ohlcv(
    df: pd.DataFrame,
    *,
    title: str = "",
    ma_periods: Sequence[int] = (7, 25, 99),
    show_volume: bool = True,
    show_rsi: bool = False,
    rsi_period: int = 14,
    height: int = 720,
    range_slider: bool = False,
    skip_weekends: bool = False,
) -> go.Figure:
    """Bitget 스타일 캔들 + 이평선 + 거래량(옵션) + RSI(옵션) Figure.

    Parameters
    ----------
    df : OHLCV DataFrame. crypto(소문자+timestamp ms) / FDR 주식(대문자+DatetimeIndex) 모두 OK.
    title : 차트 제목.
    ma_periods : 가격 패널에 오버레이할 이동평균 주기. Bitget 기본 (7, 25, 99).
    show_volume : 가격 패널 아래에 거래량 막대 서브플롯.
    show_rsi : 맨 아래 RSI 서브플롯 (rsi_period 기본 14).
    height : Figure 높이(px).
    range_slider : x축 아래 미니 슬라이더 표시 여부.
    skip_weekends : 주식차트에서 토/일 공백 제거(권장: 주식만 True). crypto는 24/7이라 False.
    """
    d = _normalize(df)

    for p in ma_periods:
        d[f"ma{p}"] = d["close"].rolling(p).mean()

    if show_rsi:
        delta = d["close"].diff()
        gain = delta.clip(lower=0).rolling(rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
        rs = gain / loss.replace(0, pd.NA)
        d["rsi"] = 100 - 100 / (1 + rs)

    n_extra = int(show_volume) + int(show_rsi)
    rows = 1 + n_extra
    heights = [0.62] + [0.2] * n_extra if n_extra else [1.0]

    fig = make_subplots(
        rows=rows, cols=1, shared_xaxes=True,
        vertical_spacing=0.02, row_heights=heights,
    )

    # --- Candlestick ---
    fig.add_trace(
        go.Candlestick(
            x=d["dt"], open=d["open"], high=d["high"], low=d["low"], close=d["close"],
            name="OHLC",
            increasing_line_color=COLOR_UP, decreasing_line_color=COLOR_DOWN,
            increasing_fillcolor=COLOR_UP, decreasing_fillcolor=COLOR_DOWN,
            line=dict(width=1),
        ),
        row=1, col=1,
    )

    # --- MA overlays ---
    for i, p in enumerate(ma_periods):
        fig.add_trace(
            go.Scatter(
                x=d["dt"], y=d[f"ma{p}"], mode="lines",
                name=f"MA{p}",
                line=dict(width=1.2, color=MA_COLORS[i % len(MA_COLORS)]),
                hovertemplate=f"MA{p}: %{{y:.4f}}<extra></extra>",
            ),
            row=1, col=1,
        )

    # --- Volume bars ---
    if show_volume:
        bar_colors = [COLOR_UP if c >= o else COLOR_DOWN for c, o in zip(d["close"], d["open"])]
        fig.add_trace(
            go.Bar(
                x=d["dt"], y=d["volume"],
                marker_color=bar_colors, marker_line_width=0,
                name="Volume", showlegend=False,
                hovertemplate="Vol: %{y:,.2f}<extra></extra>",
            ),
            row=2, col=1,
        )

    # --- RSI ---
    if show_rsi:
        rsi_row = 2 + int(show_volume)
        fig.add_trace(
            go.Scatter(
                x=d["dt"], y=d["rsi"], mode="lines",
                line=dict(width=1, color="#AB47BC"), name=f"RSI({rsi_period})",
                showlegend=False, hovertemplate="RSI: %{y:.1f}<extra></extra>",
            ),
            row=rsi_row, col=1,
        )
        fig.add_hline(y=70, line_dash="dash", line_color="rgba(246,70,93,0.4)", row=rsi_row, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="rgba(31,204,129,0.4)", row=rsi_row, col=1)

    # --- Layout ---
    fig.update_layout(
        title=dict(text=title, x=0.01, font=dict(size=14, color=TEXT)),
        height=height,
        paper_bgcolor=BG, plot_bgcolor=BG,
        font=dict(color=TEXT, family="Inter, sans-serif"),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.0, x=0.0,
            bgcolor="rgba(0,0,0,0)", font=dict(size=11),
        ),
        margin=dict(l=10, r=10, t=40, b=10),
        hovermode="x unified",
        xaxis_rangeslider_visible=range_slider,
        dragmode="pan",
    )

    fig.update_xaxes(showgrid=True, gridcolor=GRID, showline=False, color=TEXT, zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, color=TEXT, side="right", zeroline=False)

    fig.update_yaxes(title_text="Price", row=1, col=1)
    if show_volume:
        fig.update_yaxes(title_text="Volume", row=2, col=1)
    if show_rsi:
        rsi_row = 2 + int(show_volume)
        fig.update_yaxes(title_text="RSI", row=rsi_row, col=1, range=[0, 100])

    if skip_weekends:
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

    return fig


def plot_symbol(
    asset: str,
    symbol: str,
    interval: str = "1d",
    *,
    bars: Optional[int] = 300,
    **plot_kwargs,
) -> go.Figure:
    """편의 함수: 자산+심볼+인터벌만 주면 캐시에서 로드해 차트 반환.

    >>> fig = plot_symbol("crypto", "BTCUSDT", "1d", bars=500)
    """
    from data.loader import load_ohlcv
    df = load_ohlcv(asset, symbol, interval)
    if bars is not None and len(df) > bars:
        df = df.tail(bars)
    title = plot_kwargs.pop("title", f"{symbol} · {interval.upper()} · {asset.upper()}")
    skip_weekends = plot_kwargs.pop("skip_weekends", asset in ("kr", "us"))
    return plot_ohlcv(df, title=title, skip_weekends=skip_weekends, **plot_kwargs)
