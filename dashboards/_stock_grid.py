"""Shared Bitget-style grid helpers for stock pages (KOSPI / NASDAQ).

Encapsulates the parts that are identical between the two stock dashboards:
- cache tail loader (capitalized OHLC columns)
- single-pass all-windows compute, **wall-clock anchored** — prev_Nd, MA,
  and H/L values are taken relative to *today*, not to the cache's last bar
- AgGrid JsCode formatters + value getters
- Bitget/TradingView-style lightweight chart renderer

The two stock pages stay thin: they only own the live-price fetcher (Naver)
and the page-level layout / filter bar / dialog wiring.

Wall-clock anchoring
--------------------
``compute_reference_levels`` takes a ``now_ts`` anchor (default = today
midnight in local time). Every derived value is computed "as of" that
timestamp:

  - ``prev_{n}d`` = close of the bar at-or-before ``now_ts - (n+1) days``,
    within ``tol_days`` tolerance (covers weekends and 명절 휴장 갭). The
    extra ``+1`` shift avoids returning the same bar that the live price
    already represents (which would yield ``pct_1d == 0`` whenever the
    market is closed and Naver's live price equals the cache's last close).
  - ``ma{p}__{iv}`` = SMA of the last ``p`` resampled-to-iv closes ending
    at-or-before ``now_ts``.
  - ``high__{lb}`` / ``low__{lb}`` = max/min over bars in
    ``[now_ts - lookback, now_ts]``.

This matches the crypto-side anchoring in
:mod:`dashboards.live._crypto_compute` so KOSPI/NASDAQ/Bitget all share
the same "today is today" semantics. Before this change, stock refs were
anchored to the cache's *last bar* — meaning a Friday cache viewed on
Tuesday would label "1d %" as "Friday vs Thursday" (off by 4 trading days).
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

# 슬로프 임계값 (% per bar). |slope_pct| ≤ 임계 → ■(평탄), > +임계 → ▲(양),
# < -임계 → ▼(음). MA 1봉 차분을 직전 MA 로 나눠 정규화한 값이라 자산 무관.
# 사용자 합의: 차트로 직접 검증하므로 ▲/■/▼ 분류만 적절히 되면 됨.
SLOPE_THRESHOLDS: dict[str, float] = {"1d": 0.10, "1w": 0.30, "1M": 0.80}

# Tail size handed to the cache loader. 5y (≈ 1260 trading days) covers the
# longest HL lookback; 20 monthly bars (≈ 440 trading days) for 1M MA20 fits
# comfortably under this.
CACHE_TAIL_N: int = 1500

# Chart bar spacing (px per candle) for the initial view. The vendored
# streamlit-lightweight-charts frontend is patched (scripts/_common/patch_lwc.py)
# so it scrolls to the latest bar instead of fitContent() — we now send the FULL
# history and the chart opens zoomed on recent bars at this spacing, with the
# user able to pan left through everything (exchange style). Bigger = fewer,
# wider candles initially.
DEFAULT_BAR_SPACING: float = 8.0

# Kept for backward-compat: previously the series was sliced to this many bars
# before handing to the chart (the old fitContent behavior). No longer sliced.
DEFAULT_VISIBLE_BARS: int = 200


# ---------------------------------------------------------------------------
# Cache loader (capitalized OHLC — KR/US schema)
# ---------------------------------------------------------------------------

def load_cache_tails(path: Path, n: int) -> Optional[pd.DataFrame]:
    """Read the last ``n`` rows of (Close, High, Low) from a stock parquet.

    Returns a DataFrame indexed by date (oldest→newest) or ``None`` on
    miss/empty. The DatetimeIndex is required by
    ``compute_reference_levels`` for weekly/monthly resampling and
    calendar-based lookback windows.
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


# Default wall-clock-vs-cache tolerance for stock anchors. Covers normal
# weekend (2d), long weekend (3d), and most Korean / US single-week holiday
# stretches. 추석 / 설 연휴 (≈5–7d) and Thanksgiving + weekend (4d) fit.
# If the cache is older than this from the target date, the value is None
# rather than mislabeled.
DEFAULT_TOL_DAYS: int = 7


def _close_at_or_before(
    df: pd.DataFrame, target: pd.Timestamp, tol: pd.Timedelta,
) -> Optional[float]:
    """Return ``df['Close']`` for the bar whose index is ≤ ``target``, within ``tol``.

    Used for wall-clock anchored prev-close lookups. If the most recent bar
    at-or-before ``target`` is older than ``tol``, returns ``None`` — the
    cache doesn't actually cover that point in time.
    """
    if df.empty:
        return None
    pos = df.index.searchsorted(target, side="right") - 1
    if pos < 0:
        return None
    found_ts = df.index[pos]
    if (target - found_ts) > tol:
        return None
    val = float(df["Close"].iat[pos])
    if not np.isfinite(val):
        return None
    return val


# ---------------------------------------------------------------------------
# Single-pass compute: fixed period % + per-interval MA + per-lookback H/L Δ%
# ---------------------------------------------------------------------------

