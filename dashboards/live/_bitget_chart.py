"""Bitget/TradingView-style chart for crypto OHLCV (lowercase columns).

The stock side has its own counterpart in ``dashboards/_stock_grid`` because
its DataFrames carry capitalized OHLC columns + a DatetimeIndex; the crypto
cache stores ``timestamp`` (UTC ms) as a column and lowercase OHLC, so the
candle/MA/RSI assembly differs enough to keep the two separate. The overlays
(fib / trendlines) and the crosshair-tooltip ``legendLabel`` convention are
shared via ``_stock_grid`` so both charts behave identically.

Indicators (MA10/20/50 SMA + VWMA100 + RSI14 + MACD) are computed on the *full*
series so the visible slice already contains warmup values from older bars.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from dashboards._stock_grid import (
    DEFAULT_BAR_SPACING,
    INITIAL_VISIBLE_BARS,
    _overlay_series,
)


def render_tv_chart(
    symbol: str,
    interval: str,
    cdf: pd.DataFrame,
    *,
    fib_n: Optional[int] = None,
    trendlines: Optional[list] = None,
) -> None:
    """Render a Bitget/TradingView-style chart from a crypto OHLCV DataFrame.

    ``cdf`` must carry: ``timestamp`` (int UTC ms), ``open/high/low/close/volume``
    (lowercase). Caller must have ``streamlit_lightweight_charts`` installed
    — this module raises ImportError at call time if missing so a fallback
    path (e.g. plotly) can be chosen by the caller.

    ``fib_n`` overlays fib retracement from the last ``fib_n`` bars' swing;
    ``trendlines`` overlays manual ``{"p1": [iso_date, price], "p2": ...}`` segments.
    """
    import streamlit as _st
    from streamlit_lightweight_charts import renderLightweightCharts  # type: ignore
    from dashboards._stock_grid import chart_legend_html

    d = cdf.copy()
    # crypto cache: timestamp(UTC ms). lightweight-charts expects unix seconds.
    d["t"] = (pd.to_numeric(d["timestamp"]) // 1000).astype("int64")
    d = d.sort_values("t").drop_duplicates(subset="t", keep="last").reset_index(drop=True)

    # (period, color, label, kind)  kind: "sma" | "vwma"
    ma_specs = [
        (10, "#F0B90B", "MA10", "sma"),    # 노란색
        (20, "#F6465D", "MA20", "sma"),    # 빨간색
        (50, "#1565C0", "MA50", "sma"),    # 진한 파란색
        (100, "#000000", "VWMA100", "vwma"),  # 검정색 (거래량 가중)
    ]
    ma_full: dict[str, pd.Series] = {}
    for period, _color, label, kind in ma_specs:
        if kind == "vwma":
            pv = d["close"] * d["volume"]
            num = pv.rolling(period).sum()
            den = d["volume"].rolling(period).sum()
            ma_full[label] = num / den.where(den != 0)
        else:
            ma_full[label] = d["close"].rolling(period).mean()

    # RSI(14) — Wilder's smoothing via EWM(alpha=1/14).
    delta = d["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.where(avg_loss != 0)
    rsi_full = 100 - (100 / (1 + rs))

    # MACD(12,26,9) — EMA12-EMA26 line, EMA9 signal, histogram = line-signal.
    ema12 = d["close"].ewm(span=12, adjust=False).mean()
    ema26 = d["close"].ewm(span=26, adjust=False).mean()
    macd_full = ema12 - ema26
    signal_full = macd_full.ewm(span=9, adjust=False).mean()
    hist_full = macd_full - signal_full

    # 전체 히스토리를 그대로 전송 — 패치된 프론트엔드(patch_lwc.py)가 fitContent
    # 대신 scrollToRealTime 을 호출하고 initialVisibleBars 만큼 barSpacing 을 맞춘다.
    candles = [
        {"time": int(t), "open": float(o), "high": float(h),
         "low": float(l), "close": float(c)}
        for t, o, h, l, c in zip(d["t"], d["open"], d["high"], d["low"], d["close"])
    ]

    UP, DOWN = "#1FCC81", "#F6465D"
    UP_FAINT, DOWN_FAINT = "rgba(31,204,129,0.5)", "rgba(246,70,93,0.5)"
    volumes = [
        {"time": int(t), "value": float(v),
         "color": UP_FAINT if c >= o else DOWN_FAINT}
        for t, v, o, c in zip(d["t"], d["volume"], d["open"], d["close"])
    ]

    ma_series = []
    for period, color, label, kind in ma_specs:
        ma = ma_full[label]
        line_data = [
            {"time": int(t), "value": float(v)}
            for t, v in zip(d["t"], ma) if pd.notna(v)
        ]
        if not line_data:
            continue
        ma_series.append({
            "type": "Line",
            "data": line_data,
            "legendLabel": label,  # crosshair tooltip (read by patched frontend)
            "options": {
                "color": color,
                "lineWidth": 1,
                "priceLineVisible": False,
                "lastValueVisible": False,
                "crosshairMarkerVisible": False,
            },
        })

    rsi_line = [
        {"time": int(t), "value": float(v)}
        for t, v in zip(d["t"], rsi_full) if pd.notna(v)
    ]
    rsi_30 = (
        [{"time": int(d["t"].iloc[0]), "value": 30.0},
         {"time": int(d["t"].iloc[-1]), "value": 30.0}]
        if len(d) else []
    )
    rsi_70 = (
        [{"time": int(d["t"].iloc[0]), "value": 70.0},
         {"time": int(d["t"].iloc[-1]), "value": 70.0}]
        if len(d) else []
    )

    MACD_UP, MACD_DOWN = "rgba(31,204,129,0.6)", "rgba(246,70,93,0.6)"
    macd_hist = [
        {"time": int(t), "value": float(v),
         "color": MACD_UP if v >= 0 else MACD_DOWN}
        for t, v in zip(d["t"], hist_full) if pd.notna(v)
    ]
    macd_line = [
        {"time": int(t), "value": float(v)}
        for t, v in zip(d["t"], macd_full) if pd.notna(v)
    ]
    signal_line = [
        {"time": int(t), "value": float(v)}
        for t, v in zip(d["t"], signal_full) if pd.notna(v)
    ]

    chart_options = {
        "height": 800,
        # Read by the patched frontend → barSpacing = width / N (exchange-style
        # fixed initial candle count, independent of monitor width).
        "initialVisibleBars": INITIAL_VISIBLE_BARS,
        "layout": {
            "background": {"type": "solid", "color": "#ffffff"},
            "textColor": "#1a1a1a",
            "fontFamily": "Inter, sans-serif",
        },
        "grid": {
            "vertLines": {"color": "rgba(0,0,0,0.06)"},
            "horzLines": {"color": "rgba(0,0,0,0.06)"},
        },
        "rightPriceScale": {
            "borderColor": "rgba(0,0,0,0.15)",
            # 4 stacked panes: candles / volume / RSI / MACD.
            "scaleMargins": {"top": 0.03, "bottom": 0.53},
        },
        "timeScale": {
            "borderColor": "rgba(0,0,0,0.15)",
            "timeVisible": interval in ("1h", "4h"),
            "secondsVisible": False,
            "rightOffset": 6,
            "barSpacing": DEFAULT_BAR_SPACING,
            "minBarSpacing": 0.5,  # allow zooming far out across full history
        },
        "crosshair": {"mode": 1},
        "watermark": {
            "visible": True,
            "text": f"{symbol} · {interval.upper()}",
            "color": "rgba(0,0,0,0.08)",
            "fontSize": 36,
            "horzAlign": "center",
            "vertAlign": "center",
        },
    }

    series = [
        {
            "type": "Candlestick",
            "data": candles,
            "legendLabel": "OHLC",  # crosshair tooltip (read by patched frontend)
            "options": {
                "upColor": UP, "downColor": DOWN,
                "wickUpColor": UP, "wickDownColor": DOWN,
                "borderVisible": False,
            },
        },
        *ma_series,
        {
            "type": "Histogram",
            "data": volumes,
            "legendLabel": "Vol",
            "options": {
                "priceFormat": {"type": "volume"},
                "priceScaleId": "vol",
                "lastValueVisible": False,
                "priceLineVisible": False,
            },
            "priceScale": {
                "scaleMargins": {"top": 0.49, "bottom": 0.39},
            },
        },
        {
            "type": "Line",
            "data": rsi_line,
            "legendLabel": "RSI",
            "options": {
                "color": "#7E57C2", "lineWidth": 1,
                "priceScaleId": "rsi",
                "priceLineVisible": False, "lastValueVisible": False,
                "crosshairMarkerVisible": False,
            },
            "priceScale": {
                "scaleMargins": {"top": 0.63, "bottom": 0.21},
                "autoScale": False,
            },
        },
        {
            "type": "Line",
            "data": rsi_30,
            "options": {
                "color": "rgba(38, 166, 154, 0.45)", "lineWidth": 1,
                "lineStyle": 2,
                "priceScaleId": "rsi",
                "priceLineVisible": False, "lastValueVisible": False,
                "crosshairMarkerVisible": False,
            },
        },
        {
            "type": "Line",
            "data": rsi_70,
            "options": {
                "color": "rgba(239, 83, 80, 0.45)", "lineWidth": 1,
                "lineStyle": 2,
                "priceScaleId": "rsi",
                "priceLineVisible": False, "lastValueVisible": False,
                "crosshairMarkerVisible": False,
            },
        },
        # ── MACD pane (bottom) — histogram + MACD line + signal line ──
        {
            "type": "Histogram",
            "data": macd_hist,
            "legendLabel": "Hist",
            "options": {
                "priceScaleId": "macd",
                "lastValueVisible": False, "priceLineVisible": False,
            },
            "priceScale": {"scaleMargins": {"top": 0.81, "bottom": 0}},
        },
        {
            "type": "Line",
            "data": macd_line,
            "legendLabel": "MACD",
            "options": {
                "color": "#2962FF", "lineWidth": 1,
                "priceScaleId": "macd",
                "priceLineVisible": False, "lastValueVisible": False,
                "crosshairMarkerVisible": False,
            },
        },
        {
            "type": "Line",
            "data": signal_line,
            "legendLabel": "Signal",
            "options": {
                "color": "#FF6D00", "lineWidth": 1,
                "priceScaleId": "macd",
                "priceLineVisible": False, "lastValueVisible": False,
                "crosshairMarkerVisible": False,
            },
        },
    ]

    # Fibonacci levels + manual trendlines (shared with the stock renderer).
    snap_dates = pd.to_datetime(d["timestamp"], unit="ms")
    series.extend(_overlay_series(
        d["t"].to_numpy(), d["high"], d["low"], snap_dates, fib_n, trendlines,
    ))

    legend = chart_legend_html([(lbl, clr) for _p, clr, lbl, _k in ma_specs])
    with _st.container(key="chart_legend_wrap"):
        _st.markdown(legend, unsafe_allow_html=True)
        renderLightweightCharts(
            [{"chart": chart_options, "series": series}],
            key=f"lwc_{symbol}_{interval}",
        )
