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
# Constants — shared period / window choices for all stock pages
# ---------------------------------------------------------------------------

# Fixed period % columns (always shown). Daily-only since stock caches are 1D.
PERIODS_D: list[int] = [1, 3, 7, 14, 28, 56, 140]

# Selectable window — drives MA10/MA20 Δ% + Window High/Low Δ%.
# Smaller windows are skipped because MA10/20 of 1d stride is already shown
# in conventional MA lines on the chart; Bitget's window concept here means
# the *stride* between MA samples (so "28d" → MA10 = average of every 28th close).
WINDOW_OPTIONS: list[str] = ["7d", "14d", "28d", "56d", "140d"]
DEFAULT_WINDOW: str = "28d"

MA_PERIODS: tuple[int, int] = (10, 20)


# ---------------------------------------------------------------------------
# Cache loader (capitalized OHLC — KR/US schema)
# ---------------------------------------------------------------------------

def load_cache_tails(path: Path, n: int) -> Optional[dict[str, np.ndarray]]:
    """Read the last ``n`` rows of (Close, High, Low) from a stock parquet.

    Returns float64 numpy arrays (oldest→newest) or ``None`` on miss/empty.
    Reads the whole column (parquet offset filtering isn't reliable) but only
    materializes the tail into Python.
    """
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path, columns=["Close", "High", "Low"])
    except Exception:
        return None
    if df.empty:
        return None
    tail = df.tail(n) if n and n < len(df) else df
    return {
        "close": tail["Close"].to_numpy(dtype=np.float64, copy=False),
        "high": tail["High"].to_numpy(dtype=np.float64, copy=False),
        "low": tail["Low"].to_numpy(dtype=np.float64, copy=False),
    }


def _parse_window_label(label: str) -> int:
    """``"28d"`` → ``28``. Stock caches are daily-only so granularity is fixed."""
    if not label.endswith("d"):
        raise ValueError(f"stock window must end in 'd': {label!r}")
    return int(label[:-1])


# ---------------------------------------------------------------------------
# Single-pass compute: fixed period % + per-window MA / H-L Δ%
# ---------------------------------------------------------------------------

