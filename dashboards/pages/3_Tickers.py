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
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

BITGET_TICKERS_URL = "https://api.bitget.com/api/v2/mix/market/tickers"
BITGET_CANDLES_URL = "https://api.bitget.com/api/v2/mix/market/candles"
PRODUCT_TYPE = "USDT-FUTURES"
CANDLE_FETCH_CAP = 1000         # safety cap; above this we skip period % compute
CANDLE_CONCURRENCY = 5          # per project memory: keep ≤ 5
PERIODS_H: list[int] = [1, 4, 12]    # hourly windows (1H candles)
PERIODS_D: list[int] = [7, 14, 28]   # daily windows (1D candles)
WHIPSAW_WINDOW_OPTIONS: list[int] = [4, 6, 12, 24]  # supported windows for Path/Net + RV
DEFAULT_WHIPSAW_WINDOW = 24
PN_CAP = 100.0   # cap on Path/Net to keep sorting sane when net ≈ 0

# Friendly column labels + display order.
COLUMN_LABELS: dict[str, str] = {
    "symbol": "Symbol",
    "markPrice": "Mark",
    "lastPr": "Last",
    "pct_1h": "1h %",
    "pct_4h": "4h %",
    "pct_12h": "12h %",
    "change24h": "24h %",
    "changeUtc24h": "24h % (UTC)",
    "pct_7d": "7d %",
    "pct_14d": "14d %",
    "pct_28d": "28d %",
    "pct_off_high24h": "24h High Δ%",
    "pct_off_low24h": "24h Low Δ%",
    "pn_window": "Path/Net (window)",
    "rv_window": "RealVol (window)",
    "high24h": "24h High",
    "low24h": "24h Low",
    "open24h": "24h Open",
    "openUtc": "Open (UTC)",
    "quoteVolume": "거래대금 (USDT)",
    "baseVolume": "Base Vol",
    "usdtVolume": "USDT Vol",
    "fundingRate": "Funding",
    "oiNotional": "OI (USDT)",
    "holdingAmount": "OI (coin)",
    "indexPrice": "Index",
    "askPr": "Ask",
    "bidPr": "Bid",
}

NUMERIC_COLS = [
    "lastPr", "askPr", "bidPr", "bidSz", "askSz",
    "high24h", "low24h", "ts", "change24h", "baseVolume",
    "quoteVolume", "usdtVolume", "openUtc", "changeUtc24h",
    "indexPrice", "fundingRate", "holdingAmount",
    "open24h", "markPrice",
]

DEFAULT_DISPLAY = [
    "symbol", "markPrice", "quoteVolume", "fundingRate",
    "pct_1h", "pct_4h", "pct_12h", "change24h",
    "pn_window", "rv_window",
    "pct_7d", "pct_14d", "pct_28d",
    "pct_off_high24h", "pct_off_low24h",
    "oiNotional",
]

# Per-column style/format spec used after we rename to friendly labels.
PRICE_LABELS = {"Mark", "Last", "24h Open", "24h High", "24h Low", "Open (UTC)", "Index", "Ask", "Bid"}
PCT_LABELS = {
    "1h %", "4h %", "12h %", "24h %", "24h % (UTC)",
    "7d %", "14d %", "28d %",
    "24h High Δ%", "24h Low Δ%",
}
FUNDING_LABELS = {"Funding"}
QUOTE_LABELS = {"거래대금 (USDT)", "USDT Vol", "OI (USDT)"}
COIN_AMT_LABELS = {"Base Vol", "OI (coin)"}


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
# Candle batch fetch (for 1h / 4h / 12h % changes)
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


def compute_period_changes(
    current_prices: dict[str, float],
    candles_by_symbol: dict[str, list],
    periods: list[int],
    suffix: str = "h",
) -> pd.DataFrame:
    """For each symbol, compute (current - close_n_bars_ago) / close_n_bars_ago.

    ``candles_by_symbol[sym]`` is oldest→newest, and the last bar may be the
    in-progress current bar. We treat ``candles[-(n+1)]`` as "n bars ago
    closed bar" for all n, which is approximate but matches common dashboard
    semantics (used by CoinGecko / CMC etc).

    ``suffix`` controls the column-name suffix: ``"h"`` for hourly inputs,
    ``"d"`` for daily inputs, etc.
    """
    rows = []
    for sym, candles in candles_by_symbol.items():
        cur = current_prices.get(sym)
        row: dict[str, Any] = {"symbol": sym}
        if cur is None or not candles:
            for n in periods:
                row[f"pct_{n}{suffix}"] = None
            rows.append(row)
            continue
        try:
            closes = [float(c[4]) for c in candles]
        except (ValueError, TypeError, IndexError):
            for n in periods:
                row[f"pct_{n}{suffix}"] = None
            rows.append(row)
            continue
        for n in periods:
            idx = -(n + 1)
            if len(closes) > n and closes[idx]:
                row[f"pct_{n}{suffix}"] = (cur - closes[idx]) / closes[idx]
            else:
                row[f"pct_{n}{suffix}"] = None
        rows.append(row)
    return pd.DataFrame(rows)