def compute_reference_levels(
    symbols: list[str],
    cache_loader: Callable[[str, int], Optional[pd.DataFrame]],
    *,
    now_ts: Optional[pd.Timestamp] = None,
    tol_days: int = DEFAULT_TOL_DAYS,
    ma_intervals: list[str] = MA_INTERVAL_OPTIONS,
    hl_lookbacks: list[str] = HL_LOOKBACK_OPTIONS,
    periods_d: list[int] = PERIODS_D,
    ma_periods: tuple[int, int] = MA_PERIODS,
) -> pd.DataFrame:
    """Price-independent reference levels, **wall-clock anchored at ``now_ts``**.

    ``now_ts`` defaults to today midnight (naive, local time). All values are
    computed relative to that anchor — not to the cache's last bar:

      - ``prev_{n}d``: close of the bar at-or-before ``now_ts - n days``,
        within ``tol_days`` (휴장 갭 허용; over the threshold → None).
      - ``ma{short|long}__{iv}``: SMA of the last ``short`` / ``long``
        resampled-to-iv closes ending at-or-before ``now_ts``. Bars
        strictly after ``now_ts`` are dropped first so future bars (if any)
        don't leak in.
      - ``high__{lb}`` / ``low__{lb}``: max(High) / min(Low) over bars in
        the calendar window ``[now_ts - lookback, now_ts]``.

    Caller pairs the result with ``apply_current_prices`` to derive pct_*
    columns. Splitting refs (price-independent, heavy) from pct (cheap)
    lets the heavy pass be cached on disk by
    :mod:`dashboards._precompute` keyed on ``data_mtime`` + a wall-clock
    bucket — so live-price refreshes only rerun the cheap pass.
    """
    if now_ts is None:
        now_ts = pd.Timestamp.now().normalize()
    tol = pd.Timedelta(days=tol_days)
    short, long_ = ma_periods

    prev_keys = [f"prev_{n}d" for n in periods_d]
    ma_cols: list[str] = []
    slope_cols: list[str] = []
    for iv in ma_intervals:
        ma_cols.extend([f"ma{short}__{iv}", f"ma{long_}__{iv}"])
        slope_cols.extend([f"slope_pct_ma{short}__{iv}", f"slope_pct_ma{long_}__{iv}"])
    hl_cols: list[str] = []
    for lb in hl_lookbacks:
        hl_cols.extend([f"high__{lb}", f"low__{lb}"])
    none_cols = prev_keys + ma_cols + slope_cols + hl_cols

    rows: list[dict[str, Any]] = []
    for sym in symbols:
        row: dict[str, Any] = {"symbol": sym}
        for k in none_cols:
            row[k] = None

        df = cache_loader(sym, CACHE_TAIL_N)
        if df is None or df.empty:
            rows.append(row)
            continue

        # Drop any forward-looking bars so MA / HL / prev never see the future.
        df = df.loc[df.index <= now_ts]
        if df.empty:
            rows.append(row)
            continue

        # ── prev close per fixed period (wall-clock anchored, calendar days) ──
        # Shift by (n + 1) days, not n, so prev_{n}d never lands on the same
        # bar as the current price's effective reference. Concrete case: on
        # 2026-05-15 the KR cache's last bar is 05-14 and Naver's live price
        # is also 05-14's close (market closed). Target = now - 1d = 05-14
        # would return that same bar → prev_1d == cur → pct_1d = 0%. Shifting
        # by (n + 1) drops the target to 05-13, giving the real prior-day
        # close. Matches the crypto convention in ``_crypto_compute``.
        for n, key in zip(periods_d, prev_keys):
            target = now_ts - pd.Timedelta(days=n + 1)
            prev = _close_at_or_before(df, target, tol)
            if prev is not None:
                row[key] = prev

        # ── Per-interval MA (SMA on resampled bars up to now_ts) ──
        # Filter applied above already caps df at now_ts, so resample-then-tail
        # gives the most recent N bars ending at-or-before now_ts.
        for iv in ma_intervals:
            if iv == "1d":
                bar_close = df["Close"].to_numpy(dtype=np.float64, copy=False)
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
                ma_s = float(bar_close[-short:].mean())
                if np.isfinite(ma_s):
                    row[f"ma{short}__{iv}"] = ma_s
                    # slope_pct = (MA[t] − MA[t-1]) / MA[t-1] × 100 (% per bar).
                    # MA[t-1] = SMA over bars [-short-1 .. -1] (한 봉 뒤 시점).
                    if bar_close.size >= short + 1:
                        ma_s_back = float(bar_close[-short - 1:-1].mean())
                        if np.isfinite(ma_s_back) and ma_s_back != 0:
                            row[f"slope_pct_ma{short}__{iv}"] = (
                                (ma_s - ma_s_back) / ma_s_back * 100.0
                            )
            if bar_close.size >= long_:
                ma_l = float(bar_close[-long_:].mean())
                if np.isfinite(ma_l):
                    row[f"ma{long_}__{iv}"] = ma_l
                    if bar_close.size >= long_ + 1:
                        ma_l_back = float(bar_close[-long_ - 1:-1].mean())
                        if np.isfinite(ma_l_back) and ma_l_back != 0:
                            row[f"slope_pct_ma{long_}__{iv}"] = (
                                (ma_l - ma_l_back) / ma_l_back * 100.0
                            )

        # ── Per-lookback High/Low (now_ts-anchored calendar window) ──
        for lb in hl_lookbacks:
            cutoff = now_ts - pd.Timedelta(days=_lookback_to_days(lb))
            mask = df.index >= cutoff   # df.index already ≤ now_ts from filter above
            if not mask.any():
                continue
            row[f"high__{lb}"] = float(df.loc[mask, "High"].max())
            row[f"low__{lb}"] = float(df.loc[mask, "Low"].min())

        rows.append(row)
    return pd.DataFrame(rows)


