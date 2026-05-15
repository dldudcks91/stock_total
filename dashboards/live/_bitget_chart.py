"""Bitget/TradingView-style chart for crypto OHLCV (lowercase columns).

The stock side has its own counterpart in ``dashboards/_stock_grid`` because
its DataFrames carry capitalized OHLC columns + a DatetimeIndex; the crypto
cache stores ``timestamp`` (UTC ms) as a column and lowercase OHLC, so the
candle/MA/RSI assembly differs enough to keep the two separate.

Indicators (MA10/20/50 SMA + VWMA100 + RSI14) are computed on the *full*
series so the visible slice already contains warmup values from older bars.
"""
from __future__ import annotations

import pandas as pd


def render_tv_chart(symbol: str, interval: str, cdf: pd.DataFrame) -> None:
    """Render a Bitget/TradingView-style chart from a crypto OHLCV DataFrame.

    ``cdf`` must carry: ``timestamp`` (int UTC ms), ``open/high/low/close/volume``
    (lowercase). Caller must have ``streamlit_lightweight_charts`` installed
    — this module raises ImportError at call time if missing so a fallback
    path (e.g. plotly) can be chosen by the caller.
    """
    from streamlit_lightweight_charts import renderLightweightCharts  # type: ignore

    d = cdf.copy()
    # crypto cache: timestamp(UTC ms). lightweight-charts expects unix seconds.
    d["t"] = (pd.to_numeric(d["timestamp"]) // 1000).astype("int64")
    d = d.sort_values("t").drop_duplicates(subset="t", keep="last").reset_index(drop=True)

    # Standard exchange-style visible bar count per interval. Indicators
    # below compute on the FULL series first, then we slice — so MAs/RSI
    # in the visible window already include "warmup" values.
    #
    # We slice (rather than relying on ``timeScale.barSpacing`` for an
    # initial viewport) because streamlit-lightweight-charts auto-fits
    # to the full data range on first render and ignores our barSpacing,
    # which made 1d / 1w / 1M all show the same calendar period.
    VISIBLE_BARS = {"1d": 150, "1w": 100, "1M": 60, "1h": 150, "4h": 150}.get(interval, 150)

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

    # Slice to visible window after indicator computation.
    d = d.tail(VISIBLE_BARS).reset_index(drop=True)
    ma_full = {label: s.tail(VISIBLE_BARS).reset_index(drop=True)
               for label, s in ma_full.items()}
    rsi_full = rsi_full.tail(VISIBLE_BARS).reset_index(drop=True)

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
            "options": {
                "color": color,
                "lineWidth": 1,
                "priceLineVisible": False,
                "lastValueVisible": False,
                "crosshairMarkerVisible": False,
                "title": label,
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

    chart_options = {
        "height": 620,
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
            "scaleMargins": {"top": 0.05, "bottom": 0.40},
        },
        "timeScale": {
            "borderColor": "rgba(0,0,0,0.15)",
            "timeVisible": interval in ("1h", "4h"),
            "secondsVisible": False,
            "rightOffset": 6,
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
            "options": {
                "priceFormat": {"type": "volume"},
                "priceScaleId": "vol",
                "lastValueVisible": False,
                "priceLineVisible": False,
            },
            "priceScale": {
                "scaleMargins": {"top": 0.62, "bottom": 0.22},
            },
        },
        {
            "type": "Line",
            "data": rsi_line,
            "options": {
                "color": "#7E57C2", "lineWidth": 1,
                "priceScaleId": "rsi",
                "priceLineVisible": False, "lastValueVisible": False,
                "crosshairMarkerVisible": False, "title": "RSI14",
            },
            "priceScale": {
                "scaleMargins": {"top": 0.82, "bottom": 0},
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
    ]

    renderLightweightCharts(
        [{"chart": chart_options, "series": series}],
        key=f"lwc_{symbol}_{interval}",
    )