def compute_whipsaw_metrics(
    candles_by_symbol: dict[str, list],
    window_h: int,
) -> pd.DataFrame:
    """Compute Path/Net and Realized Vol over the last ``window_h`` closed 1H bars.

    ``pn_window``  = Σ|close[i] − close[i−1]| / |close[last] − close[first]|.
                     1.0 ≈ trend, large ≈ chop / whipsaw. Capped at PN_CAP.
    ``rv_window``  = std(hourly returns) × √window_h, returned as a fraction.
                     E.g. 0.054 → 5.4% typical swing over the window.

    Drops the in-progress current bar (``candles[-1]``) before computing.
    """
    import numpy as np

    rows = []
    for sym, candles in candles_by_symbol.items():
        row: dict[str, Any] = {"symbol": sym, "pn_window": None, "rv_window": None}
        # Need (window_h+1) closed bars to compute window_h hourly returns;
        # the last element is in-progress, so total bars must be ≥ window_h + 2.
        if not candles or len(candles) < window_h + 2:
            rows.append(row)
            continue
        try:
            tail = candles[-(window_h + 2):-1]   # last (window_h + 1) closed bars
            closes = [float(c[4]) for c in tail]
        except (ValueError, TypeError, IndexError):
            rows.append(row)
            continue
        if len(closes) < 2:
            rows.append(row)
            continue
        path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
        net = abs(closes[-1] - closes[0])
        if net > 1e-12:
            row["pn_window"] = min(path / net, PN_CAP)
        elif path > 0:
            row["pn_window"] = PN_CAP
        rets = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes)) if closes[i - 1]
        ]
        if rets:
            sigma = float(np.std(rets, ddof=0))
            row["rv_window"] = sigma * (window_h ** 0.5)
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