def apply_current_prices(
    refs: pd.DataFrame,
    current_prices: dict[str, float],
    *,
    ma_intervals: list[str] = MA_INTERVAL_OPTIONS,
    hl_lookbacks: list[str] = HL_LOOKBACK_OPTIONS,
    periods_d: list[int] = PERIODS_D,
    ma_periods: tuple[int, int] = MA_PERIODS,
) -> pd.DataFrame:
    """Vectorized: ``refs`` (prev/ma/high/low) + current prices → pct_* columns.

    Output columns:
      ``pct_{n}d``, ``pct_ma{p}__{iv}``,
      ``high__{lb}``, ``low__{lb}``, ``pct_off_high__{lb}``, ``pct_off_low__{lb}``.

    This is the cheap per-rerun pass — does not touch parquet, only does a
    handful of vectorized series ops over the reference DataFrame.
    """
    short, long_ = ma_periods
    out = pd.DataFrame({"symbol": refs["symbol"].astype(str)})

    cur = refs["symbol"].astype(str).map(current_prices).astype(float)
    cur = cur.where(np.isfinite(cur))

    def _pct(ref_col: str) -> pd.Series:
        if ref_col not in refs.columns:
            return pd.Series([None] * len(refs), index=refs.index, dtype="float64")
        r = pd.to_numeric(refs[ref_col], errors="coerce")
        r = r.where((r != 0) & np.isfinite(r))
        return (cur - r) / r

    for n in periods_d:
        out[f"pct_{n}d"] = _pct(f"prev_{n}d")
    for iv in ma_intervals:
        out[f"pct_ma{short}__{iv}"] = _pct(f"ma{short}__{iv}")
        out[f"pct_ma{long_}__{iv}"] = _pct(f"ma{long_}__{iv}")
        # Slope is price-independent — pass through unchanged so it travels
        # alongside in the merged frame the grid reads.
        for p in (short, long_):
            sc = f"slope_pct_ma{p}__{iv}"
            if sc in refs.columns:
                out[sc] = refs[sc].values
    for lb in hl_lookbacks:
        hi_col, lo_col = f"high__{lb}", f"low__{lb}"
        if hi_col in refs.columns:
            out[hi_col] = refs[hi_col].values
            out[f"pct_off_high__{lb}"] = _pct(hi_col)
        if lo_col in refs.columns:
            out[lo_col] = refs[lo_col].values
            out[f"pct_off_low__{lb}"] = _pct(lo_col)
    return out


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

# Custom sort comparator: sort by |value| instead of signed value, so clicking
# an MA gap column header surfaces the biggest gaps (positive AND negative) at
# the top. Nulls/NaN always sink to the bottom. (Bitget grid imports this.)
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

JS_FMT_PCT = JsCode("""
function(params) {
  const v = params.value;
  if (v == null || Number.isNaN(v)) return '—';
  const pct = v * 100;
  return pct.toFixed(1) + '%';
}
""")


def apply_flex_layout(opts: dict) -> None:
    """``width`` 기반 컬럼 폭을 ``flex`` 비율로 변환 (in-place).

    AgGrid 의 ``sizeColumnsToFit`` / ``fit_columns_on_grid_load`` 은 호출 시점의
    컨테이너 폭을 한 번 측정해 컬럼 폭을 **고정**한다. Streamlit fragment 리런
    (체크박스 토글 등) 이나 ``st.dialog`` (차트 팝업) 가 iframe 폭을 ~1프레임
    좁게 보고하는 순간 그 값으로 굳어 "표가 작아지는" 문제가 생긴다.

    ``flex`` 는 CSS flexbox 처럼 **렌더 시마다 현재 컨테이너 폭을 비율로 분배**
    하므로 좁은 폭으로 굳지 않는다. 각 컬럼의 기존 ``width`` 를 그대로 flex 비율로
    옮겨 (width=72 → flex=72) 폭 비율은 유지하면서 자동 반응성을 얻는다.

    pinned (좌측 고정 Symbol) 과 hidden 컬럼은 고정 폭을 유지해야 하므로 제외.
    """
    # st_aggrid 가 기본으로 주입하는 ``autoSizeStrategy`` (fitCellContents) 는
    # 로드 시 컬럼을 셀 내용 길이에 맞춰 고정해 flex 를 무력화하므로 제거한다.
    opts.pop("autoSizeStrategy", None)
    for cd in opts.get("columnDefs", []):
        if cd.get("pinned") or cd.get("hide"):
            continue
        w = cd.get("width")
        if w:
            cd["flex"] = w
            cd.pop("width", None)

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

# ma_touch 게이트 셀 — 통과 시 초록 ●, 미통과 공백.
# gate_pass = 오늘 ma_touch 가 ≥1 TF 통과 (/recs 스킬과 동일 신호).
# 산출: scripts._common.recommend_runner → dashboards._precompute → _recs.parquet.gate_pass
JS_FMT_REC = JsCode("""
function(params) {
  const d = params.data || {};
  return d.gate_pass ? '●' : '';
}
""")

JS_STYLE_REC = JsCode("""
function(params) {
  const d = params.data || {};
  return d.gate_pass
    ? {color: '#16A34A', fontWeight: '700', textAlign: 'center'}
    : {textAlign: 'center'};
}
""")


# Slope cell — ▲ (양) / ■ (평탄) / ▼ (음). threshold 는 % per bar 기준이며
# 컬럼별로 다른 값이 들어가야 하므로 (일/주/월) 헬퍼로 생성한다.

