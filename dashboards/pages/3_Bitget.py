"""Live ticker table for all Bitget USDT-M futures symbols.

Polls `https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES`
directly (same endpoint the upbit_project/bitget collector uses) and renders the
result as a sortable / filterable table with auto-refresh.

This page does NOT touch the realtime collector DB — it pulls fresh data from
the public REST endpoint each refresh. When the collector DB connection lands,
the dedicated `9_Realtime` page will read from it instead.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import requests

# allow `from dashboards.charts import ...` regardless of cwd
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.loader import load_ohlcv  # noqa: E402
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

BITGET_TICKERS_URL = "https://api.bitget.com/api/v2/mix/market/tickers"
BITGET_CANDLES_URL = "https://api.bitget.com/api/v2/mix/market/candles"
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
PRODUCT_TYPE = "USDT-FUTURES"
CANDLE_FETCH_CAP = 1000         # safety cap; above this we skip period % compute
CANDLE_CONCURRENCY = 5          # per project memory: keep ≤ 5
PERIODS_H: list[int] = [1, 4]            # hourly windows (1H candles)
PERIODS_D: list[int] = [3, 7, 14, 28]    # daily windows (1D candles)
MA_PERIODS: tuple[int, int] = (10, 20)   # short / long MA for MA-distance columns
# Unified window selector: hourly (1H candles) + daily (1D candles) windows.
# Drives Window High/Low Δ% (MA-distance columns use fixed periods).
WHIPSAW_WINDOW_OPTIONS: list[str] = ["1h", "4h", "12h", "24h", "7d", "14d", "28d"]
DEFAULT_WHIPSAW_WINDOW = "24h"
HOURLY_CANDLE_LIMIT = 30   # ≥ MA20+1, max hourly window+2 (24+2=26), max PERIODS_H+1
DAILY_CANDLE_LIMIT = 35    # ≥ MA20+1, max daily window+2 (28+2=30), max PERIODS_D+1


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


NUMERIC_COLS = [
    "lastPr", "askPr", "bidPr", "bidSz", "askSz",
    "high24h", "low24h", "ts", "change24h", "baseVolume",
    "quoteVolume", "usdtVolume", "openUtc", "changeUtc24h",
    "indexPrice", "fundingRate", "holdingAmount",
    "open24h", "markPrice",
]

# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_tickers(timeout: float = 10.0) -> pd.DataFrame:
    """Fetch the full USDT-M futures ticker snapshot. Raises on API error."""
    resp = requests.get(
        BITGET_TICKERS_URL,
        params={"productType": PRODUCT_TYPE},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("msg") != "success":
        raise RuntimeError(f"Bitget API error: code={payload.get('code')} msg={payload.get('msg')}")
    rows = payload.get("data", [])
    df = pd.DataFrame(rows)
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Market-cap snapshot (CoinGecko)
# ---------------------------------------------------------------------------

def fetch_market_caps(pages: int = 2, per_page: int = 250, timeout: float = 10.0) -> dict[str, float]:
    """Top N coins by market cap from CoinGecko → ``{SYMBOL_UPPER: market_cap_usd}``.

    First-seen wins (list is already mcap-desc), so collisions like LUNA /
    LUNC resolve to the higher-cap ticker. Empty dict on failure — caller
    treats missing symbols as NULL market cap.
    """
    caps: dict[str, float] = {}
    for page in range(1, pages + 1):
        try:
            resp = requests.get(
                COINGECKO_MARKETS_URL,
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": per_page,
                    "page": page,
                    "sparkline": "false",
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            for row in resp.json() or []:
                sym = (row.get("symbol") or "").upper()
                mc = row.get("market_cap")
                if sym and mc and sym not in caps:
                    caps[sym] = float(mc)
        except Exception:
            break
    return caps


def _bitget_to_base(symbol: str) -> Optional[str]:
    """``BTCUSDT`` → ``BTC``, ``1000PEPEUSDT`` → ``PEPE``, ``USDCUSDT`` → ``USDC``.

    Returns ``None`` for non-USDT-quoted symbols (shouldn't happen on the
    USDT-M endpoint, but cheap safety).
    """
    s = symbol.upper()
    if not s.endswith("USDT"):
        return None
    base = s[:-4]
    if base.startswith("1000") and len(base) > 4:
        base = base[4:]
    return base or None


def attach_market_cap(df: pd.DataFrame, caps: dict[str, float]) -> pd.DataFrame:
    """Add a ``marketCap`` column to ``df`` by mapping Bitget symbol → base coin."""
    if df.empty or not caps:
        df = df.copy()
        df["marketCap"] = pd.Series([None] * len(df), dtype="float64")
        return df
    df = df.copy()
    df["marketCap"] = (
        df["symbol"].astype(str).map(_bitget_to_base).map(caps).astype("float64")
    )
    return df


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


def _parse_window_label(label: str) -> tuple[int, str]:
    """``"4h"`` → ``(4, "1h")``, ``"14d"`` → ``(14, "1d")``."""
    if label.endswith("h"):
        return int(label[:-1]), "1h"
    if label.endswith("d"):
        return int(label[:-1]), "1d"
    raise ValueError(f"unknown window: {label!r}")


def compute_from_cache(
    current_prices: dict[str, float],
    symbols: list[str],
    windows: list[str] = WHIPSAW_WINDOW_OPTIONS,
    *,
    periods_h: list[int] = PERIODS_H,
    periods_d: list[int] = PERIODS_D,
    ma_periods: tuple[int, int] = MA_PERIODS,
    cache_loader=_load_cache_tails,
    now_ms: Optional[int] = None,
) -> pd.DataFrame:
    """Wall-clock-anchored cache reader → period %, *all-windows* H/L Δ% & MA Δ%.

    Each symbol's 1H and 1D parquet is read ONCE. Every derived metric is
    anchored to ``now_ms`` (defaults to wall-clock now), NOT the last bar in
    the cache — so a stale cache yields ``None`` for the affected metric
    instead of silently mislabeling (e.g. a "1h%" computed against a 6-hour-
    old bar).

    Anchoring rules (a bar's CLOSE represents the price at ``ts + interval``,
    so to read "price at time T" we look up the bar with ``ts ≤ T − interval``):
      * ``pct_{n}h`` — close of bar with ``ts ≤ now − (n+1)·1h``, tol 1h.
      * ``pct_{n}d`` — close of bar with ``ts ≤ now − (n+1)·1d``, tol 1d.
      * Window H/L  — bars in ``(now − stride·bar, now]``. Gated on freshness:
                      latest cached bar must be within ``2·bar`` of now.
      * MA          — same freshness gate, then for k=0..max_ma−1 read close
                      at ``now − k·stride·bar − bar_ms`` (tol = bar_ms). Missing
                      sample short-circuits → partial sample, possibly yielding
                      None for short/long if not enough samples accumulated.

    Columns produced (in order):
        symbol,
        pct_{n}h  for n in periods_h,           # fixed (1H granularity)
        pct_{n}d  for n in periods_d,           # fixed (1D granularity)
        for each window w in `windows`:
            pct_ma{short}__{w}, pct_ma{long}__{w},
            high__{w}, low__{w},
            pct_off_high__{w}, pct_off_low__{w}
    """
    import time as _time
    if now_ms is None:
        now_ms = int(_time.time() * 1000)

    short, long_ = ma_periods
    max_ma = max(short, long_)

    parsed_windows = [(w, *_parse_window_label(w)) for w in windows]
    # parsed_windows: list of (label, stride, gran)

    # How many tail bars do we need from each granularity?
    # +2 over the strict requirement to leave headroom for the at-or-before
    # lookup landing on a slightly older bar than the most recent.
    need_h = max(periods_h) + 2
    need_d = max(periods_d) + 2
    for (_, stride, gran) in parsed_windows:
        req = max(stride + 2, max_ma * stride + 2)
        if gran == "1h":
            need_h = max(need_h, req)
        else:
            need_d = max(need_d, req)

    pct_keys_h = [f"pct_{n}h" for n in periods_h]
    pct_keys_d = [f"pct_{n}d" for n in periods_d]

    # Pre-compute output column names so every row dict has the same shape.
    win_cols = []
    for (label, _, _) in parsed_windows:
        win_cols.extend([
            f"pct_ma{short}__{label}",
            f"pct_ma{long_}__{label}",
            f"high__{label}",
            f"low__{label}",
            f"pct_off_high__{label}",
            f"pct_off_low__{label}",
        ])
    none_cols = pct_keys_h + pct_keys_d + win_cols

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
        # Offset by one bar interval so we look up by bar-OPEN ts, while the
        # comparison is against the bar's CLOSE = price at (ts + interval).
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

        # ── Per-window MA + H/L (wall-clock anchored, freshness-gated) ──
        for (label, stride, gran) in parsed_windows:
            arrs = arrs_h if gran == "1h" else arrs_d
            bar_ms = HOUR_MS if gran == "1h" else DAY_MS
            if arrs is None or arrs["close"].size == 0:
                continue
            ts = arrs["timestamp"]
            closes = arrs["close"]
            highs = arrs["high"]
            lows = arrs["low"]

            # Freshness gate: latest cached bar must cover roughly "now",
            # else this window is meaningless → leave NULL.
            if now_ms - int(ts[-1]) > 2 * bar_ms:
                continue

            # Window H/L over wall-clock interval. We include any bar whose
            # span [ts, ts+bar) overlaps the window — i.e. ts > now − (stride+1)·bar
            # — so that at "now=14:37, stride=1h" the bar at ts=13:00 (covering
            # 13:00–14:00) still qualifies as part of "the last hour".
            mask = ts > now_ms - (stride + 1) * bar_ms
            if mask.any():
                hi = float(highs[mask].max())
                lo = float(lows[mask].min())
                row[f"high__{label}"] = hi
                row[f"low__{label}"] = lo
                if hi:
                    row[f"pct_off_high__{label}"] = (cur - hi) / hi
                if lo:
                    row[f"pct_off_low__{label}"] = (cur - lo) / lo

            # MA via stride sampling anchored at now. Same +1 bar offset as
            # period %: we want close ≈ price at (now − k·stride·bar), which
            # is the close of bar with ts ≤ (now − k·stride·bar − bar_ms).
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
    window_label: str,
    selected_symbol: Optional[str],
    *,
    short_ma: int = MA_PERIODS[0],
    long_ma: int = MA_PERIODS[1],
) -> tuple[pd.DataFrame, dict]:
    """Construct (df_reordered, gridOptions) for the Bitget AgGrid.

    Column order (left → right, displayed):
        ▸ checkbox + Symbol (pinned), Mark, 거래대금, Funding,
        1h%, 4h%, 24h%, 3d%, 7d%, 14d%, 28d%,
        MA10, MA20, High%, Low%   (window-dependent valueGetter),
        메모

    All other columns from the ticker API + raw per-window backing fields
    are hidden. Returns the df in the visible column order (plus hidden
    cols at the end) so AgGrid's columnDefs follows the same order.
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

    # ── Window-dependent (valueGetter reads `__{window}` from row data) ──
    gob.configure_column(
        SHORT_KEY, headerName=f"MA{short_ma}", width=60,
        valueGetter=_js_window_value_getter(f"pct_ma{short_ma}", window_label),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    gob.configure_column(
        LONG_KEY, headerName=f"MA{long_ma}", width=60,
        valueGetter=_js_window_value_getter(f"pct_ma{long_ma}", window_label),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    gob.configure_column(
        HIGH_KEY, headerName="High", width=58,
        valueGetter=_js_window_value_getter("pct_off_high", window_label),
        valueFormatter=JS_FMT_PCT, cellStyle=JS_SIGNED_COLOR,
        type=["numericColumn"],
    )
    gob.configure_column(
        LOW_KEY, headerName="Low", width=58,
        valueGetter=_js_window_value_getter("pct_off_low", window_label),
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
        st.header("Refresh")
        auto = st.toggle("Auto-refresh", value=False)
        interval = st.select_slider(
            "Interval (sec)",
            options=[5, 10, 30, 60],
            value=10,
        )
        manual = st.button("Refresh now", use_container_width=True)

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

    if manual:
        st.cache_data.clear()

    _fetch_log = _ROOT / "data" / "cache" / "crypto" / "_fetch.log"

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

    @st.cache_data(ttl=3, show_spinner=False)
    def _cached_fetch() -> pd.DataFrame:
        return fetch_tickers()

    @st.cache_data(ttl=600, show_spinner=False)
    def _cached_market_caps() -> dict[str, float]:
        # CoinGecko has a free-tier rate limit (~30/min) — 10 min TTL keeps us
        # well under it even with multiple page reloads.
        return fetch_market_caps()

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
        # only need the interval toggle here.
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
        d = d.sort_values("t").drop_duplicates(subset="t", keep="last")

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

        # (period, color, label, kind)  kind: "sma" | "vwma"
        ma_specs = [
            (10, "#F0B90B", "MA10", "sma"),    # 노란색
            (20, "#F6465D", "MA20", "red"),    # 빨간색
            (50, "#1565C0", "MA50", "sma"),    # 진한 파란색
            (100, "#000000", "VWMA100", "vwma"),  # 검정색 (거래량 가중)
        ]
        ma_series = []
        for period, color, label, kind in ma_specs:
            if kind == "vwma":
                pv = d["close"] * d["volume"]
                num = pv.rolling(period).sum()
                den = d["volume"].rolling(period).sum()
                ma = num / den.where(den != 0)
            else:
                ma = d["close"].rolling(period).mean()
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
                "timeVisible": interval in ("1h", "4h"),
                "secondsVisible": False,
                "rightOffset": 6,
                "barSpacing": 6,
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
                    "scaleMargins": {"top": 0.78, "bottom": 0},
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

    # The data section runs inside an st.fragment so that auto-refresh ticks
    # only re-render this block — sidebar / title stay put, no full-page flash.
    run_every = interval if auto else None

    @st.fragment(run_every=run_every)
    def render_data_section() -> None:
        try:
            df = _cached_fetch()
        except Exception as e:
            st.error(f"Bitget API 실패: {e}")
            return

        # Market cap snapshot — single CoinGecko call, cached 10min. Failures
        # leave marketCap as NULL, so the rest of the page still works.
        df = attach_market_cap(df, _cached_market_caps())

        # Filter bar — sits right above the table, inside the fragment so
        # changing filters only re-runs the fragment (sidebar etc. stable).
        f1, f2, f3, f4 = st.columns([3, 1, 2, 3])
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
            window_label = st.segmented_control(
                "Window",
                options=WHIPSAW_WINDOW_OPTIONS,
                default=DEFAULT_WHIPSAW_WINDOW,
                key="flt_window",
                help="Window High/Low Δ% 의 기간 + MA10/MA20 의 봉 크기. "
                     "예) 24h → MA10 = 최근 24h 봉 10개 평균(=10일), "
                     "14d → MA10 = 14일 봉 10개 평균(=140일). "
                     "MA 계산은 캐시된 1H/1D parquet 을 stride 샘플링.",
            )
            if not window_label:
                window_label = DEFAULT_WHIPSAW_WINDOW

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
        df_grid, grid_options = build_grid_options(df, window_label, selected_symbol)
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
