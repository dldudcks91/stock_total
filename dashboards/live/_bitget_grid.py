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

from dashboards._stock_grid import (
    JS_ABS_COMPARATOR,
    JS_FMT_REC,
    JS_STYLE_REC,
    SLOPE_THRESHOLDS,
    apply_flex_layout,
    js_fmt_slope_arrow,
    js_style_slope,
)


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
    "holdingAmount": "OI (coin)",
    "indexPrice": "Index",
    "askPr": "Ask",
    "bidPr": "Bid",
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
  return pct.toFixed(1) + '%';
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


# ---------------------------------------------------------------------------
# Grid options builder
# ---------------------------------------------------------------------------

#  TF × MA 고정 컬럼 — (interval, period) 8쌍. apply_current_prices 가
#  만드는 ``pct_ma{period}__{interval}`` (price vs MA 갭 %) 을 직접 읽는다.
#  헤더 라벨: 1h/4h 소문자, 1D/1W 대문자.
_TF_MA_SPECS: list[tuple[str, int]] = [
    ("1d", 10), ("1d", 20),
    ("1w", 10), ("1w", 20),
    ("1M", 10), ("1M", 20),
]
_IV_HEADER = {"1d": "1d", "1w": "1W", "1M": "1M"}

# 슬로프 6개 (KR/US 와 동일한 1d/1w/1M × MA10/20). 임계값/표시는 _stock_grid 와
# 공유 — js_fmt_slope_arrow / js_style_slope 가 ▲/■/▼ + 색을 담당.
_SLOPE_TF_MA_SPECS: list[tuple[str, int]] = [
    ("1d", 10), ("1d", 20),
    ("1w", 10), ("1w", 20),
    ("1M", 10), ("1M", 20),
]
# 헤더는 D10/D20/W10/W20/M10/M20 (일/주/월 × MA10/20 영문 약어).
_SLOPE_IV_HEADER = {"1d": "D", "1w": "W", "1M": "M"}