def js_fmt_slope_arrow(threshold: float) -> JsCode:
    return JsCode(
        "function(params){"
        "  const v=params.value;"
        "  if(v==null||Number.isNaN(v)) return '—';"
        f"  if(v > {threshold})  return '▲';"
        f"  if(v < -{threshold}) return '▼';"
        "  return '■';"
        "}"
    )


def js_style_slope(threshold: float) -> JsCode:
    return JsCode(
        "function(params){"
        "  const v=params.value;"
        "  const base={textAlign:'center',fontWeight:'700'};"
        "  if(v==null||Number.isNaN(v)) return Object.assign({},base,{color:'#888',fontWeight:'400'});"
        f"  if(v > {threshold})  return Object.assign({{}},base,{{color:'#2A9D8F'}});"
        f"  if(v < -{threshold}) return Object.assign({{}},base,{{color:'#E63946'}});"
        "  return Object.assign({},base,{color:'#888',fontWeight:'400'});"
        "}"
    )


# ---------------------------------------------------------------------------
# AgGrid options builder (stock variant)
# ---------------------------------------------------------------------------

# TF × MA 고정 컬럼 — (interval, period) 6쌍. apply_current_prices 가 만드는
# ``pct_ma{period}__{interval}`` (price vs MA 갭 %) 을 직접 읽는다. 주식은 1h/4h
# 봉이 없어 1D/1W/1M 만 (헤더는 모두 대문자).
_STOCK_TF_MA_SPECS: list[tuple[str, int]] = [
    ("1d", 10), ("1d", 20),
    ("1w", 10), ("1w", 20),
    ("1M", 10), ("1M", 20),
]
_STOCK_IV_HEADER = {"1d": "1D", "1w": "1W", "1M": "1M"}

# 슬로프 6개 — TF×MA 갭% 와 같은 6쌍을 그대로 재사용. 헤더는 한국어 약어
# (일/주/월) + MA10/20 으로 좁은 컬럼에 맞춤. ▲/■/▼ 표시는 셀 렌더러 담당.
_SLOPE_IV_HEADER = {"1d": "일", "1w": "주", "1M": "월"}


