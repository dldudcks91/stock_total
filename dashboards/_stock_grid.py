"""Shared Bitget-style grid helpers for stock pages (KOSPI / NASDAQ).

Encapsulates the parts that are identical between the two stock dashboards:
- cache tail loader (capitalized OHLC columns)
- single-pass all-windows compute (returns + MA Δ% + Window H/L Δ%)
- AgGrid JsCode formatters + value getters
- Bitget/TradingView-style lightweight chart renderer

The two stock pages stay thin: they only own the live-price fetcher (Naver)
and the page-level layout / filter bar / dialog wiring.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from st_aggrid import GridOptionsBuilder, JsCode

# ---------------------------------------------------------------------------
# Constants — shared period / interval / lookback choices for all stock pages
# ---------------------------------------------------------------------------

# Fixed period % columns (always shown). Daily-only since stock caches are 1D.
PERIODS_D: list[int] = [1, 3, 7, 14, 28, 56, 140]

# MA Interval — drives MA10/MA20 columns. Matches the chart's interval picker
# (1d/1w/1M) so the dashboard's MA value equals the exchange-standard MA line
# on a daily/weekly/monthly candle chart.
MA_INTERVAL_OPTIONS: list[str] = ["1d", "1w", "1M"]
DEFAULT_MA_INTERVAL: str = "1w"

# HL Lookback — drives Window High/Low Δ%. Calendar-day window over which we
# take max(High) / min(Low). Independent of the MA interval.
HL_LOOKBACK_OPTIONS: list[str] = ["7d", "28d", "90d", "1y", "5y"]
DEFAULT_HL_LOOKBACK: str = "1y"

MA_PERIODS: tuple[int, int] = (10, 20)

# Tail size handed to the cache loader. 5y (≈ 1260 trading days) covers the
# longest HL lookback; 20 monthly bars (≈ 440 trading days) for 1M MA20 fits
# comfortably under this.
CACHE_TAIL_N: int = 1500


# ---------------------------------------------------------------------------
# Cache loader (capitalized OHLC — KR/US schema)
# ---------------------------------------------------------------------------

def load_cache_tails(path: Path, n: int) -> Optional[pd.DataFrame]:
    """Read the last ``n`` rows of (Close, High, Low) from a stock parquet.

    Returns a DataFrame indexed by date (oldest→newest) or ``None`` on
    miss/empty. The DatetimeIndex is required by ``compute_from_cache`` for
    weekly/monthly resampling and calendar-based lookback windows.
    """
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path, columns=["Close", "High", "Low"])
    except Exception:
        return None
    if df.empty:
        return None
    return df.tail(n) if n and n < len(df) else df


def _lookback_to_days(label: str) -> int:
    """``"7d"`` → ``7``, ``"1y"`` → ``365``. Calendar days, not trading days."""
    if label.endswith("d"):
        return int(label[:-1])
    if label.endswith("y"):
        return int(label[:-1]) * 365
    raise ValueError(f"unknown HL lookback label: {label!r}")


# ---------------------------------------------------------------------------
# Single-pass compute: fixed period % + per-interval MA + per-lookback H/L Δ%
# ---------------------------------------------------------------------------

def compute_from_cache(
    current_prices: dict[str, float],
    symbols: list[str],
    cache_loader: Callable[[str, int], Optional[pd.DataFrame]],
    *,
    ma_intervals: list[str] = MA_INTERVAL_OPTIONS,
    hl_lookbacks: list[str] = HL_LOOKBACK_OPTIONS,
    periods_d: list[int] = PERIODS_D,
    ma_periods: tuple[int, int] = MA_PERIODS,
) -> pd.DataFrame:
    """All-permutations compute for stock caches (MA × Interval, HL × Lookback).

    Each symbol's parquet is read ONCE (via ``cache_loader``). From that single
    DataFrame we derive:
      - fixed period %: ``pct_{n}d`` for each n in ``periods_d``
      - per MA interval iv in ``ma_intervals`` (1d/1w/1M):
          ``pct_ma{short}__{iv}``, ``pct_ma{long}__{iv}``
        MA = SMA of last ``N`` closes on bars resampled to ``iv`` — matches the
        exchange-standard MA line on a daily/weekly/monthly candle chart.
      - per HL lookback lb in ``hl_lookbacks`` (7d/28d/90d/1y/5y):
          ``high__{lb}``, ``low__{lb}``,
          ``pct_off_high__{lb}``, ``pct_off_low__{lb}``
        Calendar-day max(High) / min(Low) anchored at the cache's last index.

    The grid switches the *displayed* combination purely client-side via JsCode
    valueGetter — no server recompute when the user toggles interval/lookback.
    """
    short, long_ = ma_periods

    pct_keys_d = [f"pct_{n}d" for n in periods_d]
    ma_cols: list[str] = []
    for iv in ma_intervals:
        ma_cols.extend([f"pct_ma{short}__{iv}", f"pct_ma{long_}__{iv}"])
    hl_cols: list[str] = []
    for lb in hl_lookbacks:
        hl_cols.extend([
            f"high__{lb}", f"low__{lb}",
            f"pct_off_high__{lb}", f"pct_off_low__{lb}",
        ])
    none_cols = pct_keys_d + ma_cols + hl_cols

    rows: list[dict[str, Any]] = []
    for sym in symbols:
        row: dict[str, Any] = {"symbol": sym}
        for k in none_cols:
            row[k] = None
        cur = current_prices.get(sym)
        if cur is None or not np.isfinite(cur):
            rows.append(row)
            continue

        df = cache_loader(sym, CACHE_TAIL_N)
        if df is None or df.empty:
            rows.append(row)
            continue

        closes = df["Close"].to_numpy(dtype=np.float64, copy=False)

        # ── Fixed period % ──
        for n, key in zip(periods_d, pct_keys_d):
            if closes.size > n:
                prev = float(closes[-(n + 1)])
                if prev:
                    row[key] = (cur - prev) / prev

        # ── Per-interval MA (exchange-standard SMA on resampled bars) ──
        for iv in ma_intervals:
            if iv == "1d":
                bar_close = closes
            elif iv == "1w":
                bar_close = df["Close"].resample("W-FRI").last().dropna().to_numpy(
                    dtype=np.float64, copy=False,
                )
            elif iv == "1M":
                bar_close = df["Close"].resample("ME").last().dropna().to_numpy(
                    dtype=np.float64, copy=False,
                )
            else:
                continue
            if bar_close.size >= short:
                ma_s = bar_close[-short:].mean()
                if ma_s:
                    row[f"pct_ma{short}__{iv}"] = (cur - ma_s) / ma_s
            if bar_close.size >= long_:
                ma_l = bar_close[-long_:].mean()
                if ma_l:
                    row[f"pct_ma{long_}__{iv}"] = (cur - ma_l) / ma_l

        # ── Per-lookback High/Low (calendar days from cache's last index) ──
        last_ts = df.index[-1]
        for lb in hl_lookbacks:
            cutoff = last_ts - pd.Timedelta(days=_lookback_to_days(lb))
            mask = df.index >= cutoff
            if not mask.any():
                continue
            hi = float(df.loc[mask, "High"].max())
            lo = float(df.loc[mask, "Low"].min())
            row[f"high__{lb}"] = hi
            row[f"low__{lb}"] = lo
            if hi:
                row[f"pct_off_high__{lb}"] = (cur - hi) / hi
            if lo:
                row[f"pct_off_low__{lb}"] = (cur - lo) / lo

        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# JsCode formatters / cellStyle / valueGetter
# ---------------------------------------------------------------------------

JS_SIGNED_COLOR = JsCode("""
function(params) {
  const v = params.value;
  if (v == null || Number.isNaN(v)) return {color: '#888'};
  if (v > 0) return {color: '#2A9D8F', fontWeight: '600'};
  if (v < 0) return {color: '#E63946', fontWeight: '600'};
  return {};
}
""")

JS_FMT_PCT = JsCode("""
function(params) {
  const v = params.value;
  if (v == null || Number.isNaN(v)) return '—';
  const pct = v * 100;
  const sign = pct > 0 ? '+' : (pct < 0 ? '' : '');
  return sign + pct.toFixed(1) + '%';
}
""")

# Stock prices: thousands separator with up to 2 decimals (US) — KR is integer KRW.
JS_FMT_PRICE_INT = JsCode("""
function(params) {
  const v = params.value;
  if (v == null || Number.isNaN(v)) return '—';
  return Math.round(v).toLocaleString('en-US');
}
""")

JS_FMT_PRICE_DEC = JsCode("""
function(params) {
  const v = params.value;
  if (v == null || Number.isNaN(v)) return '—';
  return Number(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
}
""")

JS_FMT_INT = JsCode("""
function(params) {
  const v = params.value;
  if (v == null || Number.isNaN(v)) return '—';
  return Math.round(v).toLocaleString('en-US');
}
""")

# Value / market cap in millions, e.g. KRW: 600,000,000,000,000 → "600,000,000M".
JS_FMT_MILLIONS = JsCode("""
function(params) {
  const v = params.value;
  if (v == null || Number.isNaN(v)) return '—';
  return Math.round(v / 1e6).toLocaleString('en-US') + 'M';
}
""")


def js_window_value_getter(field_prefix: str, window_label: str) -> JsCode:
    """JsCode that returns ``row[`{prefix}__{window}`]`` — lets window-toggle
    flip column values purely client-side."""
    return JsCode(
        f"function(params) {{ return params.data['{field_prefix}__{window_label}']; }}"
    )


# ---------------------------------------------------------------------------
# AgGrid options builder (stock variant)
# ---------------------------------------------------------------------------

def build_stock_grid_options(
    df: pd.DataFrame,
    ma_interval: str,
    hl_lookback: str,
    selected_symbol: Optional[str],
    *,
    symbol_col: str,                 # e.g. "itemCode" or "symbolCode"
    symbol_header: str,              # "Code" / "Symbol"
    name_col: Optional[str],         # "stockName" / "stockNameEng"; None to omit
    name_header: str = "Name",
    price_col: str = "closePrice",
    price_header: str = "Last",
    price_format: str = "int",       # "int" (KRW) or "dec" (USD)
    volume_col: Optional[str] = "accumulatedTradingValue",
    volume_header: str = "거래대금",
    volume_format: str = "int",      # "int" or "millions" (e.g. KRW values)
    market_cap_col: Optional[str] = "marketValue",
    market_cap_header: str = "시총",
    market_cap_format: str = "int",  # "int" or "millions"
    pct_header_suffix: str = "%",    # appended to period / High / Low headers
    short_ma: int = MA_PERIODS[0],
    long_ma: int = MA_PERIODS[1],
    periods_d: list[int] = PERIODS_D,
) -> tuple[pd.DataFrame, dict]:
    """Build (reordered df, gridOptions) matching the Bitget layout for stocks.

    Visible column order (left → right):
        ▸ Symbol (pinned + checkbox), Name, Last, 거래대금, 시총,
          1d%, 3d%, 7d%, 14d%, 28d%, 56d%, 140d%,
          MA10 Δ% (ma_interval), MA20 Δ% (ma_interval),
          High Δ% (hl_lookback), Low Δ% (hl_lookback),
          메모

    ``ma_interval`` ∈ {1d, 1w, 1M} selects which resampled bar the MA columns
    read from; ``hl_lookback`` ∈ {7d, 28d, 90d, 1y, 5y} selects the calendar
    window for the High/Low columns. Both flip values purely client-side via
    JsCode valueGetter — no server recompute.
    """
    SHORT_KEY = f"_ma{short_ma}"
    LONG_KEY = f"_ma{long_ma}"
    HIGH_KEY = "_high_pct"
    LOW_KEY = "_low_pct"

    visible_order: list[str] = [symbol_col]
    if name_col:
        visible_order.append(name_col)
    visible_order.append(price_col)
    if volume_col:
        visible_order.append(volume_col)
    if market_cap_col:
        visible_order.append(market_cap_col)
    visible_order.extend(f"pct_{n}d" for n in periods_d)
    visible_order.extend([SHORT_KEY, LONG_KEY, HIGH_KEY, LOW_KEY, "note"])

    df_grid = df.copy()
    for placeholder in (SHORT_KEY, LONG_KEY, HIGH_KEY, LOW_KEY):
        if placeholder not in df_grid.columns:
            df_grid[placeholder] = None

    visible_present = [c for c in visible_order if c in df_grid.columns]
    hidden_present = [c for c in df_grid.columns if c not in visible_present]
    df_grid = df_grid[visible_present + hidden_present]

    gob = GridOptionsBuilder.from_dataframe(df_grid)
    gob.configure_default_column(
        resizable=True, sortable=True, filter=False,
        editable=False, suppressMovable=False,
        cellStyle={"display": "flex", "alignItems": "center"},
    )

    # ── Symbol (pinned, checkbox column) ──
    gob.configure_column(
        symbol_col, headerName=symbol_header, pinned="left",
        width=110, minWidth=90,
        checkboxSelection=True, headerCheckboxSelection=False,
    )

    if name_col:
        gob.configure_column(name_col, headerName=name_header, width=160, minWidth=120)

    price_fmt = JS_FMT_PRICE_INT if price_format == "int" else JS_FMT_PRICE_DEC
    gob.configure_column(
        price_col, headerName=price_header, width=95,
        valueFormatter=price_fmt, type=["numericColumn"],
    )

    vol_fmt = JS_FMT_MILLIONS if volume_format == "millions" else JS_FMT_INT
    mcap_fmt = JS_FMT_MILLIONS if market_cap_format == "millions" else JS_FMT_INT
    vol_width = 130 if volume_format == "millions" else 120
    mcap_width = 130 if market_cap_format == "millions" else 120
    if volume_col:
        gob.configure_column(
            volume_col, headerName=volume_header, width=vol_width,
            valueFormatter=vol_fmt, type=["numericColumn"],
        )
    if market_cap_col:
        gob.configure_column(
            market_cap_col, headerName=market_cap_header, width=mcap_width,
            valueFormatter=mcap_fmt, type=["numericColumn"],
        )

    # ── Fixed period % columns ──
    for n in periods_d:
        gob.configure_column(
            f"pct_{n}d", headerName=f"{n}d{pct_header_suffix}", width=68,
            valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
            type=["numericColumn"],
        )

    # ── MA columns (valueGetter reads `__{ma_interval}` from row data) ──
    gob.configure_column(
        SHORT_KEY, headerName=f"MA{short_ma}", width=72,
        valueGetter=js_window_value_getter(f"pct_ma{short_ma}", ma_interval),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    gob.configure_column(
        LONG_KEY, headerName=f"MA{long_ma}", width=72,
        valueGetter=js_window_value_getter(f"pct_ma{long_ma}", ma_interval),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    # ── HL columns (valueGetter reads `__{hl_lookback}` from row data) ──
    gob.configure_column(
        HIGH_KEY, headerName=f"High{pct_header_suffix}", width=72,
        valueGetter=js_window_value_getter("pct_off_high", hl_lookback),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    gob.configure_column(
        LOW_KEY, headerName=f"Low{pct_header_suffix}", width=72,
        valueGetter=js_window_value_getter("pct_off_low", hl_lookback),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )

    # ── Memo (editable, wide, last column) ──
    gob.configure_column(
        "note", headerName="메모", width=220, editable=True,
        cellEditor="agLargeTextCellEditor",
        cellEditorParams={"maxLength": 500, "rows": 3, "cols": 40},
    )

    # ── Hide everything else ──
    visible_set = set(visible_order)
    for col in df_grid.columns:
        if col not in visible_set:
            gob.configure_column(col, hide=True, suppressColumnsToolPanel=True)

    gob.configure_selection(
        selection_mode="single", use_checkbox=True,
        pre_selected_rows=(
            [int(df_grid.index[df_grid[symbol_col] == selected_symbol][0])]
            if selected_symbol and (df_grid[symbol_col] == selected_symbol).any() else []
        ),
    )

    opts = gob.build()
    opts.update({
        "rowHeight": 34,
        "headerHeight": 36,
        "suppressMenuHide": True,
        "domLayout": "normal",
        "animateRows": False,
        "suppressRowClickSelection": True,
        "rowSelection": "single",
        "enableCellTextSelection": True,
    })
    return df_grid, opts


# ---------------------------------------------------------------------------
# TradingView-style chart renderer for stocks (capitalized OHLC columns)
# ---------------------------------------------------------------------------

def render_tv_chart_stock(
    symbol: str,
    title: str,
    interval: str,
    cdf: pd.DataFrame,
    *,
    key_prefix: str,
) -> None:
    """Render a Bitget/TradingView-style chart from a stock OHLCV DataFrame.

    ``cdf`` has DatetimeIndex (naive) + columns Open/High/Low/Close/Volume.
    Caller must have ``streamlit_lightweight_charts`` installed.
    """
    from streamlit_lightweight_charts import renderLightweightCharts  # type: ignore

    d = cdf.copy().sort_index()

    # Standard exchange-style visible bar count per interval. We slice the
    # data to this tail length AFTER computing MAs/RSI on full history, so
    # the indicators in the visible window already include "warmup" values
    # from older bars.
    VISIBLE_BARS = {"1d": 150, "1w": 100, "1M": 60}.get(interval, 150)

    ma_specs = [
        (10, "#F0B90B", "MA10", "sma"),
        (20, "#F6465D", "MA20", "sma"),
        (50, "#1565C0", "MA50", "sma"),
        (100, "#000000", "VWMA100", "vwma"),
    ]
    ma_full: dict[str, pd.Series] = {}
    for period, _color, label, kind in ma_specs:
        if kind == "vwma":
            pv = d["Close"] * d["Volume"]
            num = pv.rolling(period).sum()
            den = d["Volume"].rolling(period).sum()
            ma_full[label] = num / den.where(den != 0)
        else:
            ma_full[label] = d["Close"].rolling(period).mean()

    # RSI(14) — Wilder's smoothing via EWM(alpha=1/14).
    delta = d["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.where(avg_loss != 0)
    rsi_full = 100 - (100 / (1 + rs))

    # Slice everything to the visible window (indicators already have warmup).
    d = d.tail(VISIBLE_BARS)
    ma_full = {label: s.reindex(d.index) for label, s in ma_full.items()}
    rsi_full = rsi_full.reindex(d.index)

    idx = pd.DatetimeIndex(d.index)
    t = (idx.tz_localize("UTC").astype("int64") // 10**9).astype("int64")

    candles = [
        {"time": int(ti), "open": float(o), "high": float(h),
         "low": float(l), "close": float(c)}
        for ti, o, h, l, c in zip(t, d["Open"], d["High"], d["Low"], d["Close"])
    ]

    UP, DOWN = "#1FCC81", "#F6465D"
    UP_FAINT, DOWN_FAINT = "rgba(31,204,129,0.5)", "rgba(246,70,93,0.5)"
    volumes = [
        {"time": int(ti), "value": float(v),
         "color": UP_FAINT if c >= o else DOWN_FAINT}
        for ti, v, o, c in zip(t, d["Volume"], d["Open"], d["Close"])
    ]

    ma_series = []
    for period, color, label, kind in ma_specs:
        ma = ma_full[label]
        line_data = [
            {"time": int(ti), "value": float(v)}
            for ti, v in zip(t, ma) if pd.notna(v)
        ]
        if not line_data:
            continue
        ma_series.append({
            "type": "Line",
            "data": line_data,
            "options": {
                "color": color, "lineWidth": 1,
                "priceLineVisible": False, "lastValueVisible": False,
                "crosshairMarkerVisible": False, "title": label,
            },
        })

    rsi_line = [
        {"time": int(ti), "value": float(v)}
        for ti, v in zip(t, rsi_full) if pd.notna(v)
    ]
    # 30 / 70 reference lines — flat 2-point lines spanning the visible range.
    rsi_30 = (
        [{"time": int(t[0]), "value": 30.0},
         {"time": int(t[-1]), "value": 30.0}]
        if len(t) else []
    )
    rsi_70 = (
        [{"time": int(t[0]), "value": 70.0},
         {"time": int(t[-1]), "value": 70.0}]
        if len(t) else []
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
            "timeVisible": False, "secondsVisible": False,
            "rightOffset": 6,
        },
        "crosshair": {"mode": 1},
        "watermark": {
            "visible": True,
            "text": f"{title} · {interval.upper()}",
            "color": "rgba(0,0,0,0.08)",
            "fontSize": 36,
            "horzAlign": "center", "vertAlign": "center",
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
            "priceScale": {"scaleMargins": {"top": 0.62, "bottom": 0.22}},
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
                "lineStyle": 2,  # dashed
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
                "lineStyle": 2,  # dashed
                "priceScaleId": "rsi",
                "priceLineVisible": False, "lastValueVisible": False,
                "crosshairMarkerVisible": False,
            },
        },
    ]

    renderLightweightCharts(
        [{"chart": chart_options, "series": series}],
        key=f"{key_prefix}_{symbol}_{interval}",
    )


# ---------------------------------------------------------------------------
# Notes persistence (per-page JSON file)
# ---------------------------------------------------------------------------

def load_notes(path: Path) -> dict:
    import json
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def save_notes(path: Path, notes: dict) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(notes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def render_chart_title(st: Any, title: str) -> None:
    """Left-aligned title for the chart dialog header row."""
    st.markdown(
        f"<div style='text-align:left; font-size:17px; font-weight:600; "
        f"padding-top:0px; margin-top:-6px; line-height:28px; white-space:nowrap; "
        f"overflow:hidden; text-overflow:ellipsis;'>{title}</div>",
        unsafe_allow_html=True,
    )


def render_chart_memo(
    st: Any,
    code: str,
    notes_path: Path,
    session_key: str,
    *,
    placeholder: str = "메모 작성…",
) -> None:
    """Memo text_input that persists to ``notes_path`` and the in-session dict.

    Shares the ``session_key`` dict with the grid's 메모 column, so edits made
    in the chart dialog show up in the grid (and vice versa) and survive page
    reloads via the JSON file.
    """
    notes = st.session_state.setdefault(session_key, load_notes(notes_path))
    new_val = st.text_input(
        "메모",
        value=notes.get(code, ""),
        key=f"chart_memo_input::{session_key}::{code}",
        label_visibility="collapsed",
        placeholder=placeholder,
    )
    cur = notes.get(code, "")
    new = (new_val or "").strip()
    if new != cur:
        if new:
            notes[code] = new
        else:
            notes.pop(code, None)
        save_notes(notes_path, notes)


# ---------------------------------------------------------------------------
# Shared CSS — compact interval picker for the chart dialog
# ---------------------------------------------------------------------------

STOCK_PAGE_CSS = """
<style>
.st-key-stock_chart_iv_picker { margin-bottom: 4px; }
.st-key-stock_chart_iv_picker [data-testid="stHorizontalBlock"] { gap: 0 !important; }
.st-key-stock_chart_iv_picker button {
  padding: 2px 10px !important;
  font-size: 12px !important;
  min-height: 0 !important;
  line-height: 1.4 !important;
}
/* Nudge dialog X button — small offset from default */
div[role="dialog"] button[aria-label="Close"],
[data-testid="stDialog"] button[aria-label="Close"] {
  top: 0.4rem !important;
  margin-top: -2px !important;
}
</style>
"""