def _color_signed(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    if pd.isna(f):
        return ""
    if f > 0:
        return "color: #2A9D8F; font-weight: 600"
    if f < 0:
        return "color: #E63946; font-weight: 600"
    return ""


def display_label(key: str, window_h: int) -> str:
    """Resolve a column key to the friendly header used in the rendered table.

    ``pn_window`` / ``rv_window`` carry a static placeholder in COLUMN_LABELS
    so the sidebar selectors are stable, but the displayed header includes the
    chosen window (e.g. ``Path/Net 24h``).
    """
    if key == "pn_window":
        return f"Path/Net {window_h}h"
    if key == "rv_window":
        return f"RealVol {window_h}h"
    return COLUMN_LABELS.get(key, key)


def build_format_map(view_columns: list[str]) -> dict[str, str]:
    fmt: dict[str, str] = {}
    for col in view_columns:
        if col in PRICE_LABELS:
            fmt[col] = "{:,.4f}"
        elif col in PCT_LABELS:
            fmt[col] = "{:+.2%}"
        elif col in FUNDING_LABELS:
            fmt[col] = "{:+.2%}"
        elif col in QUOTE_LABELS:
            fmt[col] = "{:,.0f}"
        elif col in COIN_AMT_LABELS:
            fmt[col] = "{:,.2f}"
        elif col.startswith("RealVol "):
            fmt[col] = "{:.2%}"
        elif col.startswith("Path/Net "):
            fmt[col] = "{:.2f}"
    return fmt


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def main() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="Live Tickers — Bitget",
        page_icon="📡",
        layout="wide",
    )
    st.title("Live Tickers — Bitget USDT-M Futures")
    st.caption(
        "공개 REST API(`/api/v2/mix/market/tickers`)를 직접 폴링합니다. "
        "수집기 DB 와는 분리되어 있으며, 새로고침 주기마다 fresh 데이터를 가져옵니다."
    )

    all_keys = list(COLUMN_LABELS.keys())
    sort_default = "quoteVolume"

    with st.sidebar:
        st.header("Refresh")
        auto = st.toggle("Auto-refresh", value=True)
        interval = st.select_slider(
            "Interval (sec)",
            options=[5, 10, 30, 60],
            value=10,
        )
        manual = st.button("Refresh now", use_container_width=True)

        st.markdown("---")
        st.header("Period changes (candles)")
        compute_periods = st.toggle(
            "1h / 4h / 12h / 7d / 14d / 28d / PN / RV 계산",
            value=True,
            help=f"필터 후 화면에 보이는 심볼만 1H+1D 캔들을 가져와 계산합니다 (cap {CANDLE_FETCH_CAP}). 캔들 캐시 5분.",
        )

        st.markdown("---")
        st.header("Columns")
        display_cols = st.multiselect(
            "Show columns",
            options=all_keys,
            default=DEFAULT_DISPLAY,
            format_func=lambda k: COLUMN_LABELS.get(k, k),
        )

    if manual:
        st.cache_data.clear()

    @st.cache_data(ttl=3, show_spinner=False)
    def _cached_fetch() -> pd.DataFrame:
        return fetch_tickers()

    @st.cache_data(ttl=300, show_spinner=False)
    def _cached_candles(symbols_tuple: tuple[str, ...], granularity: str, limit: int) -> dict[str, list]:
        return fetch_candles_batch(list(symbols_tuple), granularity=granularity, limit=limit)

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

        fetched_at = datetime.now(timezone.utc).astimezone()
        col_a, col_b, col_c = st.columns([2, 1, 1])
        col_a.caption(f"Last fetched: **{fetched_at.strftime('%Y-%m-%d %H:%M:%S %Z')}**")
        col_b.metric("Symbols", f"{len(df):,}")
        col_c.metric("Mode", "Auto" if auto else "Manual")

        # Filter bar — sits right above the table, inside the fragment so
        # changing filters only re-runs the fragment (sidebar etc. stable).
        f1, f2, f3, f4, f5 = st.columns([3, 1, 2, 1, 1])
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
            sort_desc = st.toggle("Descending", value=True, key="flt_desc")
        with f5:
            whipsaw_window = st.select_slider(
                "Window (h)",
                options=WHIPSAW_WINDOW_OPTIONS,
                value=DEFAULT_WHIPSAW_WINDOW,
                key="flt_window",
                help="Path/Net 와 RealVol 계산 기간 (시간). 1H 캔들의 마지막 N개 종가 사용.",
            )

        # apply filter
        if search:
            df = df[df["symbol"].astype(str).str.contains(search, case=False, na=False)]
        if sort_col_key in df.columns:
            df = df.sort_values(sort_col_key, ascending=not sort_desc, na_position="last")
        if top_n > 0:
            df = df.head(int(top_n))

        if df.empty:
            st.info("필터 조건에 맞는 심볼이 없습니다.")
            return

        # 24h High/Low Δ% — derived from ticker fields, no extra API.
        if "markPrice" in df.columns and "high24h" in df.columns:
            df["pct_off_high24h"] = (df["markPrice"] - df["high24h"]) / df["high24h"].where(df["high24h"] != 0)
        if "markPrice" in df.columns and "low24h" in df.columns:
            df["pct_off_low24h"] = (df["markPrice"] - df["low24h"]) / df["low24h"].where(df["low24h"] != 0)

        # OI notional (USDT) — holdingAmount is in base coin, multiply by mark price.
        if "markPrice" in df.columns and "holdingAmount" in df.columns:
            df["oiNotional"] = df["markPrice"] * df["holdingAmount"]

        # Period % changes: 1H candles for 1h/4h/12h + PN/RV, 1D for 7d/14d/28d.
        visible_symbols = df["symbol"].astype(str).tolist()
        skipped_period_calc = False
        if compute_periods and visible_symbols:
            if len(visible_symbols) > CANDLE_FETCH_CAP:
                skipped_period_calc = True
            else:
                current_prices = dict(zip(df["symbol"].astype(str), df.get("markPrice", pd.Series(dtype=float))))
                try:
                    sym_tuple = tuple(sorted(visible_symbols))
                    with st.spinner(f"캔들 fetching 1H+1D ({len(visible_symbols)} symbols)…"):
                        hourly = _cached_candles(sym_tuple, "1H", 30)
                        daily = _cached_candles(sym_tuple, "1D", 30)
                    changes_h = compute_period_changes(current_prices, hourly, PERIODS_H, suffix="h")
                    changes_d = compute_period_changes(current_prices, daily, PERIODS_D, suffix="d")
                    whipsaw = compute_whipsaw_metrics(hourly, whipsaw_window)
                    if not changes_h.empty:
                        df = df.merge(changes_h, on="symbol", how="left")
                    if not changes_d.empty:
                        df = df.merge(changes_d, on="symbol", how="left")
                    if not whipsaw.empty:
                        df = df.merge(whipsaw, on="symbol", how="left")
                except Exception as e:
                    st.warning(f"기간 변화율 계산 실패: {e}")

        if skipped_period_calc:
            st.info(
                f"표시 심볼 {len(visible_symbols)}개 > cap({CANDLE_FETCH_CAP}). "
                "1h/4h/12h/7d/14d/28d/PN/RV 계산 스킵 — Top N 을 줄이거나 검색 필터를 적용하세요."
            )

        cols_present = [c for c in display_cols if c in df.columns]
        if not cols_present:
            st.warning("선택된 컬럼이 응답에 없습니다.")
            return

        view = df[cols_present].copy()
        view = view.rename(columns={c: display_label(c, whipsaw_window) for c in view.columns})

        fmt = build_format_map(list(view.columns))
        styled = view.style.format(fmt, na_rep="—")
        pct_cols_present = [c for c in (
            "1h %", "4h %", "12h %", "24h %", "24h % (UTC)",
            "7d %", "14d %", "28d %",
            "24h High Δ%", "24h Low Δ%",
        ) if c in view.columns]
        if pct_cols_present:
            styled = styled.map(_color_signed, subset=pct_cols_present)
        if "Funding" in view.columns:
            styled = styled.map(_color_signed, subset=["Funding"])

        st.dataframe(styled, use_container_width=True, hide_index=True, height=720)

        with st.expander("응답 원본 컬럼 (디버그)"):
            st.write(sorted(df.columns.tolist()))

    render_data_section()


main()