def compute_from_cache(
    current_prices: dict[str, float],
    symbols: list[str],
    cache_loader: Callable[[str, int], Optional[dict[str, np.ndarray]]],
    *,
    windows: list[str] = WINDOW_OPTIONS,
    periods_d: list[int] = PERIODS_D,
    ma_periods: tuple[int, int] = MA_PERIODS,
) -> pd.DataFrame:
    """Bitget-style all-windows compute for stock caches.

    Each symbol's parquet is read ONCE (via ``cache_loader``). From that single
    array we derive:
      - fixed period %: ``pct_{n}d`` for each n in ``periods_d``
      - per window w in ``windows``:
          ``pct_ma{short}__{w}``, ``pct_ma{long}__{w}``,
          ``high__{w}``, ``low__{w}``,
          ``pct_off_high__{w}``, ``pct_off_low__{w}``

    The grid switches the *displayed* window purely client-side via JsCode
    valueGetter — no server recompute when the user toggles window.
    """
    short, long_ = ma_periods
    max_ma = max(short, long_)
    parsed = [(w, _parse_window_label(w)) for w in windows]

    # How many tail rows do we need?
    need = max(periods_d) + 1
    for _label, stride in parsed:
        need = max(need, stride + 1, max_ma * stride + 1)

    pct_keys_d = [f"pct_{n}d" for n in periods_d]
    win_cols: list[str] = []
    for label, _stride in parsed:
        win_cols.extend([
            f"pct_ma{short}__{label}",
            f"pct_ma{long_}__{label}",
            f"high__{label}",
            f"low__{label}",
            f"pct_off_high__{label}",
            f"pct_off_low__{label}",
        ])
    none_cols = pct_keys_d + win_cols

    rows: list[dict[str, Any]] = []
    for sym in symbols:
        row: dict[str, Any] = {"symbol": sym}
        for k in none_cols:
            row[k] = None
        cur = current_prices.get(sym)
        if cur is None or not np.isfinite(cur):
            rows.append(row)
            continue

        arrs = cache_loader(sym, need)
        if arrs is None or arrs["close"].size == 0:
            rows.append(row)
            continue

        closes = arrs["close"]
        highs = arrs["high"]
        lows = arrs["low"]

        # ── Fixed period % ──
        for n, key in zip(periods_d, pct_keys_d):
            if closes.size > n:
                prev = float(closes[-(n + 1)])
                if prev:
                    row[key] = (cur - prev) / prev

        # ── Per-window MA + H/L (all windows from same array) ──
        for label, stride in parsed:
            if highs.size >= stride:
                hi = float(highs[-stride:].max())
                lo = float(lows[-stride:].min())
                row[f"high__{label}"] = hi
                row[f"low__{label}"] = lo
                if hi:
                    row[f"pct_off_high__{label}"] = (cur - hi) / hi
                if lo:
                    row[f"pct_off_low__{label}"] = (cur - lo) / lo

            n_closed = closes.size
            idx = n_closed - 1 - np.arange(max_ma) * stride
            valid = idx >= 0
            sampled = closes[idx[valid]] if valid.any() else np.array([], dtype=np.float64)
            if sampled.size >= short:
                ma_s = sampled[:short].mean()
                if ma_s:
                    row[f"pct_ma{short}__{label}"] = (cur - ma_s) / ma_s
            if sampled.size >= long_:
                ma_l = sampled[:long_].mean()
                if ma_l:
                    row[f"pct_ma{long_}__{label}"] = (cur - ma_l) / ma_l

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
    window_label: str,
    selected_symbol: Optional[str],
    *,
    symbol_col: str,                 # e.g. "itemCode" or "symbolCode"
    symbol_header: str,              # "Code" / "Symbol"
    name_col: Optional[str],         # "stockName" / "stockNameEng"; None to omit
    name_header: str = "Name",
    price_col: str = "closePrice",
    price_format: str = "int",       # "int" (KRW) or "dec" (USD)
    volume_col: Optional[str] = "accumulatedTradingValue",
    volume_header: str = "거래대금",
    market_cap_col: Optional[str] = "marketValue",
    market_cap_header: str = "시총",
    short_ma: int = MA_PERIODS[0],
    long_ma: int = MA_PERIODS[1],
    periods_d: list[int] = PERIODS_D,
) -> tuple[pd.DataFrame, dict]:
    """Build (reordered df, gridOptions) matching the Bitget layout for stocks.

    Visible column order (left → right):
        ▸ Symbol (pinned + checkbox), Name, Last, 거래대금, 시총,
          1d%, 3d%, 7d%, 14d%, 28d%, 56d%, 140d%,
          MA10 Δ%, MA20 Δ%, High Δ%, Low Δ%,
          메모
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
        price_col, headerName="Last", width=95,
        valueFormatter=price_fmt, type=["numericColumn"],
    )

    if volume_col:
        gob.configure_column(
            volume_col, headerName=volume_header, width=120,
            valueFormatter=JS_FMT_INT, type=["numericColumn"],
        )
    if market_cap_col:
        gob.configure_column(
            market_cap_col, headerName=market_cap_header, width=120,
            valueFormatter=JS_FMT_INT, type=["numericColumn"],
        )

    # ── Fixed period % columns ──
    for n in periods_d:
        gob.configure_column(
            f"pct_{n}d", headerName=f"{n}d%", width=68,
            valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
            type=["numericColumn"],
        )

    # ── Window-dependent (valueGetter reads `__{window}` from row data) ──
    gob.configure_column(
        SHORT_KEY, headerName=f"MA{short_ma}", width=72,
        valueGetter=js_window_value_getter(f"pct_ma{short_ma}", window_label),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    gob.configure_column(
        LONG_KEY, headerName=f"MA{long_ma}", width=72,
        valueGetter=js_window_value_getter(f"pct_ma{long_ma}", window_label),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    gob.configure_column(
        HIGH_KEY, headerName="High%", width=72,
        valueGetter=js_window_value_getter("pct_off_high", window_label),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    gob.configure_column(
        LOW_KEY, headerName="Low%", width=72,
        valueGetter=js_window_value_getter("pct_off_low", window_label),
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

    d_full = cdf.copy().sort_index()
    TAIL_N = {"1d": 200, "1w": 120, "1M": 60}.get(interval, 200)

    ma_specs = [
        (10, "#F0B90B", "MA10", "sma"),
        (20, "#F6465D", "MA20", "sma"),
        (50, "#1565C0", "MA50", "sma"),
        (100, "#000000", "VWMA100", "vwma"),
    ]
    ma_full: dict[str, pd.Series] = {}
    for period, _color, label, kind in ma_specs:
        if kind == "vwma":
            pv = d_full["Close"] * d_full["Volume"]
            num = pv.rolling(period).sum()
            den = d_full["Volume"].rolling(period).sum()
            ma_full[label] = num / den.where(den != 0)
        else:
            ma_full[label] = d_full["Close"].rolling(period).mean()

    d = d_full.tail(TAIL_N)
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
        ma = ma_full[label].reindex(d.index)
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

    chart_options = {
        "height": 520,
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
            "scaleMargins": {"top": 0.05, "bottom": 0.25},
        },
        "timeScale": {
            "borderColor": "rgba(0,0,0,0.15)",
            "timeVisible": False, "secondsVisible": False,
            "rightOffset": 6, "barSpacing": 6,
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
            "priceScale": {"scaleMargins": {"top": 0.78, "bottom": 0}},
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
</style>
"""