def build_stock_grid_options(
    df: pd.DataFrame,
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
    star_codes: Optional[set] = None,  # codes/symbols to mark with ⭐
) -> tuple[pd.DataFrame, dict]:
    """Build (reordered df, gridOptions) matching the Bitget layout for stocks.

    Visible column order (left → right):
        ▸ Symbol (pinned + checkbox), Name, Last, 거래대금, 시총,
          1D-MA10, 1D-MA20, 1W-MA10, 1W-MA20, 1M-MA10, 1M-MA20
            (각 TF×MA 의 price vs MA 갭 %),
          MA20(게이트),
          일MA10, 일MA20, 주MA10, 주MA20, 월MA10, 월MA20
            (각 MA 의 기울기 — ▲/■/▼ + 색)

    이전의 MA Interval / HL Lookback 토글, 기간 수익률(1d~140d %), High/Low%
    컬럼은 모두 제거됨. 6개 TF×MA 갭 컬럼은 토글 없이 항상 표시된다 (값은
    ``pct_ma{p}__{iv}`` df 컬럼을 그대로 field 로 읽음). 주식은 1h/4h 봉이
    없어 1D/1W/1M 만 — crypto(_bitget_grid) 의 1h/4h/1d/1w 와 같은 방식.
    """
    REC_KEY = "_rec"   # display-only column; reads gate_pass via JS (ma_touch 게이트)
    STAR_KEY = "_star"  # display-only ⭐ column (membership in star_codes)
    MA_COLS = [f"pct_ma{p}__{iv}" for iv, p in _STOCK_TF_MA_SPECS]
    SLOPE_COLS = [f"slope_pct_ma{p}__{iv}" for iv, p in _STOCK_TF_MA_SPECS]

    visible_order: list[str] = [symbol_col, STAR_KEY]
    if name_col:
        visible_order.append(name_col)
    visible_order.append(price_col)
    if volume_col:
        visible_order.append(volume_col)
    if market_cap_col:
        visible_order.append(market_cap_col)
    visible_order.extend(MA_COLS)
    visible_order.append(REC_KEY)
    visible_order.extend(SLOPE_COLS)

    df_grid = df.copy()
    star_set = {str(s) for s in (star_codes or set())}
    df_grid[STAR_KEY] = df_grid[symbol_col].astype(str).map(
        lambda s: "⭐" if s in star_set else ""
    )
    for placeholder in (*MA_COLS, REC_KEY, *SLOPE_COLS):
        if placeholder not in df_grid.columns:
            df_grid[placeholder] = None

    visible_present = [c for c in visible_order if c in df_grid.columns]
    hidden_present = [c for c in df_grid.columns if c not in visible_present]
    df_grid = df_grid[visible_present + hidden_present]

    gob = GridOptionsBuilder.from_dataframe(df_grid)
    gob.configure_default_column(
        resizable=True, sortable=True, filter=False,
        editable=False, suppressMovable=False,
        # Hide the per-column header menu (hamburger ☰, 가로줄 3개) on every
        # column so it doesn't cover the header label. Both keys for AG Grid
        # v28 (suppressMenu) and v32+ (suppressHeaderMenuButton) — matches
        # _bitget_grid so KOSPI/NASDAQ behave like Bitget.
        suppressMenu=True, suppressHeaderMenuButton=True,
        cellStyle={"display": "flex", "alignItems": "center"},
    )

    # All columns use plain ``width`` — column auto-fit is handled at the
    # AgGrid call site via ``fit_columns_on_grid_load=True`` plus the
    # onGridSizeChanged handler below, so the grid always exactly fills its
    # container width (no horizontal scroll, no trailing gap).
    gob.configure_column(
        symbol_col, headerName=symbol_header, pinned="left",
        width=110, minWidth=70,
        checkboxSelection=True, headerCheckboxSelection=False,
    )

    # ── ⭐ 별표 (display-only) — 차트 헤더 토글로 켜고/끄고, 여기선 표시만 ──
    gob.configure_column(
        STAR_KEY, headerName="⭐", pinned="left",
        width=40, minWidth=34, maxWidth=48, sortable=True,
        cellStyle={"textAlign": "center", "display": "flex",
                   "alignItems": "center", "justifyContent": "center"},
        headerTooltip="별표(즐겨찾기) — 차트 헤더의 ⭐ 버튼으로 토글",
    )

    if name_col:
        # 긴 종목명(특히 NASDAQ 영문명)이 칸을 넘지 않도록 말줄임(…) 처리.
        # 기본 cellStyle 의 display:flex 를 빼고 lineHeight 로 수직 가운데 정렬해
        # ag-grid 의 text-overflow:ellipsis 가 정상 동작하게 한다.
        gob.configure_column(
            name_col, headerName=name_header, width=160, minWidth=80,
            cellStyle=JsCode(
                "function(params){ return {lineHeight:'34px', whiteSpace:'nowrap',"
                " overflow:'hidden', textOverflow:'ellipsis'}; }"
            ),
        )

    price_fmt = JS_FMT_PRICE_INT if price_format == "int" else JS_FMT_PRICE_DEC
    gob.configure_column(
        price_col, headerName=price_header, width=95, minWidth=60,
        valueFormatter=price_fmt, type=["numericColumn"],
    )

    vol_fmt = JS_FMT_MILLIONS if volume_format == "millions" else JS_FMT_INT
    mcap_fmt = JS_FMT_MILLIONS if market_cap_format == "millions" else JS_FMT_INT
    vol_width = 130 if volume_format == "millions" else 120
    mcap_width = 130 if market_cap_format == "millions" else 120
    if volume_col:
        gob.configure_column(
            volume_col, headerName=volume_header, width=vol_width, minWidth=70,
            valueFormatter=vol_fmt, type=["numericColumn"],
        )
    if market_cap_col:
        gob.configure_column(
            market_cap_col, headerName=market_cap_header, width=mcap_width, minWidth=70,
            valueFormatter=mcap_fmt, type=["numericColumn"],
        )

    # ── TF × MA 갭 % (6 고정 컬럼) ──
    # 각 컬럼은 df 의 ``pct_ma{p}__{iv}`` 를 그대로 읽는다 (토글 없음).
    # 헤더 클릭 정렬은 |value| 기준 (부호 무시, 가장 큰 갭이 위로) — Bitget 과 동일.
    for iv, p in _STOCK_TF_MA_SPECS:
        col = f"pct_ma{p}__{iv}"
        gob.configure_column(
            col, headerName=f"{_STOCK_IV_HEADER[iv]}-MA{p}", width=72, minWidth=52,
            valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
            type=["numericColumn"], comparator=JS_ABS_COMPARATOR,
        )

    # ── ma_touch 게이트 (display-only) ──
    # gate_pass 컬럼이 row data 에 있어야 ● 표시됨. 없으면 공백.
    gob.configure_column(
        REC_KEY, headerName="터치", width=64, minWidth=48,
        valueFormatter=JS_FMT_REC, cellStyle=JS_STYLE_REC,
    )

    # ── MA10/MA20 슬로프 6개 (일/주/월 × MA10/MA20) ──
    # 각 셀은 ▲(양) / ■(평탄) / ▼(음) + 색상. 임계값 (% per bar):
    # 일봉 ±0.10 / 주봉 ±0.30 / 월봉 ±0.80. 셀 내부는 슬로프 값(% per bar)을
    # numeric 으로 들고 있으므로 헤더 클릭 정렬은 signed 값 기준 (양수 큰 게 위).
    for iv, p in _STOCK_TF_MA_SPECS:
        col = f"slope_pct_ma{p}__{iv}"
        th = SLOPE_THRESHOLDS[iv]
        gob.configure_column(
            col, headerName=f"{_SLOPE_IV_HEADER[iv]}MA{p}", width=44, minWidth=34,
            valueFormatter=js_fmt_slope_arrow(th),
            cellStyle=js_style_slope(th),
            type=["numericColumn"],
            headerTooltip=f"{_SLOPE_IV_HEADER[iv]}봉 MA{p} 기울기 (% per bar, "
                          f"|±{th:g}| 이내 평탄)",
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
        "domLayout": "normal",
        "animateRows": False,
        "suppressRowClickSelection": True,
        "rowSelection": "single",
        "enableCellTextSelection": True,
    })
    # flex 레이아웃으로 컬럼 폭을 컨테이너에 자동 분배 — sizeColumnsToFit 처럼
    # "한 시점 폭으로 고정"하지 않으므로 fragment 리런·차트 다이얼로그 reflow 때
    # 좁은 폭으로 굳지 않는다. (자세히: _apply_flex_layout)
    apply_flex_layout(opts)
    return df_grid, opts


# ---------------------------------------------------------------------------
# TradingView-style chart renderer for stocks (capitalized OHLC columns)
# ---------------------------------------------------------------------------

