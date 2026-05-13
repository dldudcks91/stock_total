"""Live ticker table for all Bitget USDT-M futures symbols.

Reads a persisted snapshot at ``data/cache/crypto/_live_snapshot.parquet``
on render — never auto-fetches. The sidebar "라이브 가격 갱신" button kicks
off a background subprocess (``python -m data.sources.bitget_live``) that
fetches Bitget tickers + CoinGecko market caps and merges them into the
snapshot, then atomically replaces the file. The next page rerun reads the
new snapshot.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

# allow `from dashboards.charts import ...` regardless of cwd
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.loader import load_ohlcv  # noqa: E402
from data.sources.bitget_live import SNAPSHOT_PATH, load_snapshot  # noqa: E402
from dashboards._lib import render_fetch_log_sidebar  # noqa: E402

# Bitget/TradingView-style chart: use TradingView's lightweight-charts via
# the Streamlit wrapper. Falls back to plotly if the package isn't installed.
try:
    from streamlit_lightweight_charts import renderLightweightCharts  # type: ignore
    _HAS_LWC = True
except ImportError:  # pragma: no cover
    _HAS_LWC = False
    from dashboards.charts import plot_ohlcv  # noqa: F401

# Client-side grid (AgGrid). Renders / sorts / filters / edits in the browser
# — no streamlit rerun on each interaction. Required at import time.
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode, GridUpdateMode  # noqa: E402

BITGET_CANDLES_URL = "https://api.bitget.com/api/v2/mix/market/candles"
PRODUCT_TYPE = "USDT-FUTURES"
CANDLE_FETCH_CAP = 1000         # safety cap; above this we skip period % compute
CANDLE_CONCURRENCY = 5          # per project memory: keep ≤ 5
PERIODS_H: list[int] = [1, 4]            # hourly periods (fixed columns)
PERIODS_D: list[int] = [3, 7, 14, 28]    # daily periods (fixed columns)
MA_PERIODS: tuple[int, int] = (10, 20)   # short / long MA for MA Δ% columns

# MA Interval — bar size for MA10/MA20 columns. Mirrors KOSPI/NASDAQ pages'
# MA_INTERVAL split, extended with hourly granularity since the crypto cache
# carries 1H bars. ("1h" / "4h" stride-sample the 1H cache; "1d" / "1w" use
# the 1D cache.)
MA_INTERVAL_OPTIONS_CRYPTO: list[str] = ["1h", "4h", "1d", "1w"]
DEFAULT_MA_INTERVAL_CRYPTO: str = "1d"

# HL Lookback — calendar window for max(High) / min(Low) Δ%. "24h" reads
# from the 1H cache; everything else uses the 1D cache.
HL_LOOKBACK_OPTIONS_CRYPTO: list[str] = ["24h", "7d", "28d", "90d", "1y"]
DEFAULT_HL_LOOKBACK_CRYPTO: str = "28d"

# (granularity, stride): "1w" stride=7 on the 1D cache.
MA_INTERVAL_SPECS: dict[str, tuple[str, int]] = {
    "1h": ("1h", 1),
    "4h": ("1h", 4),
    "1d": ("1d", 1),
    "1w": ("1d", 7),
}

# (granularity, num_bars): "24h" = 24 bars of 1H cache; "1y" = 365 bars of 1D.
HL_LOOKBACK_SPECS: dict[str, tuple[str, int]] = {
    "24h": ("1h", 24),
    "7d": ("1d", 7),
    "28d": ("1d", 28),
    "90d": ("1d", 90),
    "1y": ("1d", 365),
}

HOURLY_CANDLE_LIMIT = 30   # ≥ MA20·stride for hourly MA + 24h lookback + PERIODS_H
DAILY_CANDLE_LIMIT = 380   # ≥ 1y lookback (365) + 20·7 (1w MA20) — pick the max


# Friendly column labels + display order.
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

# Local persistence for the per-symbol notepad column. JSON map of
# {symbol: note_text}. Loaded into session_state on page open and rewritten
# whenever the user edits a note in the chart panel.
NOTES_PATH = _ROOT / "data" / "cache" / "crypto" / "_notes.json"


def _load_notes() -> dict:
    import json
    try:
        return json.loads(NOTES_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_notes(notes: dict) -> None:
    import json
    NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTES_PATH.write_text(
        json.dumps(notes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _humanize_ago(delta: pd.Timedelta) -> str:
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


# ---------------------------------------------------------------------------
# Candle batch fetch (for period % changes + MA distance + Window High/Low)
# ---------------------------------------------------------------------------

async def _fetch_one_candles(session, sem, symbol: str, granularity: str, limit: int) -> tuple[str, list]:
    import aiohttp
    params = {
        "symbol": symbol,
        "productType": PRODUCT_TYPE,
        "granularity": granularity,
        "limit": str(limit),
    }
    async with sem:
        try:
            async with session.get(
                BITGET_CANDLES_URL, params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                payload = await r.json()
                if payload.get("msg") != "success":
                    return symbol, []
                return symbol, payload.get("data") or []
        except Exception:
            return symbol, []


async def _fetch_candles_batch_async(
    symbols: list[str], granularity: str, limit: int, concurrency: int,
) -> dict[str, list]:
    import aiohttp
    sem = asyncio.Semaphore(concurrency)
    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_one_candles(session, sem, s, granularity, limit) for s in symbols]
        results = await asyncio.gather(*tasks)
    return dict(results)


def fetch_candles_batch(
    symbols: list[str],
    granularity: str = "1H",
    limit: int = 30,
    concurrency: int = CANDLE_CONCURRENCY,
) -> dict[str, list]:
    """Sync wrapper around the async batch fetcher.

    Returns ``{symbol: [[ts, open, high, low, close, baseVol, quoteVol], ...]}``
    sorted oldest→newest. Empty list on failure / missing data for a symbol.
    """
    if not symbols:
        return {}
    return asyncio.run(_fetch_candles_batch_async(symbols, granularity, limit, concurrency))


def _load_cache_tails(
    symbol: str, gran: str, n: int,
) -> Optional[dict[str, np.ndarray]]:
    """Read the last ``n`` rows of (timestamp, close, high, low) from a cached crypto parquet.

    Returns ``None`` on miss / error. Arrays are oldest→newest. ``timestamp``
    is int64 UTC ms (matches the on-disk schema); ``close/high/low`` are
    float64. May be shorter than ``n`` if the cache has fewer rows.
    """
    path = _ROOT / "data" / "cache" / "crypto" / gran / f"{symbol}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path, columns=["timestamp", "close", "high", "low"])
    except Exception:
        return None
    if df.empty:
        return None
    tail = df.tail(n) if n and n < len(df) else df
    return {
        "timestamp": tail["timestamp"].to_numpy(dtype=np.int64, copy=False),
        "close": tail["close"].to_numpy(dtype=np.float64, copy=False),
        "high": tail["high"].to_numpy(dtype=np.float64, copy=False),
        "low": tail["low"].to_numpy(dtype=np.float64, copy=False),
    }


HOUR_MS = 3_600_000
DAY_MS = 86_400_000


def _close_at_or_before(
    ts: np.ndarray, closes: np.ndarray, target_ms: int, tol_ms: int,
) -> Optional[float]:
    """Return close of the bar whose timestamp is ≤ target_ms, within tolerance.

    Used for wall-clock-anchored lookups: ``target_ms`` is the wall-clock
    instant we want a price for, and the bar at-or-before it must be no more
    than ``tol_ms`` (typically 1 bar interval) older — otherwise the cache
    doesn't actually cover that point in time and we return ``None``.
    """
    if ts.size == 0:
        return None
    idx = int(np.searchsorted(ts, target_ms, side="right")) - 1
    if idx < 0:
        return None
    if target_ms - int(ts[idx]) > tol_ms:
        return None
    val = float(closes[idx])
    if not np.isfinite(val):
        return None
    return val


def compute_from_cache(
    current_prices: dict[str, float],
    symbols: list[str],
    *,
    ma_intervals: list[str] = MA_INTERVAL_OPTIONS_CRYPTO,
    hl_lookbacks: list[str] = HL_LOOKBACK_OPTIONS_CRYPTO,
    periods_h: list[int] = PERIODS_H,
    periods_d: list[int] = PERIODS_D,
    ma_periods: tuple[int, int] = MA_PERIODS,
    cache_loader=_load_cache_tails,
    now_ms: Optional[int] = None,
) -> pd.DataFrame:
    """Wall-clock-anchored cache reader → period %, MA × MA Interval, H/L × HL Lookback.

    Mirrors the KOSPI/NASDAQ ``_stock_grid.compute_from_cache`` two-axis model
    (MA Interval, HL Lookback) but anchored to wall-clock now and granularity-
    aware so 1H and 1D crypto caches can both feed the same row.

    Each symbol's 1H and 1D parquet is read ONCE. Every derived metric is
    anchored to ``now_ms``, NOT the last bar in the cache — so a stale cache
    yields ``None`` instead of silently mislabeling.

    Anchoring rules (a bar's CLOSE represents the price at ``ts + interval``,
    so to read "price at time T" we look up the bar with ``ts ≤ T − interval``):
      * ``pct_{n}h`` — close of bar with ``ts ≤ now − (n+1)·1h``, tol 1h.
      * ``pct_{n}d`` — close of bar with ``ts ≤ now − (n+1)·1d``, tol 1d.
      * MA per MA Interval iv ∈ MA_INTERVAL_SPECS — stride-sampled SMA anchored
        at now, on the matching granularity cache. Freshness-gated.
      * HL per HL Lookback lb ∈ HL_LOOKBACK_SPECS — bars in
        ``(now − num_bars·bar, now]`` on the matching granularity cache.
        Freshness-gated.

    Columns produced:
        symbol,
        pct_{n}h, pct_{n}d (fixed),
        per ma_interval iv:  pct_ma{short}__{iv}, pct_ma{long}__{iv}
        per hl_lookback lb:  high__{lb}, low__{lb},
                             pct_off_high__{lb}, pct_off_low__{lb}
    """
    import time as _time
    if now_ms is None:
        now_ms = int(_time.time() * 1000)

    short, long_ = ma_periods
    max_ma = max(short, long_)

    # Parse specs upfront — bail on unknown labels rather than emit silently
    # wrong columns.
    parsed_ma = [(iv, *MA_INTERVAL_SPECS[iv]) for iv in ma_intervals]
    # parsed_ma: list of (label, gran, stride)
    parsed_hl = [(lb, *HL_LOOKBACK_SPECS[lb]) for lb in hl_lookbacks]
    # parsed_hl: list of (label, gran, num_bars)

    # How many tail bars do we need from each granularity?
    # +2 over the strict requirement leaves headroom for the at-or-before
    # lookup landing on a slightly older bar than the most recent.
    need_h = max(periods_h) + 2
    need_d = max(periods_d) + 2
    for (_, gran, stride) in parsed_ma:
        req = max_ma * stride + 2
        if gran == "1h":
            need_h = max(need_h, req)
        else:
            need_d = max(need_d, req)
    for (_, gran, num_bars) in parsed_hl:
        req = num_bars + 2
        if gran == "1h":
            need_h = max(need_h, req)
        else:
            need_d = max(need_d, req)

    pct_keys_h = [f"pct_{n}h" for n in periods_h]
    pct_keys_d = [f"pct_{n}d" for n in periods_d]

    # Pre-compute output column names so every row dict has the same shape.
    ma_cols: list[str] = []
    for (label, _, _) in parsed_ma:
        ma_cols.extend([f"pct_ma{short}__{label}", f"pct_ma{long_}__{label}"])
    hl_cols: list[str] = []
    for (label, _, _) in parsed_hl:
        hl_cols.extend([
            f"high__{label}", f"low__{label}",
            f"pct_off_high__{label}", f"pct_off_low__{label}",
        ])
    none_cols = pct_keys_h + pct_keys_d + ma_cols + hl_cols

    rows = []
    for sym in symbols:
        row: dict[str, Any] = {"symbol": sym}
        for k in none_cols:
            row[k] = None
        cur = current_prices.get(sym)
        if cur is None or not np.isfinite(cur):
            rows.append(row)
            continue

        arrs_h = cache_loader(sym, "1h", need_h)
        arrs_d = cache_loader(sym, "1d", need_d)

        # ── Wall-clock anchored period % (1H, 1D) ──
        if arrs_h is not None and arrs_h["close"].size:
            ts_h, cl_h = arrs_h["timestamp"], arrs_h["close"]
            for n, key in zip(periods_h, pct_keys_h):
                prev = _close_at_or_before(ts_h, cl_h, now_ms - (n + 1) * HOUR_MS, HOUR_MS)
                if prev:
                    row[key] = (cur - prev) / prev
        if arrs_d is not None and arrs_d["close"].size:
            ts_d, cl_d = arrs_d["timestamp"], arrs_d["close"]
            for n, key in zip(periods_d, pct_keys_d):
                prev = _close_at_or_before(ts_d, cl_d, now_ms - (n + 1) * DAY_MS, DAY_MS)
                if prev:
                    row[key] = (cur - prev) / prev

        # ── MA per MA Interval (wall-clock anchored, freshness-gated) ──
        for (label, gran, stride) in parsed_ma:
            arrs = arrs_h if gran == "1h" else arrs_d
            bar_ms = HOUR_MS if gran == "1h" else DAY_MS
            if arrs is None or arrs["close"].size == 0:
                continue
            ts = arrs["timestamp"]
            closes = arrs["close"]
            if now_ms - int(ts[-1]) > 2 * bar_ms:
                continue
            sampled: list[float] = []
            for k in range(max_ma):
                target = now_ms - k * stride * bar_ms - bar_ms
                val = _close_at_or_before(ts, closes, target, bar_ms)
                if val is None:
                    break
                sampled.append(val)
            if len(sampled) >= short:
                ma_s = sum(sampled[:short]) / short
                if ma_s:
                    row[f"pct_ma{short}__{label}"] = (cur - ma_s) / ma_s
            if len(sampled) >= long_:
                ma_l = sum(sampled[:long_]) / long_
                if ma_l:
                    row[f"pct_ma{long_}__{label}"] = (cur - ma_l) / ma_l

        # ── HL per HL Lookback (wall-clock anchored, freshness-gated) ──
        for (label, gran, num_bars) in parsed_hl:
            arrs = arrs_h if gran == "1h" else arrs_d
            bar_ms = HOUR_MS if gran == "1h" else DAY_MS
            if arrs is None or arrs["close"].size == 0:
                continue
            ts = arrs["timestamp"]
            highs = arrs["high"]
            lows = arrs["low"]
            if now_ms - int(ts[-1]) > 2 * bar_ms:
                continue
            # Include bars whose span [ts, ts+bar) overlaps the lookback window
            # — same +1 offset as before so a partial current bar still counts.
            mask = ts > now_ms - (num_bars + 1) * bar_ms
            if not mask.any():
                continue
            hi = float(highs[mask].max())
            lo = float(lows[mask].min())
            row[f"high__{label}"] = hi
            row[f"low__{label}"] = lo
            if hi:
                row[f"pct_off_high__{label}"] = (cur - hi) / hi
            if lo:
                row[f"pct_off_low__{label}"] = (cur - lo) / lo

        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# AgGrid client-side spec (JsCode formatters / cellStyle / valueGetter)
# ---------------------------------------------------------------------------

# Color cell text by sign of value. Returns a CSS-in-JS object.
JS_SIGNED_COLOR = JsCode("""
function(params) {
  const v = params.value;
  if (v == null || Number.isNaN(v)) return {color: '#888'};
  if (v > 0) return {color: '#2A9D8F', fontWeight: '600'};
  if (v < 0) return {color: '#E63946', fontWeight: '600'};
  return {};
}
""")

# "+5.2%" / "-1.3%" / "—".  Input value is fraction (0.0523).
JS_FMT_PCT = JsCode("""
function(params) {
  const v = params.value;
  if (v == null || Number.isNaN(v)) return '—';
  const pct = v * 100;
  const sign = pct > 0 ? '+' : (pct < 0 ? '' : '');
  return sign + pct.toFixed(1) + '%';
}
""")

# Price: 4 decimal places, thousands separator.
JS_FMT_PRICE = JsCode("""
function(params) {
  const v = params.value;
  if (v == null || Number.isNaN(v)) return '—';
  return Number(v).toLocaleString('en-US', {minimumFractionDigits: 4, maximumFractionDigits: 4});
}
""")

# Volume / OI (USDT): integer with thousands separator.
JS_FMT_INT = JsCode("""
function(params) {
  const v = params.value;
  if (v == null || Number.isNaN(v)) return '—';
  return Math.round(v).toLocaleString('en-US');
}
""")

# Market cap (USD): compact "$1.62T / $34.7B / $912M".
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


def _js_window_value_getter(field_prefix: str, window_label: str) -> JsCode:
    """Build a JS valueGetter that returns row[`{prefix}__{window}`].

    Lets us keep 4 visible window-dependent columns (MA10, MA20, High%, Low%)
    while the row data carries values for all 7 windows. Switching window =
    re-evaluating valueGetter on the same row data; no server recompute.
    """
    return JsCode(
        f"function(params) {{ return params.data['{field_prefix}__{window_label}']; }}"
    )


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
        ▸ checkbox + Symbol (pinned), Mark, 거래대금, Funding,
        1h%, 4h%, 24h%, 3d%, 7d%, 14d%, 28d%,
        MA10 (ma_interval), MA20 (ma_interval),
        High% (hl_lookback), Low% (hl_lookback),
        메모

    ``ma_interval`` ∈ MA_INTERVAL_OPTIONS_CRYPTO selects which __{iv}
    suffix the MA columns read; ``hl_lookback`` ∈ HL_LOOKBACK_OPTIONS_CRYPTO
    selects the suffix for the H/L columns. Toggling flips values purely
    client-side via JsCode valueGetter — no server recompute.
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

    # Insert placeholder cols so AgGrid renders them in this position.
    # Actual values come from valueGetter (raw window-suffixed fields in row).
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
        valueGetter=_js_window_value_getter(f"pct_ma{short_ma}", ma_interval),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    gob.configure_column(
        LONG_KEY, headerName=f"MA{long_ma}", width=60,
        valueGetter=_js_window_value_getter(f"pct_ma{long_ma}", ma_interval),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    # ── HL columns (valueGetter reads `__{hl_lookback}` from row data) ──
    gob.configure_column(
        HIGH_KEY, headerName="High", width=58,
        valueGetter=_js_window_value_getter("pct_off_high", hl_lookback),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    gob.configure_column(
        LOW_KEY, headerName="Low", width=58,
        valueGetter=_js_window_value_getter("pct_off_low", hl_lookback),
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
    })
    return df_grid, opts


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

_BITGET_PAGE_CSS = """
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
</style>
"""


def main() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="Bitget",
        page_icon="📡",
        layout="wide",
    )
    # One-shot CSS injection — selectors are stable, no need to re-inject per rerun.
    st.markdown(_BITGET_PAGE_CSS, unsafe_allow_html=True)

    all_keys = list(COLUMN_LABELS.keys())
    sort_default = "quoteVolume"

    with st.sidebar:
        st.header("Snapshot")

        if SNAPSHOT_PATH.exists():
            _mtime = pd.Timestamp.fromtimestamp(
                SNAPSHOT_PATH.stat().st_mtime, tz="Asia/Seoul",
            )
            _ago = pd.Timestamp.now(tz="Asia/Seoul") - _mtime
            st.caption(
                f"📡 스냅샷 {_mtime.strftime('%H:%M:%S')} · {_humanize_ago(_ago)} ago"
            )
        else:
            st.caption("📡 스냅샷 없음 — 아래 버튼으로 최초 받기")

        live_proc = st.session_state.get("bitget_live_proc")
        live_running = live_proc is not None and live_proc.poll() is None
        live_btn = st.button(
            "라이브 가격 갱신" if not live_running else "Fetching… (background)",
            use_container_width=True,
            key="bitget_live_btn",
            disabled=live_running,
            help="Bitget 티커 + CoinGecko 시총을 받아 _live_snapshot.parquet 에 머지. 백그라운드.",
        )

        st.markdown("---")
        fetch_proc = st.session_state.get("bitget_fetch_proc")
        fetch_running = fetch_proc is not None and fetch_proc.poll() is None
        fetch_btn = st.button(
            "Bitget 데이터 받기" if not fetch_running else "Fetching… (background)",
            use_container_width=True,
            key="bitget_fetch_btn",
            disabled=fetch_running,
            help="Bitget USDT-M 전 종목 1D + 1H OHLCV 를 data/cache/crypto/ 로 증분 다운로드. 백그라운드 실행.",
        )

        # 최근 내려받은 데이터 — 펼친 상태로 사이드바에 상시 노출.
        render_fetch_log_sidebar(st, embedded=True)

    _fetch_log = _ROOT / "data" / "cache" / "crypto" / "_fetch.log"
    _live_log = _ROOT / "data" / "cache" / "crypto" / "_live_fetch.log"

    if live_btn and not live_running:
        import subprocess
        _live_log.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(_live_log, "w", encoding="utf-8", buffering=1)
        new_proc = subprocess.Popen(
            [sys.executable, "-m", "data.sources.bitget_live"],
            cwd=str(_ROOT),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        st.session_state["bitget_live_proc"] = new_proc
        st.session_state["bitget_live_started"] = pd.Timestamp.now(tz="Asia/Seoul").isoformat(timespec="seconds")
        st.session_state["bitget_live_finalized"] = False
        st.rerun()

    with st.sidebar:
        if live_running or live_proc is not None:
            try:
                live_log_text = _live_log.read_text(encoding="utf-8", errors="replace")
            except FileNotFoundError:
                live_log_text = ""
            live_tail = live_log_text.splitlines()[-8:]
        if live_running:
            st.info(
                f"⏳ 라이브 fetch 진행 중 (시작 {st.session_state.get('bitget_live_started','?')})"
            )
            if live_tail:
                st.code("\n".join(live_tail))
            if st.button("🔄 상태 갱신", use_container_width=True, key="bitget_live_refresh"):
                st.rerun()
        elif live_proc is not None:
            rc = live_proc.returncode
            if not st.session_state.get("bitget_live_finalized"):
                st.session_state["bitget_live_finalized"] = True
            if rc == 0:
                st.success("✅ 라이브 fetch 완료")
            else:
                st.error(f"❌ 라이브 fetch 실패 (rc={rc})")
            if live_tail:
                st.code("\n".join(live_tail))
            if st.button("Dismiss", use_container_width=True, key="bitget_live_dismiss"):
                st.session_state["bitget_live_proc"] = None
                st.session_state["bitget_live_finalized"] = False
                st.rerun()

    if fetch_btn and not fetch_running:
        import subprocess
        _fetch_log.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(_fetch_log, "w", encoding="utf-8", buffering=1)
        # 1d → 1h 순차 실행을 한 파이썬 프로세스로 묶음
        wrapper = (
            "import subprocess, sys;"
            "rc1 = subprocess.call([sys.executable,'-m','data.sources.bitget','--granularity','1d']);"
            "rc2 = subprocess.call([sys.executable,'-m','data.sources.bitget','--granularity','1h']);"
            "sys.exit(rc1 or rc2)"
        )
        new_proc = subprocess.Popen(
            [sys.executable, "-c", wrapper],
            cwd=str(_ROOT),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        st.session_state["bitget_fetch_proc"] = new_proc
        st.session_state["bitget_fetch_started"] = pd.Timestamp.now(tz="Asia/Seoul").isoformat(timespec="seconds")
        st.session_state["bitget_fetch_finalized"] = False
        st.rerun()

    def _parse_fetch_progress(log_text: str) -> dict:
        """bitget.py stdout 에서 현재 granularity, 진행 카운트, 최근 심볼 추출."""
        import re
        gran = None
        last_idx = 0
        total = 0
        last_sym = ""
        last_rows = ""
        for line in log_text.splitlines():
            m = re.search(r"granularity=(\w+)", line)
            if m:
                gran = m.group(1)
                last_idx = 0  # 단계 전환 — 카운터 리셋
            m = re.match(r"\[\s*(\d+)/(\d+)\]\s+(\S+)\s+rows=\s*(\d+)", line)
            if m:
                last_idx = int(m.group(1))
                total = int(m.group(2))
                last_sym = m.group(3)
                last_rows = m.group(4)
        return {
            "gran": gran,
            "idx": last_idx,
            "total": total,
            "sym": last_sym,
            "rows": last_rows,
        }

    # ── status indicator (always visible after the button) ────────────────
    with st.sidebar:
        if fetch_running or fetch_proc is not None:
            try:
                log_text = _fetch_log.read_text(encoding="utf-8", errors="replace")
            except FileNotFoundError:
                log_text = ""

            prog = _parse_fetch_progress(log_text)
            tail = log_text.splitlines()[-8:]

        if fetch_running:
            st.info(f"⏳ Bitget fetch 진행 중 (시작 {st.session_state.get('bitget_fetch_started','?')})")
            if prog["total"]:
                pct = prog["idx"] / prog["total"]
                st.progress(
                    min(pct, 1.0),
                    text=f"{prog['gran']}: {prog['idx']}/{prog['total']} ({pct*100:.1f}%) — last: {prog['sym']} rows={prog['rows']}",
                )
            else:
                st.caption("starting…")
            if tail:
                st.code("\n".join(tail))
            if st.button("🔄 상태 갱신", use_container_width=True, key="bitget_fetch_refresh"):
                st.rerun()
        elif fetch_proc is not None:
            rc = fetch_proc.returncode
            if not st.session_state.get("bitget_fetch_finalized"):
                if rc == 0:
                    st.cache_data.clear()
                st.session_state["bitget_fetch_finalized"] = True
            if rc == 0:
                st.success(
                    f"✅ Bitget fetch 완료 — last {prog['gran']}: "
                    f"{prog['idx']}/{prog['total']}"
                )
            else:
                st.error(f"❌ Bitget fetch 실패 (rc={rc})")
            if tail:
                st.code("\n".join(tail))
            if st.button("Dismiss", use_container_width=True, key="bitget_fetch_dismiss"):
                st.session_state["bitget_fetch_proc"] = None
                st.session_state["bitget_fetch_finalized"] = False
                st.rerun()

    @st.cache_data(ttl=300, show_spinner=False)
    def _cached_cache_tails(symbol: str, gran: str, n: int):
        # Single source of truth for period %, window H/L, MA Δ%.
        return _load_cache_tails(symbol, gran, n)

    @st.cache_data(ttl=60, show_spinner=False)
    def _cached_compute_all_windows(
        symbols_tuple: tuple,
        prices_items: tuple,  # tuple of (symbol, markPrice) — hashable for cache
    ) -> pd.DataFrame:
        """Cached wrapper over compute_from_cache for all windows.

        Cache TTL=60s. Window-toggle / sort / row-select reruns all hit this
        cache (within the minute) so the parquet read + numpy pass runs at
        most once per minute per (symbol set, price snapshot).
        """
        current_prices = dict(prices_items)
        def _loader(sym: str, gran: str, n: int):
            limit = HOURLY_CANDLE_LIMIT if gran == "1h" else DAILY_CANDLE_LIMIT
            return _cached_cache_tails(sym, gran, max(n, limit))
        return compute_from_cache(
            current_prices, list(symbols_tuple),
            cache_loader=_loader,
        )

    @st.cache_data(ttl=300, show_spinner=False)
    def _chart_df_cached(symbol: str, interval: str) -> pd.DataFrame:
        # cache/crypto/{1h,1d}/{SYMBOL}.parquet → 1h/4h/1d/1w (raw or resample)
        return load_ohlcv("crypto", symbol, interval)

    def _render_inline_chart(symbol: str) -> None:
        # Dialog has its own close (Esc / outside-click / built-in X), so we
        # only need the symbol name + interval toggle here.
        col_left, _spacer = st.columns([2, 3], vertical_alignment="center")
        with col_left:
            st.markdown(
                f"<div style='text-align:left; font-size:17px; font-weight:600; "
                f"padding-top:0px; margin-top:-6px; line-height:28px; white-space:nowrap; "
                f"overflow:hidden; text-overflow:ellipsis;'>{symbol}</div>",
                unsafe_allow_html=True,
            )
            with st.container(key="chart_iv_picker"):
                chart_iv = st.segmented_control(
                    "Interval",
                    options=["1d", "1w", "1M"],
                    default="1w",
                    key="chart_iv",
                    label_visibility="collapsed",
                )
        if not chart_iv:
            chart_iv = "1w"

        try:
            cdf = _chart_df_cached(symbol, chart_iv)
        except FileNotFoundError:
            st.warning(
                f"`{symbol}` 캐시 없음 — `/crypto-fetch {symbol}` 으로 먼저 받아주세요."
            )
            return
        except Exception as e:  # noqa: BLE001
            st.warning(f"{symbol} 캐시 로드 실패: {e}")
            return

        if cdf is None or len(cdf) == 0:
            st.warning(f"{symbol} 데이터 비어있음")
            return

        if _HAS_LWC:
            _render_tv_chart(symbol, chart_iv, cdf)
        else:
            from dashboards.charts import plot_ohlcv
            fig = plot_ohlcv(
                cdf,
                title=f"{symbol} · {chart_iv.upper()} · {len(cdf):,}봉",
                ma_periods=(10, 20, 50), vwma_periods=(100,),
                show_volume=True, height=420,
            )
            st.plotly_chart(fig, use_container_width=True,
                            config={"displayModeBar": False, "scrollZoom": True})

    def _render_tv_chart(symbol: str, interval: str, cdf: pd.DataFrame) -> None:
        """Bitget/TradingView-style chart via lightweight-charts."""
        d = cdf.copy()
        # crypto cache: timestamp(UTC ms). lightweight-charts expects unix seconds.
        d["t"] = (pd.to_numeric(d["timestamp"]) // 1000).astype("int64")
        d = d.sort_values("t").drop_duplicates(subset="t", keep="last").reset_index(drop=True)

        # Standard exchange-style visible bar count per interval. Indicators
        # below compute on the FULL series first, then we slice — so MAs/RSI
        # in the visible window already include "warmup" values.
        VISIBLE_BARS = {"1d": 150, "1w": 100, "1M": 60}.get(interval, 150)

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

    # Chart dialog (modal popup) — opens when a row is freshly selected in
    # the grid. Built-in Streamlit dialog handles Esc / outside-click / X.
    # Selection state lives in ``bitget_sel_symbol``; we track the symbol we
    # *last opened the dialog for* in ``_chart_dialog_shown_for`` so that
    # auto-refresh reruns don't reopen a dialog the user already dismissed.
    @st.dialog(" ", width="large")
    def _chart_dialog() -> None:
        sym = st.session_state.get("bitget_sel_symbol")
        if not sym:
            return
        _render_inline_chart(sym)

    @st.fragment
    def render_data_section() -> None:
        df = load_snapshot()
        if df is None or df.empty:
            st.info(
                "📡 라이브 스냅샷 없음 — 사이드바 `라이브 가격 갱신` 으로 먼저 받아주세요. "
                "Bitget 티커는 bulk endpoint라 1~2초면 완료."
            )
            return

        stale_caption: Optional[str]
        if "fetched_at" in df.columns:
            fetched_ts = pd.to_datetime(df["fetched_at"], errors="coerce", utc=False)
            latest = fetched_ts.max()
            if pd.notna(latest):
                latest_kst = (
                    latest.tz_convert("Asia/Seoul")
                    if latest.tzinfo is not None else latest
                )
                ago = pd.Timestamp.now(tz="Asia/Seoul") - latest_kst
                fresh_count = int((fetched_ts == latest).sum())
                stale_caption = (
                    f"📡 시세 {latest_kst.strftime('%H:%M:%S')} · "
                    f"{_humanize_ago(ago)} ago · "
                    f"{fresh_count}/{len(df)} freshly updated"
                )
            else:
                stale_caption = f"📡 시세 (timestamp unknown) · {len(df)} rows"
        else:
            stale_caption = f"📡 시세 (no timestamp) · {len(df)} rows"
        st.caption(stale_caption)

        # Filter bar — sits right above the table, inside the fragment so
        # changing filters only re-runs the fragment (sidebar etc. stable).
        # Mirrors KOSPI/NASDAQ: 5 columns with MA Interval + HL Lookback split.
        f1, f2, f3, f4, f5 = st.columns([3, 1, 2, 2, 3])
        with f1:
            search = st.text_input("Symbol contains", value="", key="flt_search").strip()
        with f2:
            top_n = st.number_input(
                "Top N (0 = all)",
                min_value=0, max_value=2000, value=0, step=10,
                key="flt_topn",
            )
        with f3:
            sort_col_key = st.selectbox(
                "Sort by",
                options=all_keys,
                index=all_keys.index(sort_default),
                format_func=lambda k: COLUMN_LABELS.get(k, k),
                key="flt_sort",
            )
        with f4:
            ma_interval = st.segmented_control(
                "MA Interval",
                options=MA_INTERVAL_OPTIONS_CRYPTO,
                default=DEFAULT_MA_INTERVAL_CRYPTO,
                key="flt_ma_interval",
                help="MA10/MA20 봉 단위. 1h/4h → 1H 캐시, 1d/1w → 1D 캐시 stride 샘플링.",
            )
            if not ma_interval:
                ma_interval = DEFAULT_MA_INTERVAL_CRYPTO
        with f5:
            hl_lookback = st.segmented_control(
                "HL Lookback",
                options=HL_LOOKBACK_OPTIONS_CRYPTO,
                default=DEFAULT_HL_LOOKBACK_CRYPTO,
                key="flt_hl_lookback",
                help="High/Low Δ% 기간 (wall-clock anchored). "
                     "24h → 1H 캐시 24봉, 그 외 → 1D 캐시.",
            )
            if not hl_lookback:
                hl_lookback = DEFAULT_HL_LOOKBACK_CRYPTO

        # apply filter (always descending — Top N + sort-by-volume etc.)
        if search:
            df = df[df["symbol"].astype(str).str.contains(search, case=False, na=False)]
        if sort_col_key in df.columns:
            df = df.sort_values(sort_col_key, ascending=False, na_position="last")
        if top_n > 0:
            df = df.head(int(top_n))
        df = df.reset_index(drop=True)

        if df.empty:
            st.info("필터 조건에 맞는 심볼이 없습니다.")
            return

        # Period %, Window H/L, MA Δ% — all from the local 1H/1D parquet cache.
        # Now computes ALL 7 windows in one pass; AgGrid switches which window
        # is *displayed* purely on the browser side via valueGetter — no server
        # recompute when the user changes window.
        visible_symbols = df["symbol"].astype(str).tolist()
        skipped_period_calc = False
        if visible_symbols:
            if len(visible_symbols) > CANDLE_FETCH_CAP:
                skipped_period_calc = True
            else:
                current_prices = dict(zip(
                    df["symbol"].astype(str),
                    df.get("markPrice", pd.Series(dtype=float)),
                ))
                try:
                    def _loader(sym: str, gran: str, n: int):
                        limit = HOURLY_CANDLE_LIMIT if gran == "1h" else DAILY_CANDLE_LIMIT
                        return _cached_cache_tails(sym, gran, max(n, limit))
                    with st.spinner(f"캐시 계산 ({len(visible_symbols)} symbols, all windows)…"):
                        derived = _cached_compute_all_windows(
                            tuple(visible_symbols),
                            tuple(sorted(current_prices.items())),
                        )
                    if not derived.empty:
                        overlap = [c for c in derived.columns
                                   if c != "symbol" and c in df.columns]
                        if overlap:
                            df = df.drop(columns=overlap)
                        df = df.merge(derived, on="symbol", how="left")
                except Exception as e:
                    st.warning(f"기간 변화율 계산 실패: {e}")

        if skipped_period_calc:
            st.info(
                f"표시 심볼 {len(visible_symbols)}개 > cap({CANDLE_FETCH_CAP}). "
                "Top N 을 줄이거나 검색 필터를 적용하세요."
            )

        # ── Per-symbol notes (memo column) ──
        notes = st.session_state.setdefault("bitget_notes", _load_notes())
        df["note"] = df["symbol"].astype(str).map(notes).fillna("")

        # ── Selection state (used by AgGrid pre_selected_rows + chart panel) ──
        SEL_KEY = "bitget_sel_symbol"
        selected_symbol: Optional[str] = st.session_state.get(SEL_KEY)
        if selected_symbol and not (df["symbol"] == selected_symbol).any():
            # filter/sort dropped it
            st.session_state.pop(SEL_KEY, None)
            selected_symbol = None

        # ── AgGrid render ──
        df_grid, grid_options = build_grid_options(
            df, ma_interval, hl_lookback, selected_symbol,
        )
        # Re-key the grid only when the row set/order *meaningfully* changes
        # (top_n / search / sort key). Same key across reruns lets AgGrid
        # preserve scroll position and column resize.
        grid_key = f"bitget_grid::{top_n}::{search}::{sort_col_key}"
        grid_resp = AgGrid(
            df_grid,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.SELECTION_CHANGED
                       | GridUpdateMode.VALUE_CHANGED,
            allow_unsafe_jscode=True,
            fit_columns_on_grid_load=False,
            height=720,
            theme="streamlit",
            key=grid_key,
        )

        # ── Persist memo edits (silent, no rerun) ──
        edited_df = grid_resp.get("data")
        if edited_df is not None and "note" in edited_df.columns:
            notes_changed = False
            for sym, new_val in zip(edited_df["symbol"].astype(str), edited_df["note"].astype(str)):
                new_val = (new_val or "").strip()
                cur_val = notes.get(sym, "")
                if new_val != cur_val:
                    if new_val:
                        notes[sym] = new_val
                    else:
                        notes.pop(sym, None)
                    notes_changed = True
            if notes_changed:
                _save_notes(notes)

        # ── Selection → chart panel ──
        sel_rows = grid_resp.get("selected_rows")
        new_sel: Optional[str] = None
        if sel_rows is not None:
            if isinstance(sel_rows, pd.DataFrame) and len(sel_rows):
                new_sel = str(sel_rows.iloc[0].get("symbol", "")) or None
            elif isinstance(sel_rows, list) and sel_rows:
                first = sel_rows[0]
                if isinstance(first, dict):
                    new_sel = str(first.get("symbol", "")) or None
        if new_sel != selected_symbol:
            if new_sel:
                st.session_state[SEL_KEY] = new_sel
            else:
                st.session_state.pop(SEL_KEY, None)
            st.rerun(scope="fragment")

        # ── Chart popup: open dialog once per *new* selection ──
        # The dialog tracks ``_chart_dialog_shown_for`` so dismissal (Esc /
        # outside-click / built-in X) doesn't trigger an immediate reopen on
        # the next rerun. To open the same symbol again, uncheck → re-check.
        cur_sel = st.session_state.get(SEL_KEY)
        last_shown = st.session_state.get("_chart_dialog_shown_for")
        if cur_sel and cur_sel != last_shown:
            st.session_state["_chart_dialog_shown_for"] = cur_sel
            _chart_dialog()
        elif not cur_sel and last_shown is not None:
            st.session_state.pop("_chart_dialog_shown_for", None)

        with st.expander("응답 원본 컬럼 (디버그)"):
            st.write(sorted(df.columns.tolist()))

    render_data_section()


main()