def build_grid_options(
    df: pd.DataFrame,
    selected_symbol: Optional[str],
    star_codes: Optional[set] = None,
) -> tuple[pd.DataFrame, dict]:
    """**DEPRECATED — no longer wired.** The Bitget tab now uses the shared
    :func:`dashboards._stock_grid.build_stock_grid_options` so its grid is
    identical to KOSPI/NASDAQ (merged gap+slope 6 cols + 터치 + G1~G4). Kept
    only for reference; safe to delete once the new layout is confirmed.

    Construct (df_reordered, gridOptions) for the Bitget AgGrid.

    Column order (left → right, displayed):
        ▸ checkbox + Symbol (pinned), Mark, 거래대금, 시총,
          1h-MA10, 1h-MA20, 4h-MA10, 4h-MA20,
          1D-MA10, 1D-MA20, 1W-MA10, 1W-MA20  (각 TF×MA 의 price vs MA 갭 %),
          MA20(게이트),
          일MA10, 일MA20, 주MA10, 주MA20, 월MA10, 월MA20
            (각 MA 의 기울기 — ▲/■/▼ + 색)
    """
    REC_KEY = "_rec"   # display-only; reads gate_pass via JS (ma_touch 게이트)
    STAR_KEY = "_star"  # display-only ⭐ column (membership in star_codes)
    MA_COLS = [f"pct_ma{p}__{iv}" for iv, p in _TF_MA_SPECS]
    SLOPE_COLS = [f"slope_pct_ma{p}__{iv}" for iv, p in _SLOPE_TF_MA_SPECS]

    VISIBLE_ORDER = [
        "symbol",
        "markPrice", "quoteVolume", "marketCap",
        *MA_COLS,
        REC_KEY,
        *SLOPE_COLS,
        STAR_KEY,
    ]

    df_grid = df.copy()
    star_set = {str(s) for s in (star_codes or set())}
    df_grid[STAR_KEY] = df_grid["symbol"].astype(str).map(
        lambda s: "⭐" if s in star_set else ""
    )
    for placeholder in (*MA_COLS, REC_KEY, *SLOPE_COLS):
        if placeholder not in df_grid.columns:
            df_grid[placeholder] = None

    # Signed numeric columns always sort by |value| — gap%. Sign matters for the
    # cell color but the user wants to rank by magnitude (biggest gaps), not sign.
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
        width=84, minWidth=64,
        checkboxSelection=True, headerCheckboxSelection=False,
    )

    # ── ⭐ 별표 (display-only) — 차트 헤더 토글로 켜고/끄고, 여기선 표시만 ──
    gob.configure_column(
        STAR_KEY, headerName="⭐", pinned="right",
        width=40, minWidth=34, maxWidth=48, sortable=True,
        cellStyle={"textAlign": "center", "display": "flex",
                   "alignItems": "center", "justifyContent": "center"},
        headerTooltip="별표(즐겨찾기) — 차트 헤더의 ⭐ 버튼으로 토글",
    )

    # ── Mark / 거래대금 / 시가총액 ──
    gob.configure_column(
        "markPrice", headerName="Mark", width=95,
        valueFormatter=JS_FMT_PRICE, type=["numericColumn"],
    )
    gob.configure_column(
        "quoteVolume", headerName="거래대금", width=62,
        valueFormatter=JS_FMT_MCAP, type=["numericColumn"],
    )
    gob.configure_column(
        "marketCap", headerName="시가총액", width=62,
        valueFormatter=JS_FMT_MCAP, type=["numericColumn"],
    )

    # ── TF × MA 갭 % (8 고정 컬럼) ──
    # 각 컬럼은 df 의 ``pct_ma{p}__{iv}`` 를 그대로 읽는다 (토글 없음).
    for iv, p in _TF_MA_SPECS:
        col = f"pct_ma{p}__{iv}"
        gob.configure_column(
            col, headerName=f"{_IV_HEADER[iv]}-MA{p}", width=64, minWidth=52,
            valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
            type=["numericColumn"], **signed_kw,
        )

    # ── ma_touch 게이트 (display-only) ──
    # gate_pass 컬럼이 row data 에 있어야 ● 표시됨. 없으면 공백.
    gob.configure_column(
        REC_KEY, headerName="터치", width=64, minWidth=48,
        valueFormatter=JS_FMT_REC, cellStyle=JS_STYLE_REC,
    )

    # ── MA10/MA20 슬로프 6개 (일/주/월 × MA10/MA20) ──
    # ▲(양) / ■(평탄) / ▼(음) + 색. 임계값 % per bar: 일 ±0.10 / 주 ±0.30 /
    # 월 ±0.80. 헤더 클릭 정렬은 signed 값 기준 (양수 큰 게 위).
    for iv, p in _SLOPE_TF_MA_SPECS:
        col = f"slope_pct_ma{p}__{iv}"
        th = SLOPE_THRESHOLDS[iv]
        gob.configure_column(
            col, headerName=f"{_SLOPE_IV_HEADER[iv]}{p}", width=44, minWidth=34,
            valueFormatter=js_fmt_slope_arrow(th),
            cellStyle=js_style_slope(th),
            type=["numericColumn"],
            headerTooltip=f"{iv} MA{p} 기울기 (% per bar, "
                          f"|±{th:g}| 이내 평탄)",
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
    })
    # flex 레이아웃으로 컬럼 폭을 컨테이너에 자동 분배 — sizeColumnsToFit 처럼
    # "한 시점 폭으로 고정"하지 않으므로 fragment 리런·차트 다이얼로그 reflow 때
    # 좁은 폭으로 굳지 않는다 (차트 팝업으로 표가 작아지던 문제 포함).
    apply_flex_layout(opts)
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
/* Chart dialog prev/next (‹ ›) nav buttons — compact, square-ish */
[class*="chart_nav_prev"] button,
[class*="chart_nav_next"] button {
  padding: 0 !important;
  min-height: 30px !important;
  height: 30px !important;
  font-size: 18px !important;
  line-height: 1 !important;
  font-weight: 700 !important;
}
/* Chart dialog position jump box — compact text_input matching the ‹ › height */
[class*="_next__pos"] input {
  padding: 2px 6px !important;
  height: 30px !important;
  min-height: 30px !important;
  text-align: center !important;
  font-size: 13px !important;
}
/* Chart line legend overlay — anchor the absolute legend to the chart's
   top-left and collapse the gap so the chart sits flush under it. */
.st-key-chart_legend_wrap { position: relative !important; }
.st-key-chart_legend_wrap [data-testid="stVerticalBlock"] { gap: 0 !important; }
/* Dialog X button — 우상단 코너에서 위·오른쪽 여백이 같아야 대칭. */
div[role="dialog"] button[aria-label="Close"],
[data-testid="stDialog"] button[aria-label="Close"] {
  top: 0.5rem !important;
  right: 0.5rem !important;
  margin: 0 !important;
}
/* 차트 헤더 ⭐ 토글 — 카드/보더 다 벗기고 통통한 ⭐ 만 남긴다. OFF 는 grayscale. */
[class*="chart_star_wrap_"] {
  margin: 0 !important;
  padding: 0 !important;
}
[class*="chart_star_wrap_"] button {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  padding: 0 !important;
  min-height: 30px !important;
  height: 30px !important;
  line-height: 1 !important;
  font-size: 24px !important;
}
[class*="chart_star_wrap_"] button:hover {
  background: rgba(255, 215, 0, 0.10) !important;
  border-radius: 50% !important;
}
[class*="chart_star_wrap_off"] button {
  filter: grayscale(1) opacity(0.35);
}
[class*="chart_star_wrap_off"] button:hover {
  filter: opacity(0.75);
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