def chart_legend_html(entries: list) -> str:
    """Top-left overlay legend for the chart — list of ``(label, color)``.

    lightweight-charts has no built-in top-left legend; its per-series
    ``title`` renders at the line's right end (next to the price axis). We drop
    those titles and overlay this HTML legend instead, absolutely positioned in
    the top-left of the chart (the wrapping container is ``position:relative``
    via the page CSS). ``pointer-events:none`` so it never blocks the chart.
    """
    spans = "".join(
        f"<span style='color:{color};margin-right:11px;'>{label}</span>"
        for label, color in entries
    )
    return (
        "<div style='position:absolute;top:6px;left:10px;z-index:6;"
        "font-size:11px;font-weight:700;line-height:1.4;white-space:nowrap;"
        "background:rgba(255,255,255,0.62);padding:1px 7px;border-radius:4px;"
        "pointer-events:none;'>" + spans + "</div>"
    )


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
    import streamlit as _st
    from streamlit_lightweight_charts import renderLightweightCharts  # type: ignore

    d = cdf.copy().sort_index()

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

    # 전체 히스토리를 그대로 전송 — 패치된 프론트엔드(patch_lwc.py)가 fitContent
    # 대신 scrollToRealTime 을 호출하므로 초기엔 최근 봉에 줌되고, 왼쪽으로 끌면
    # 과거 캔들이 거래소처럼 계속 이어진다 (barSpacing = DEFAULT_BAR_SPACING).
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
                "crosshairMarkerVisible": False,
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
            "barSpacing": DEFAULT_BAR_SPACING,
            "minBarSpacing": 0.5,  # allow zooming far out across full history
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
                "crosshairMarkerVisible": False,
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

    legend = chart_legend_html([(lbl, clr) for _p, clr, lbl, _k in ma_specs])
    with _st.container(key="chart_legend_wrap"):
        _st.markdown(legend, unsafe_allow_html=True)
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
# Stars (favorites) persistence — per-page JSON file, ``{code: true}``
# ---------------------------------------------------------------------------

def load_stars(path: Path) -> set:
    """Load the starred-codes set from ``path`` (``{code: true}`` JSON)."""
    import json
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return set()
    if isinstance(data, dict):
        return {str(k) for k, v in data.items() if v}
    if isinstance(data, list):
        return {str(x) for x in data}
    return set()


