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

from dashboards._stock_grid import JS_FMT_REC, JS_STYLE_REC
from dashboards.live._crypto_compute import MA_PERIODS


# ---------------------------------------------------------------------------
# Column labels (used by the "Sort by" dropdown above the grid)
# ---------------------------------------------------------------------------

COLUMN_LABELS: dict[str, str] = {
    "symbol": "Symbol",
    "markPrice": "Mark",
    "lastPr": "Last",
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

# Signed angle in degrees — flat MA = 0°, ±sign carries direction.
# Source value is already in degrees (see ``_slope_deg`` in _crypto_compute).
JS_FMT_DEG = JsCode("""
function(params) {
  const v = params.value;
  if (v == null || Number.isNaN(v)) return '—';
  const sign = v > 0 ? '+' : (v < 0 ? '' : '');
  return sign + v.toFixed(1) + '°';
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

# Custom sort comparator: sort by |value| instead of signed value. Lets
# the user surface "biggest movers" (positive AND negative) at the top by
# clicking any signed column header. Nulls/NaN sink to bottom always.
JS_ABS_COMPARATOR = JsCode("""
function(valueA, valueB, nodeA, nodeB, isDescending) {
  const aNull = valueA == null || Number.isNaN(valueA);
  const bNull = valueB == null || Number.isNaN(valueB);
  if (aNull && bNull) return 0;
  if (aNull) return isDescending ? -1 : 1;
  if (bNull) return isDescending ? 1 : -1;
  const a = Math.abs(valueA);
  const b = Math.abs(valueB);
  return a < b ? -1 : (a > b ? 1 : 0);
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
          MA10갭, MA10∠, MA20갭, MA20∠ (all read ``__{ma_interval}``),
          High% (hl_lookback), Low% (hl_lookback),
          추천, 메모

    Fixed-period % columns (1h/4h/24h/3d/7d/14d) were removed in favor of
    MA-centric columns: gap % (price vs MA, signed) + slope ° (MA trend
    angle, signed). Trend angle is price-independent — flat MA = 0° even if
    price gaps; the two columns answer different questions.

    ``ma_interval`` ∈ ``MA_INTERVAL_OPTIONS_CRYPTO`` selects which __{iv}
    suffix the MA columns read; ``hl_lookback`` ∈ ``HL_LOOKBACK_OPTIONS_CRYPTO``
    selects the suffix for the H/L columns. Both flip purely client-side via
    JsCode valueGetter — no server recompute when the user changes window.
    """
    SHORT_KEY = f"_ma{short_ma}"             # MA10 gap %
    SHORT_SLOPE_KEY = f"_slope{short_ma}"    # MA10 angle (°)
    LONG_KEY = f"_ma{long_ma}"               # MA20 gap %
    LONG_SLOPE_KEY = f"_slope{long_ma}"      # MA20 angle (°)
    HIGH_KEY = "_high_pct"
    LOW_KEY = "_low_pct"
    REC_KEY = "_rec"   # display-only; reads rec_label/rec_score/rec_kind via JS

    VISIBLE_ORDER = [
        "symbol",
        "markPrice", "quoteVolume", "marketCap", "fundingRate",
        SHORT_KEY, SHORT_SLOPE_KEY, LONG_KEY, LONG_SLOPE_KEY,
        HIGH_KEY, LOW_KEY,
        REC_KEY, "note",
    ]

    df_grid = df.copy()
    for placeholder in (SHORT_KEY, SHORT_SLOPE_KEY, LONG_KEY, LONG_SLOPE_KEY,
                        HIGH_KEY, LOW_KEY, REC_KEY):
        if placeholder not in df_grid.columns:
            df_grid[placeholder] = None

    # Signed numeric columns always sort by |value| — gap%, slope°, High/Low%,
    # fundingRate. Sign matters for the cell color but the user wants to rank
    # by magnitude (biggest movers, biggest gaps), not by sign.
    signed_kw = {"comparator": JS_ABS_COMPARATOR}

    visible_present = [c for c in VISIBLE_ORDER if c in df_grid.columns]
    hidden_present = [c for c in df_grid.columns if c not in visible_present]
    df_grid = df_grid[visible_present + hidden_present]

    gob = GridOptionsBuilder.from_dataframe(df_grid)
    gob.configure_default_column(
        resizable=True, sortable=True, filter=False,
        editable=False, suppressMovable=False,
        # Hide the per-column header menu (hamburger) on every column. Both
        # keys for AG Grid v28 (suppressMenu) and v32+ (suppressHeaderMenuButton)
        # so the option works regardless of the bundled ag-grid version.
        suppressMenu=True, suppressHeaderMenuButton=True,
        cellStyle={"display": "flex", "alignItems": "center"},
    )

    # ── Symbol (pinned left, doubles as checkbox column) ──
    gob.configure_column(
        "symbol", headerName="Symbol", pinned="left",
        width=95, minWidth=75,
        checkboxSelection=True, headerCheckboxSelection=False,
    )

    # ── Mark / 거래대금 / 시가총액 / Funding ──
    gob.configure_column(
        "markPrice", headerName="Mark", width=95,
        valueFormatter=JS_FMT_PRICE, type=["numericColumn"],
    )
    gob.configure_column(
        "quoteVolume", headerName="거래대금", width=80,
        valueFormatter=JS_FMT_MCAP, type=["numericColumn"],
    )
    gob.configure_column(
        "marketCap", headerName="시가총액", width=80,
        valueFormatter=JS_FMT_MCAP, type=["numericColumn"],
    )
    gob.configure_column(
        "fundingRate", headerName="Funding", width=62,
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"], **signed_kw,
    )

    # ── MA gap % + slope ° columns ──
    # Each MA gets a pair: gap % (price vs MA, signed) and slope ° (MA trend
    # angle, signed, price-independent). Both valueGetters key off the same
    # ma_interval suffix → flipping the MA Interval picker swaps all 4 cells
    # client-side in one shot.
    gob.configure_column(
        SHORT_KEY, headerName=f"MA{short_ma}갭", width=66,
        valueGetter=js_window_value_getter(f"pct_ma{short_ma}", ma_interval),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"], **signed_kw,
    )
    gob.configure_column(
        SHORT_SLOPE_KEY, headerName=f"MA{short_ma}∠", width=66,
        valueGetter=js_window_value_getter(f"slope{short_ma}", ma_interval),
        valueFormatter=JS_FMT_DEG, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"], **signed_kw,
    )
    gob.configure_column(
        LONG_KEY, headerName=f"MA{long_ma}갭", width=66,
        valueGetter=js_window_value_getter(f"pct_ma{long_ma}", ma_interval),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"], **signed_kw,
    )
    gob.configure_column(
        LONG_SLOPE_KEY, headerName=f"MA{long_ma}∠", width=66,
        valueGetter=js_window_value_getter(f"slope{long_ma}", ma_interval),
        valueFormatter=JS_FMT_DEG, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"], **signed_kw,
    )
    # ── HL columns (valueGetter reads `__{hl_lookback}` from row data) ──
    gob.configure_column(
        HIGH_KEY, headerName="High", width=58,
        valueGetter=js_window_value_getter("pct_off_high", hl_lookback),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"], **signed_kw,
    )
    gob.configure_column(
        LOW_KEY, headerName="Low", width=58,
        valueGetter=js_window_value_getter("pct_off_low", hl_lookback),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"], **signed_kw,
    )

    # ── 추천 (전략 점수, display-only) ──
    # rec_label / rec_score / rec_kind 컬럼이 row data 에 있어야 표시됨.
    # 크립토는 아직 recs 미계산 → 모든 셀이 "—" 로 렌더링 (자리만 잡아둠).
    gob.configure_column(
        REC_KEY, headerName="추천", width=98, minWidth=70,
        valueFormatter=JS_FMT_REC, cellStyle=JS_STYLE_REC,
        tooltipField="rec_detail",
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
        "domLayout": "normal",
        "animateRows": False,
        "suppressRowClickSelection": True,
        "rowSelection": "single",
        "enableCellTextSelection": True,
        # Auto-fit columns whenever the grid container resizes — fires on
        # window resize, sidebar toggle, and the layout shifts caused by
        # ``st.dialog`` opening/closing.
        #
        # While the chart dialog is open, the parent document briefly
        # reflows the iframe to a transient (narrower) width. If we re-fit
        # at that transient width, the columns get squeezed and stay
        # squeezed once the dialog closes — visually it looks like
        # "opening the chart shrinks the grid". Guard by checking the
        # parent document for an open Streamlit dialog and skipping the
        # fit while one is present. When the dialog closes, the iframe
        # restores to its real width and onGridSizeChanged fires again
        # (this time with no dialog) to re-fit correctly.
        "onGridSizeChanged": JsCode("""
function(params) {
  try {
    const top = window.parent && window.parent.document;
    if (top && (top.querySelector('[data-testid="stDialog"]') ||
                top.querySelector('div[role="dialog"]'))) {
      return;
    }
  } catch (e) {}
  params.api.sizeColumnsToFit();
}
"""),
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
/* Cap the entire page to viewport width and clip any overflow.
   Streamlit's wide layout sometimes lets nested blocks push the page
   wider than the viewport — this forces everything to fit. Without
   these caps, opening the chart dialog can briefly widen the page (body
   scrollbar removed by the dialog's overflow:hidden), the AgGrid iframe
   gets re-measured at the wider width, and after the dialog closes the
   iframe sticks at that width — columns then squeeze to fit the now-
   narrower visible viewport.

   ``overflow-y: scroll`` on <html> forces the vertical scrollbar to be
   reserved at all times. Without it, Streamlit's dialog sets
   ``body { overflow: hidden }`` while open, removing the scrollbar (~15px
   gutter) and reflowing the page wider; after close the gutter returns
   and the AgGrid iframe ends up narrower than before. Pinning the
   scrollbar gutter eliminates that toggle entirely. */
html {
  overflow-y: scroll !important;
}
html, body {
  overflow-x: hidden !important;
  max-width: 100vw !important;
}
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
.main,
.main .block-container,
[data-testid="stMainBlockContainer"] {
  max-width: 100% !important;
  overflow-x: hidden !important;
}
[data-testid="stCustomComponentV1"],
[data-testid="element-container"]:has(iframe) {
  width: 100% !important;
  max-width: 100% !important;
}
[data-testid="stCustomComponentV1"] iframe,
iframe[title*="aggrid"],
iframe[title*="st_aggrid"],
iframe[title*="ag_grid"] {
  width: 100% !important;
  max-width: 100% !important;
}
</style>
"""
