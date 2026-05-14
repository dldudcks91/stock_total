"""Bitget AgGrid spec — column labels, JsCode formatters, options builder.

Stock pages share their column spec via ``dashboards/_stock_grid`` because
KOSPI and NASDAQ have nearly identical schemas; Bitget's snapshot carries a
different set (markPrice, quoteVolume, fundingRate, marketCap, period %
hourly/daily, ...) so its grid spec lives here.

The two-axis window model (``MA Interval`` × ``HL Lookback``) is the same as
the stock pages: every window's value is pre-computed and shipped in the row
data; the visible MA / High / Low columns use JsCode ``valueGetter`` to flip
which suffix-keyed column shows. Toggling is therefore client-side once the
data has been sent.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from st_aggrid import GridOptionsBuilder, JsCode

from dashboards.live._crypto_compute import MA_PERIODS, PERIODS_D, PERIODS_H


# ---------------------------------------------------------------------------
# Column labels (used by the "Sort by" dropdown above the grid)
# ---------------------------------------------------------------------------

COLUMN_LABELS: dict[str, str] = {
    "symbol": "Symbol",
    "markPrice": "Mark",
    "lastPr": "Last",
    "pct_1h": "1h",
    "pct_4h": "4h",
    "change24h": "24h",
    "changeUtc24h": "24h (UTC)",
    "pct_3d": "3d",
    "pct_7d": "7d",
    "pct_14d": "14d",
    "pct_28d": "28d",
    "pct_off_high24h": "24h High Δ",
    "pct_off_low24h": "24h Low Δ",
    "pct_ma10": "MA10 Δ",
    "pct_ma20": "MA20 Δ",
    "high24h": "24h High",
    "low24h": "24h Low",
    "open24h": "24h Open",
    "openUtc": "Open (UTC)",
    "quoteVolume": "거래대금 (USDT)",
    "marketCap": "시가총액",
    "baseVolume": "Base Vol",
    "usdtVolume": "USDT Vol",
    "fundingRate": "Funding",
    "holdingAmount": "OI (coin)",
    "indexPrice": "Index",
    "askPr": "Ask",
    "bidPr": "Bid",
    "note": "메모",
}


# ---------------------------------------------------------------------------
# JsCode formatters / cellStyle
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

JS_FMT_PRICE = JsCode("""
function(params) {
  const v = params.value;
  if (v == null || Number.isNaN(v)) return '—';
  return Number(v).toLocaleString('en-US', {minimumFractionDigits: 4, maximumFractionDigits: 4});
}
""")

JS_FMT_INT = JsCode("""
function(params) {
  const v = params.value;
  if (v == null || Number.isNaN(v)) return '—';
  return Math.round(v).toLocaleString('en-US');
}
""")

JS_FMT_MCAP = JsCode("""
function(params) {
  const v = params.value;
  if (v == null || Number.isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e12) return '$' + (v / 1e12).toFixed(2) + 'T';
  if (abs >= 1e9)  return '$' + (v / 1e9 ).toFixed(2) + 'B';
  if (abs >= 1e6)  return '$' + (v / 1e6 ).toFixed(1) + 'M';
  if (abs >= 1e3)  return '$' + (v / 1e3 ).toFixed(1) + 'K';
  return '$' + v.toFixed(0);
}
""")


def js_window_value_getter(field_prefix: str, window_label: str) -> JsCode:
    """JsCode that returns ``row[`{prefix}__{window}`]``.

    Lets the grid keep four visible window-dependent columns (MA10, MA20,
    High%, Low%) while the row data carries values for all windows. Switching
    window = re-evaluating valueGetter on the same row data; no server work.
    """
    return JsCode(
        f"function(params) {{ return params.data['{field_prefix}__{window_label}']; }}"
    )


# ---------------------------------------------------------------------------
# Grid options builder
# ---------------------------------------------------------------------------

def build_grid_options(
    df: pd.DataFrame,
    ma_interval: str,
    hl_lookback: str,
    selected_symbol: Optional[str],
    *,
    short_ma: int = MA_PERIODS[0],
    long_ma: int = MA_PERIODS[1],
) -> tuple[pd.DataFrame, dict]:
    """Construct (df_reordered, gridOptions) for the Bitget AgGrid.

    Column order (left → right, displayed):
        ▸ checkbox + Symbol (pinned), Mark, 거래대금, 시총, Funding,
          1h%, 4h%, 24h%, 3d%, 7d%, 14d%, 28d%,
          MA10 (ma_interval), MA20 (ma_interval),
          High% (hl_lookback), Low% (hl_lookback),
          메모

    ``ma_interval`` ∈ ``MA_INTERVAL_OPTIONS_CRYPTO`` selects which __{iv}
    suffix the MA columns read; ``hl_lookback`` ∈ ``HL_LOOKBACK_OPTIONS_CRYPTO``
    selects the suffix for the H/L columns. Both flip purely client-side via
    JsCode valueGetter — no server recompute when the user changes window.
    """
    SHORT_KEY = f"_ma{short_ma}"
    LONG_KEY = f"_ma{long_ma}"
    HIGH_KEY = "_high_pct"
    LOW_KEY = "_low_pct"

    VISIBLE_ORDER = [
        "symbol",
        "markPrice", "quoteVolume", "marketCap", "fundingRate",
        "pct_1h", "pct_4h", "change24h",
        "pct_3d", "pct_7d", "pct_14d", "pct_28d",
        SHORT_KEY, LONG_KEY, HIGH_KEY, LOW_KEY,
        "note",
    ]

    df_grid = df.copy()
    for placeholder in (SHORT_KEY, LONG_KEY, HIGH_KEY, LOW_KEY):
        if placeholder not in df_grid.columns:
            df_grid[placeholder] = None

    visible_present = [c for c in VISIBLE_ORDER if c in df_grid.columns]
    hidden_present = [c for c in df_grid.columns if c not in visible_present]
    df_grid = df_grid[visible_present + hidden_present]

    gob = GridOptionsBuilder.from_dataframe(df_grid)
    gob.configure_default_column(
        resizable=True, sortable=True, filter=False,
        editable=False, suppressMovable=False,
        cellStyle={"display": "flex", "alignItems": "center"},
    )

    # ── Symbol (pinned left, doubles as checkbox column) ──
    gob.configure_column(
        "symbol", headerName="Symbol", pinned="left",
        width=130, minWidth=100,
        checkboxSelection=True, headerCheckboxSelection=False,
    )

    # ── Mark / 거래대금 / 시가총액 / Funding ──
    gob.configure_column(
        "markPrice", headerName="Mark", width=95,
        valueFormatter=JS_FMT_PRICE, type=["numericColumn"],
    )
    gob.configure_column(
        "quoteVolume", headerName="거래대금", width=115,
        valueFormatter=JS_FMT_INT, type=["numericColumn"],
    )
    gob.configure_column(
        "marketCap", headerName="시가총액", width=90,
        valueFormatter=JS_FMT_MCAP, type=["numericColumn"],
    )
    gob.configure_column(
        "fundingRate", headerName="Funding", width=62,
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )

    # ── Fixed period % columns ──
    for n in PERIODS_H:
        gob.configure_column(
            f"pct_{n}h", headerName=f"{n}h", width=56,
            valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
            type=["numericColumn"],
        )
    gob.configure_column(
        "change24h", headerName="24h", width=56,
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    for n in PERIODS_D:
        gob.configure_column(
            f"pct_{n}d", headerName=f"{n}d", width=56,
            valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
            type=["numericColumn"],
        )

    # ── MA columns (valueGetter reads `__{ma_interval}` from row data) ──
    gob.configure_column(
        SHORT_KEY, headerName=f"MA{short_ma}", width=60,
        valueGetter=js_window_value_getter(f"pct_ma{short_ma}", ma_interval),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    gob.configure_column(
        LONG_KEY, headerName=f"MA{long_ma}", width=60,
        valueGetter=js_window_value_getter(f"pct_ma{long_ma}", ma_interval),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    # ── HL columns (valueGetter reads `__{hl_lookback}` from row data) ──
    gob.configure_column(
        HIGH_KEY, headerName="High", width=58,
        valueGetter=js_window_value_getter("pct_off_high", hl_lookback),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    gob.configure_column(
        LOW_KEY, headerName="Low", width=58,
        valueGetter=js_window_value_getter("pct_off_low", hl_lookback),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )

    # ── Memo (editable, last column, wider) ──
    gob.configure_column(
        "note", headerName="메모", width=220, editable=True,
        cellEditor="agLargeTextCellEditor",
        cellEditorParams={"maxLength": 500, "rows": 3, "cols": 40},
    )

    # ── Hide everything not in VISIBLE_ORDER ──
    visible_set = set(VISIBLE_ORDER)
    for col in df_grid.columns:
        if col not in visible_set:
            gob.configure_column(col, hide=True, suppressColumnsToolPanel=True)

    # Selection: single row via checkbox.
    gob.configure_selection(
        selection_mode="single", use_checkbox=True,
        pre_selected_rows=(
            [int(df_grid.index[df_grid["symbol"] == selected_symbol][0])]
            if selected_symbol and (df_grid["symbol"] == selected_symbol).any() else []
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
        # Auto-fit columns whenever the grid container resizes — fires on
        # window resize, sidebar toggle, and the layout shifts caused by
        # ``st.dialog`` opening/closing (body scrollbar toggle). Without
        # this, ``fit_columns_on_grid_load`` only fires once at mount time
        # and columns stay at the wrong size after the chart dialog closes.
        "onGridSizeChanged": JsCode(
            "function(params){ params.api.sizeColumnsToFit(); }"
        ),
        "onFirstDataRendered": JsCode(
            "function(params){ params.api.sizeColumnsToFit(); }"
        ),
    })
    return df_grid, opts


# ---------------------------------------------------------------------------
# Page-level CSS (Bitget tab only — selectors are scoped to its keys)
# ---------------------------------------------------------------------------

BITGET_PAGE_CSS = """
<style>
/* Compact interval picker on the inline chart */
.st-key-chart_iv_picker { margin-bottom: 4px; }
.st-key-chart_iv_picker [data-testid="stHorizontalBlock"] { gap: 0 !important; }
.st-key-chart_iv_picker button {
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
/* AgGrid iframe — keep full width across fragment partial reruns.
   Without this, clicking MA Interval / HL Lookback shrinks the iframe
   because the parent block's clientWidth is re-measured mid-reflow. */
iframe[title*="aggrid"],
iframe[title*="st_aggrid"] {
  width: 100% !important;
}
</style>
"""