def save_stars(path: Path, stars: set) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({c: True for c in sorted(stars)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def render_chart_star(
    st: Any, code: str, stars_path: Path, session_key: str,
) -> bool:
    """⭐/☆ toggle button for the chart header (right end).

    Shares the ``session_key`` set with the grid's ⭐ column and the "별표만"
    filter, persisting to ``stars_path`` so favorites survive reloads. Returns
    the current starred state. No explicit ``st.rerun`` — the button click
    already reruns, and calling ``st.rerun`` inside a dialog would close it.
    """
    stars = st.session_state.setdefault(session_key, load_stars(stars_path))
    is_on = code in stars
    if st.button(
        "⭐" if is_on else "☆",
        key=f"chart_star_btn::{session_key}::{code}",
        help="별표 토글 (즐겨찾기)",
        use_container_width=True,
    ):
        if is_on:
            stars.discard(code)
        else:
            stars.add(code)
        save_stars(stars_path, stars)
        is_on = not is_on
    return is_on


# ---------------------------------------------------------------------------
# Compact number formatting for the chart meta line (시총 / 거래량)
# ---------------------------------------------------------------------------

def fmt_compact_krw(v: Any) -> str:
    """KRW amount → 조/억 compact string (원 단위 입력)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if x != x or x <= 0:
        return ""
    if x >= 1e12:
        return f"{x / 1e12:.1f}조"
    if x >= 1e8:
        return f"{x / 1e8:,.0f}억"
    return f"{x:,.0f}"


def fmt_compact_usd(v: Any) -> str:
    """USD amount → $B/$M/$K compact string."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if x != x or x <= 0:
        return ""
    if x >= 1e9:
        return f"${x / 1e9:.2f}B"
    if x >= 1e6:
        return f"${x / 1e6:.1f}M"
    if x >= 1e3:
        return f"${x / 1e3:.1f}K"
    return f"${x:,.0f}"


def fmt_compact_count(v: Any) -> str:
    """Plain share/contract count → thousands-separated (거래량 주식수)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if x != x or x <= 0:
        return ""
    return f"{x:,.0f}"


def render_chart_meta_line(st: Any, parts: list) -> None:
    """Small grey caption under the chart title — list of ``(label, value)``.

    Skips empty values. Renders as ``label value · label value`` on one line.
    """
    segs = [f"{label} {val}" for label, val in parts if val]
    if not segs:
        return
    st.markdown(
        "<div style='text-align:left; font-size:12px; color:#9aa0a6; "
        "margin-top:-4px; line-height:16px; white-space:nowrap; overflow:hidden; "
        "text-overflow:ellipsis;'>" + "&nbsp;·&nbsp;".join(segs) + "</div>",
        unsafe_allow_html=True,
    )


def breadth_counts(change: Any) -> tuple:
    """(up, down, flat) counts from a change/등락 series — sign-based.

    Unit-agnostic (percent or fraction): only the sign matters. NaN ignored.
    """
    c = pd.to_numeric(change, errors="coerce")
    return int((c > 0).sum()), int((c < 0).sum()), int((c == 0).sum())


def render_breadth(
    st: Any, *, full: Optional[tuple] = None, shown: Optional[tuple] = None,
) -> None:
    """One-line 상승/하락/보합 breadth caption (전체 / 표시) above a grid.

    Colors match the grid's signed convention — 상승 teal, 하락 red, 보합 grey.
    """
    UP, DN, FL = "#2A9D8F", "#E63946", "#888"

    def _seg(label: str, t: tuple) -> str:
        u, d, f = t
        return (
            f"{label} "
            f"<span style='color:{UP};font-weight:700'>▲{u:,}</span> "
            f"<span style='color:{DN};font-weight:700'>▼{d:,}</span> "
            f"<span style='color:{FL}'>─{f:,}</span>"
        )

    parts = []
    if full is not None:
        parts.append(_seg("전체", full))
    if shown is not None:
        parts.append(_seg("표시", shown))
    if not parts:
        return
    st.markdown(
        "<div style='font-size:13px; margin:1px 0 5px;'>📊 "
        + " &nbsp;&nbsp;·&nbsp;&nbsp; ".join(parts)
        + "</div>",
        unsafe_allow_html=True,
    )


def safe_fragment_rerun(st: Any) -> None:
    """``st.rerun(scope="fragment")`` that falls back to a full rerun.

    ``scope="fragment"`` is only valid while a fragment is running as a
    *fragment rerun*. During the initial full-app run (e.g. a page reload while a
    grid row is already selected) it raises ``StreamlitAPIException`` — catch
    that and do a normal full rerun instead so the page never crashes.
    """
    from streamlit.errors import StreamlitAPIException
    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:
        st.rerun()


def render_chart_title(st: Any, title: str) -> None:
    """Left-aligned title for the chart dialog header row."""
    st.markdown(
        f"<div style='text-align:left; font-size:17px; font-weight:600; "
        f"padding-top:0px; margin-top:-6px; line-height:28px; white-space:nowrap; "
        f"overflow:hidden; text-overflow:ellipsis;'>{title}</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Chart dialog navigation — ←/→ (and on-screen ‹/›) to step through stocks
# ---------------------------------------------------------------------------

def _inject_arrow_key_js(st: Any, prev_btn_key: str, next_btn_key: str) -> None:
    """Bridge keyboard ←/→ to the on-screen prev/next ``st.button`` clicks.

    Streamlit has no native key handling, so we drop a 0-height component
    iframe whose script (same-origin → reaches ``window.parent.document``)
    listens for arrow keys and ``.click()`` s the matching button.

    The tricky part is **focus**: after clicking a grid row, focus stays inside
    the AgGrid iframe, and the chart is its own iframe too — keydown there never
    reaches the main document, so a document-level listener would see nothing.
    On open we therefore pull focus onto the dialog container (once, and never
    when a text field is focused) so arrow keys land on the main document.

    Guards: only acts while a dialog is open; ignores keys while typing in an
    INPUT/TEXTAREA; skips disabled buttons (list boundaries). The handler is
    stored on the parent document and de-duplicated each rerun so re-injection
    never stacks listeners; a stale handler after close no-ops (no dialog).

    Button lookup tries the ``st-key-…`` class first, then falls back to the
    ‹ / › glyph inside the dialog in case the keyed class is absent.
    """
    from streamlit.components.v1 import html as _html

    _html(
        f"""
        <script>
        (function() {{
          let doc;
          try {{ doc = window.parent.document; }} catch (err) {{ return; }}
          if (!doc) return;

          var PREV_KEY = {prev_btn_key!r};
          var NEXT_KEY = {next_btn_key!r};

          function findDialog() {{
            return doc.querySelector('[data-testid="stDialog"]')
                || doc.querySelector('[role="dialog"]');
          }}

          function findBtn(dlg, key) {{
            var b = dlg.querySelector('.st-key-' + key + ' button');
            if (b) return b;
            var glyph = (key === PREV_KEY) ? '‹' : '›';  // ‹ / ›
            var all = dlg.querySelectorAll('button');
            for (var i = 0; i < all.length; i++) {{
              if ((all[i].innerText || '').trim() === glyph) return all[i];
            }}
            return null;
          }}

          if (doc.__stockChartNavHandler) {{
            doc.removeEventListener('keydown', doc.__stockChartNavHandler, true);
          }}
          function handler(e) {{
            if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
            var dlg = findDialog();
            if (!dlg) return;
            var ae = doc.activeElement;
            if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA'
                       || ae.isContentEditable)) return;
            var btn = findBtn(dlg, e.key === 'ArrowLeft' ? PREV_KEY : NEXT_KEY);
            if (btn && !btn.disabled) {{ e.preventDefault(); btn.click(); }}
          }}
          doc.__stockChartNavHandler = handler;
          doc.addEventListener('keydown', handler, true);

          // Pull focus onto the dialog so arrow keys reach the main document
          // and not the AgGrid / chart iframes. Once per open; never steal
          // focus from a text field the user may be typing in.
          var dlg = findDialog();
          if (dlg && !dlg.__navFocused) {{
            var ae = doc.activeElement;
            var inField = ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA'
                                 || ae.isContentEditable);
            if (!inField) {{
              dlg.setAttribute('tabindex', '-1');
              try {{ dlg.focus({{preventScroll: true}}); }} catch (e2) {{}}
              dlg.__navFocused = true;
            }}
          }}
        }})();
        </script>
        """,
        height=0,
    )


class ChartNavigator:
    """←/→ + ‹/› navigation between stocks inside the chart dialog.

    Steps the dialog's selected symbol to the previous/next entry in the
    grid's *current display order* — the page stores that ordered list (and a
    ``{code: name}`` map) in ``session_state`` under ``codes_key`` /
    ``names_key`` each rerun, so navigation follows whatever filter/sort the
    user has applied.

    ``shown_key`` (the page's ``_*_chart_dialog_shown_for`` guard) is updated
    in lockstep so the page does **not** call the dialog function again while
    it is already open — Streamlit forbids opening two dialogs and would
    raise. The already-open dialog re-renders itself on the rerun the button
    click triggers, picking up the new ``sel_key`` value.
    """

    def __init__(
        self,
        st: Any,
        *,
        codes_key: str,
        names_key: str,
        sel_key: str,
        name_key: str,
        shown_key: str,
        btn_prefix: str,
    ) -> None:
        self.st = st
        self.codes_key = codes_key
        self.names_key = names_key
        self.sel_key = sel_key
        self.name_key = name_key
        self.shown_key = shown_key
        self.prev_btn = f"{btn_prefix}_prev"
        self.next_btn = f"{btn_prefix}_next"

    def _codes(self) -> list:
        return self.st.session_state.get(self.codes_key) or []

    def _pos(self) -> tuple:
        """Return ``(index_of_current, total)``; index is -1 if not found."""
        codes = self._codes()
        cur = self.st.session_state.get(self.sel_key)
        return (codes.index(cur) if cur in codes else -1), len(codes)

    def _go(self, delta: int) -> None:
        codes = self._codes()
        cur = self.st.session_state.get(self.sel_key)
        if not codes or cur not in codes:
            return
        j = codes.index(cur) + delta
        if j < 0 or j >= len(codes):
            return
        new = codes[j]
        self.st.session_state[self.sel_key] = new
        names = self.st.session_state.get(self.names_key) or {}
        self.st.session_state[self.name_key] = names.get(new, new)
        self.st.session_state[self.shown_key] = new  # keep dialog-open guard in sync

    def button_prev(self) -> None:
        i, _n = self._pos()
        self.st.button(
            "‹", key=self.prev_btn, use_container_width=True,
            disabled=(i <= 0), on_click=self._go, args=(-1,),
            help="이전 종목 (←)",
        )

    def button_next(self) -> None:
        i, n = self._pos()
        self.st.button(
            "›", key=self.next_btn, use_container_width=True,
            disabled=(i < 0 or i >= n - 1), on_click=self._go, args=(1,),
            help="다음 종목 (→)",
        )

    def position_text(self) -> None:
        i, n = self._pos()
        label = f"{i + 1} / {n}" if i >= 0 else f"– / {n}"
        self.st.markdown(
            f"<div style='text-align:center;color:#888;font-size:12px;"
            f"line-height:32px;'>{label}</div>",
            unsafe_allow_html=True,
        )

    def _go_to(self, idx0: int) -> None:
        """Jump to the 0-based index ``idx0`` (clamped to range)."""
        codes = self._codes()
        if not codes:
            return
        idx0 = max(0, min(idx0, len(codes) - 1))
        new = codes[idx0]
        self.st.session_state[self.sel_key] = new
        names = self.st.session_state.get(self.names_key) or {}
        self.st.session_state[self.name_key] = names.get(new, new)
        self.st.session_state[self.shown_key] = new  # keep dialog-open guard in sync

    def _jump_from_widget(self, key: str) -> None:
        raw = self.st.session_state.get(key)
        if raw is None or str(raw).strip() == "":
            return
        try:
            idx1 = int(str(raw).strip())
        except (TypeError, ValueError):
            return
        self._go_to(idx1 - 1)  # _go_to clamps out-of-range input

    def position_input(self) -> None:
        """Editable ``n / m`` position — type a number (1..N) to jump to that chart.

        A plain text box (no +/- steppers) shows the current position with the
        total ``/ N`` beside it. The box is re-seeded to the current position
        every run (before instantiation) so ‹/›/arrow navigation keeps it in
        sync; typing a number triggers ``_jump_from_widget`` to navigate.
        Invalid / out-of-range text self-corrects on the next run.
        """
        i, n = self._pos()
        if n <= 0:
            self.position_text()
            return
        key = f"{self.next_btn}__pos"
        self.st.session_state[key] = str(i + 1) if i >= 0 else ""
        c_in, c_tot = self.st.columns([1, 0.7])
        with c_in:
            self.st.text_input(
                f"종목 위치 (1–{n})",
                key=key, on_change=self._jump_from_widget, args=(key,),
                label_visibility="collapsed",
                placeholder=str(i + 1) if i >= 0 else "#",
            )
        with c_tot:
            self.st.markdown(
                f"<div style='text-align:left;color:#888;font-size:13px;"
                f"line-height:32px;white-space:nowrap;'>/ {n}</div>",
                unsafe_allow_html=True,
            )

    def inject_keys(self) -> None:
        _inject_arrow_key_js(self.st, self.prev_btn, self.next_btn)


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
/* Nudge dialog X button — small offset from default */
div[role="dialog"] button[aria-label="Close"],
[data-testid="stDialog"] button[aria-label="Close"] {
  top: 0.4rem !important;
  margin-top: -2px !important;
}
/* Cap the entire page to viewport width and clip any overflow.
   Streamlit's wide layout sometimes lets nested blocks push the page
   wider than the viewport — this forces everything to fit. */
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
/* AgGrid component container + iframe — never exceed parent width. */
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
