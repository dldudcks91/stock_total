"""Live ticker table for NASDAQ stocks — Bitget-style.

Live prices: Naver Finance unofficial per-symbol endpoint
``https://api.stock.naver.com/stock/{TICKER}.O/basic`` (fanned out in parallel).

Universe is the set of NASDAQ tickers already cached in ``data/cache/us/*.parquet``
(see ``us-fetch`` skill). To add a symbol, fetch it once and the page picks it
up on next refresh.

Period %, MA Δ%, Window High/Low Δ% come from the local 1D parquet cache.
Period columns fixed at 1d / 3d / 7d / 14d / 28d / 56d / 140d; window selector
toggles MA/HL stride purely client-side via JsCode valueGetter.

Layout mirrors the Bitget page: AgGrid client-side grid, modal chart dialog,
persisted ``메모`` column, sidebar "NASDAQ 데이터 받기" background fetch.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.loader import load_ohlcv  # noqa: E402
from dashboards._lib import render_fetch_log_sidebar  # noqa: E402
from dashboards._stock_grid import (  # noqa: E402
    DEFAULT_WINDOW,
    PERIODS_D,
    STOCK_PAGE_CSS,
    WINDOW_OPTIONS,
    build_stock_grid_options,
    compute_from_cache,
    load_cache_tails,
    load_notes,
    render_tv_chart_stock,
    save_notes,
)

try:
    from streamlit_lightweight_charts import renderLightweightCharts  # type: ignore # noqa: F401
    _HAS_LWC = True
except ImportError:  # pragma: no cover
    _HAS_LWC = False

from st_aggrid import AgGrid, GridUpdateMode  # noqa: E402

US_CACHE_DIR = _ROOT / "data" / "cache" / "us"
NOTES_PATH = US_CACHE_DIR / "_notes.json"

NAVER_BASIC_URL = "https://api.stock.naver.com/stock/{ticker}.O/basic"
FETCH_CONCURRENCY = 10
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

COLUMN_LABELS: dict[str, str] = {
    "symbolCode": "Symbol",
    "stockNameEng": "Name",
    "closePrice": "Last",
    "fluctuationsRatio": "Change %",
    "accumulatedTradingVolume": "Volume",
    "marketValueRaw": "시총 (USD)",
    **{f"pct_{n}d": f"{n}d %" for n in PERIODS_D},
}


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------

def discover_universe() -> list[str]:
    """Return cached NASDAQ tickers sorted alphabetically."""
    if not US_CACHE_DIR.exists():
        return []
    return sorted(p.stem for p in US_CACHE_DIR.glob("*.parquet") if not p.stem.startswith("_"))


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

async def _fetch_one(session, sem, ticker: str) -> tuple[str, Optional[dict[str, Any]]]:
    import aiohttp
    url = NAVER_BASIC_URL.format(ticker=ticker)
    async with sem:
        try:
            async with session.get(
                url,
                headers={"User-Agent": USER_AGENT, "Referer": "https://m.stock.naver.com/"},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status != 200:
                    return ticker, None
                return ticker, await r.json()
        except Exception:
            return ticker, None


async def _fetch_universe_async(tickers: list[str]) -> dict[str, dict[str, Any]]:
    import aiohttp
    sem = asyncio.Semaphore(FETCH_CONCURRENCY)
    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_one(session, sem, t) for t in tickers]
        results = await asyncio.gather(*tasks)
    return {sym: payload for sym, payload in results if payload is not None}


def fetch_universe(tickers: list[str]) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    payloads = asyncio.run(_fetch_universe_async(tickers))
    rows = [_normalize(sym, p) for sym, p in payloads.items()]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _normalize(symbol: str, p: dict[str, Any]) -> dict[str, Any]:
    totals = {item.get("code"): item.get("value") for item in (p.get("stockItemTotalInfos") or [])}
    row: dict[str, Any] = {
        "symbolCode": p.get("symbolCode") or symbol,
        "stockName": p.get("stockName"),
        "stockNameEng": p.get("stockNameEng"),
        "closePrice": _to_float(p.get("closePrice")),
        "fluctuationsRatio": _to_pct(p.get("fluctuationsRatio")),
        "accumulatedTradingVolume": _to_float(totals.get("accumulatedTradingVolume")),
        "marketValueRaw": _parse_market_value_usd(totals.get("marketValue")),
        "marketStatus": p.get("marketStatus"),
        "localTradedAt": p.get("localTradedAt"),
    }
    direction = (p.get("compareToPreviousPrice") or {}).get("code")
    if direction in {"4", "5"} and row["fluctuationsRatio"] is not None:
        row["fluctuationsRatio"] = -abs(row["fluctuationsRatio"])
    return row


def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None or x == "" or x == "N/A":
            return None
        return float(str(x).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _to_pct(x: Any) -> Optional[float]:
    v = _to_float(x)
    return None if v is None else v / 100.0


# Parses Naver-formatted USD market-cap strings like "4조 2,914억 USD".
# 1조 = 10^12, 1억 = 10^8 (Korean accounting digit-grouping).
_MV_RE = re.compile(
    r"(?:(?P<jo>\d+(?:[\d,]*\d)?)\s*조\s*)?"
    r"(?:(?P<eok>\d+(?:[\d,]*\d)?)\s*억)?",
)


def _parse_market_value_usd(s: Any) -> Optional[float]:
    if s is None or s == "" or s == "N/A":
        return None
    s = str(s).strip()
    plain = _to_float(s.replace("USD", "").strip())
    if plain is not None and "조" not in s and "억" not in s:
        return plain
    m = _MV_RE.search(s)
    if not m or not (m.group("jo") or m.group("eok")):
        return None
    jo = _to_float(m.group("jo")) or 0.0
    eok = _to_float(m.group("eok")) or 0.0
    return jo * 1e12 + eok * 1e8


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="NASDAQ", page_icon="🇺🇸", layout="wide")
    render_fetch_log_sidebar(st)
    st.markdown(STOCK_PAGE_CSS, unsafe_allow_html=True)

    sort_options = list(COLUMN_LABELS.keys())
    sort_default = "marketValueRaw"

    universe = discover_universe()
    if not universe:
        st.warning(
            "`data/cache/us/` 가 비어 있습니다. 사이드바의 `NASDAQ 데이터 받기` 로 NASDAQ 일봉을 받아주세요."
        )

    with st.sidebar:
        st.header("Refresh")
        auto = st.toggle("Auto-refresh", value=False, key="nas_auto")
        interval = st.select_slider(
            "Interval (sec)", options=[15, 30, 60, 120], value=60, key="nas_interval",
        )
        manual = st.button("Refresh now", use_container_width=True, key="nas_manual")

        st.markdown("---")
        st.header("Universe")
        st.caption(f"캐시된 NASDAQ 심볼: **{len(universe)}** 개")
        limit = st.slider(
            "Fetch limit (alphabetical from cache)",
            min_value=20,
            max_value=max(20, min(500, len(universe) or 20)),
            value=min(100, len(universe) or 20),
            step=10, key="nas_limit",
            help="네트워크 라운드트립 비용 ≈ ceil(N / concurrency) × ~0.3s.",
        ) if universe else 0

        st.markdown("---")
        fetch_proc = st.session_state.get("nas_fetch_proc")
        fetch_running = fetch_proc is not None and fetch_proc.poll() is None
        fetch_btn = st.button(
            "NASDAQ 데이터 받기" if not fetch_running else "Fetching… (background)",
            use_container_width=True,
            key="nas_fetch_btn",
            disabled=fetch_running,
            help="FDR 로 NASDAQ 전 종목 일봉을 data/cache/us/ 로 증분 다운로드. 백그라운드 실행.",
        )

    if manual:
        st.cache_data.clear()

    _fetch_log = US_CACHE_DIR / "_fetch.log"

    if fetch_btn and not fetch_running:
        import subprocess
        _fetch_log.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(_fetch_log, "w", encoding="utf-8", buffering=1)
        new_proc = subprocess.Popen(
            [sys.executable, "-m", "data.sources.stocks", "--market", "NASDAQ"],
            cwd=str(_ROOT),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        st.session_state["nas_fetch_proc"] = new_proc
        st.session_state["nas_fetch_started"] = pd.Timestamp.now(tz="Asia/Seoul").isoformat(timespec="seconds")
        st.session_state["nas_fetch_finalized"] = False
        st.rerun()

    with st.sidebar:
        if fetch_running or fetch_proc is not None:
            try:
                log_text = _fetch_log.read_text(encoding="utf-8", errors="replace")
            except FileNotFoundError:
                log_text = ""
            tail = log_text.splitlines()[-8:]
        if fetch_running:
            st.info(f"⏳ NASDAQ fetch 진행 중 (시작 {st.session_state.get('nas_fetch_started','?')})")
            if tail:
                st.code("\n".join(tail))
            if st.button("🔄 상태 갱신", use_container_width=True, key="nas_fetch_refresh"):
                st.rerun()
        elif fetch_proc is not None:
            rc = fetch_proc.returncode
            if not st.session_state.get("nas_fetch_finalized"):
                if rc == 0:
                    st.cache_data.clear()
                st.session_state["nas_fetch_finalized"] = True
            if rc == 0:
                st.success("✅ NASDAQ fetch 완료")
            else:
                st.error(f"❌ NASDAQ fetch 실패 (rc={rc})")
            if tail:
                st.code("\n".join(tail))
            if st.button("Dismiss", use_container_width=True, key="nas_fetch_dismiss"):
                st.session_state["nas_fetch_proc"] = None
                st.session_state["nas_fetch_finalized"] = False
                st.rerun()

    if not universe:
        return

    @st.cache_data(ttl=60, show_spinner=False)
    def _cached_universe(tickers_tuple: tuple[str, ...]) -> pd.DataFrame:
        return fetch_universe(list(tickers_tuple))

    @st.cache_data(ttl=300, show_spinner=False)
    def _cached_cache_tails(ticker: str, n: int):
        return load_cache_tails(US_CACHE_DIR / f"{ticker}.parquet", n)

    @st.cache_data(ttl=60, show_spinner=False)
    def _cached_compute_all_windows(
        symbols_tuple: tuple,
        prices_items: tuple,
    ) -> pd.DataFrame:
        current_prices = dict(prices_items)
        return compute_from_cache(
            current_prices, list(symbols_tuple),
            cache_loader=_cached_cache_tails,
        )

    @st.cache_data(ttl=300, show_spinner=False)
    def _chart_df_cached(symbol: str, iv: str) -> pd.DataFrame:
        if iv == "1M":
            daily = load_ohlcv("us", symbol, "1d")
            return daily.resample("ME").agg(
                {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
            ).dropna()
        return load_ohlcv("us", symbol, iv)

    def _render_inline_chart(symbol: str, name: str) -> None:
        with st.container(key="stock_chart_iv_picker"):
            chart_iv = st.segmented_control(
                "Interval",
                options=["1d", "1w", "1M"],
                default="1w",
                key="nas_chart_iv",
                label_visibility="collapsed",
            )
        if not chart_iv:
            chart_iv = "1w"
        try:
            cdf = _chart_df_cached(symbol, chart_iv)
        except FileNotFoundError:
            st.warning(f"`{symbol}` 캐시 없음 — `NASDAQ 데이터 받기` 로 먼저 받아주세요.")
            return
        except Exception as e:  # noqa: BLE001
            st.warning(f"{symbol} 캐시 로드 실패: {e}")
            return
        if cdf is None or len(cdf) == 0:
            st.warning(f"{symbol} 데이터 비어있음")
            return
        if not _HAS_LWC:
            st.warning(
                "`streamlit-lightweight-charts` 미설치 — "
                "`.venv/Scripts/python.exe -m pip install streamlit-lightweight-charts`"
            )
            return
        render_tv_chart_stock(
            symbol, f"{name} · {symbol}", chart_iv, cdf, key_prefix="lwc_nasdaq",
        )

    @st.dialog(" ", width="large")
    def _chart_dialog() -> None:
        sym = st.session_state.get("nas_sel_symbol")
        if not sym:
            return
        name = st.session_state.get("nas_sel_name") or sym
        _render_inline_chart(sym, name)

    run_every = interval if auto else None

    @st.fragment(run_every=run_every)
    def render_data_section() -> None:
        f1, f2, f3, f4 = st.columns([3, 1, 2, 3])
        with f1:
            search = st.text_input("Symbol / name contains", value="", key="nas_search").strip()
        with f2:
            top_n = st.number_input(
                "Top N (0 = all)",
                min_value=0, max_value=2000, value=0, step=50,
                key="nas_topn",
            )
        with f3:
            sort_col_key = st.selectbox(
                "Sort by",
                options=sort_options,
                index=sort_options.index(sort_default),
                format_func=lambda k: COLUMN_LABELS.get(k, k),
                key="nas_sort",
            )
        with f4:
            window_label = st.segmented_control(
                "Window",
                options=WINDOW_OPTIONS,
                default=DEFAULT_WINDOW,
                key="nas_window",
                help="Window High/Low Δ% 기간 + MA10/MA20 봉 stride. "
                     "예) 28d → MA10 = 28일 봉 10개 평균(=280일).",
            )
            if not window_label:
                window_label = DEFAULT_WINDOW

        chosen = universe[: int(limit)]
        try:
            with st.spinner(f"Naver 시세 fetching ({len(chosen)} symbols, concurrency={FETCH_CONCURRENCY})…"):
                df = _cached_universe(tuple(chosen))
        except Exception as e:
            st.error(f"Naver API 실패: {e}")
            return

        if df.empty:
            st.warning("응답이 비어 있습니다. Naver 비공식 엔드포인트가 차단됐을 수 있습니다.")
            return

        symbols_all = df["symbolCode"].dropna().astype(str).tolist()
        if symbols_all:
            current_prices = dict(zip(symbols_all, df.get("closePrice", pd.Series(dtype=float))))
            try:
                with st.spinner(f"캐시 계산 ({len(symbols_all)}개, all windows)…"):
                    derived = _cached_compute_all_windows(
                        tuple(symbols_all),
                        tuple(sorted(current_prices.items())),
                    )
                if not derived.empty:
                    derived = derived.rename(columns={"symbol": "symbolCode"})
                    overlap = [c for c in derived.columns
                               if c != "symbolCode" and c in df.columns]
                    if overlap:
                        df = df.drop(columns=overlap)
                    df = df.merge(derived, on="symbolCode", how="left")
            except Exception as e:
                st.warning(f"캐시 계산 실패: {e}")

        if search:
            mask = (
                df["symbolCode"].astype(str).str.contains(search, case=False, na=False)
                | df["stockNameEng"].astype(str).str.contains(search, case=False, na=False)
                | df["stockName"].astype(str).str.contains(search, case=False, na=False)
            )
            df = df[mask]
        if sort_col_key in df.columns:
            df = df.sort_values(sort_col_key, ascending=False, na_position="last")
        if top_n > 0:
            df = df.head(int(top_n))
        df = df.reset_index(drop=True)

        if df.empty:
            st.info("필터 조건에 맞는 종목이 없습니다.")
            return

        notes = st.session_state.setdefault("nas_notes", load_notes(NOTES_PATH))
        df["note"] = df["symbolCode"].astype(str).map(notes).fillna("")

        SEL_KEY = "nas_sel_symbol"
        selected_symbol: Optional[str] = st.session_state.get(SEL_KEY)
        if selected_symbol and not (df["symbolCode"] == selected_symbol).any():
            st.session_state.pop(SEL_KEY, None)
            selected_symbol = None

        df_grid, grid_options = build_stock_grid_options(
            df, window_label, selected_symbol,
            symbol_col="symbolCode", symbol_header="Symbol",
            name_col="stockNameEng", name_header="Name",
            price_col="closePrice", price_format="dec",
            volume_col="accumulatedTradingVolume", volume_header="Volume",
            market_cap_col="marketValueRaw", market_cap_header="시총 (USD)",
        )
        grid_key = f"nas_grid::{top_n}::{search}::{sort_col_key}::{limit}"
        grid_resp = AgGrid(
            df_grid,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.SELECTION_CHANGED | GridUpdateMode.VALUE_CHANGED,
            allow_unsafe_jscode=True,
            fit_columns_on_grid_load=False,
            height=720,
            theme="streamlit",
            key=grid_key,
        )

        # ── Persist memo edits (silent) ──
        edited_df = grid_resp.get("data")
        if edited_df is not None and "note" in edited_df.columns:
            notes_changed = False
            for sym, new_val in zip(edited_df["symbolCode"].astype(str), edited_df["note"].astype(str)):
                new_val = (new_val or "").strip()
                cur_val = notes.get(sym, "")
                if new_val != cur_val:
                    if new_val:
                        notes[sym] = new_val
                    else:
                        notes.pop(sym, None)
                    notes_changed = True
            if notes_changed:
                save_notes(NOTES_PATH, notes)

        # ── Selection → chart dialog ──
        sel_rows = grid_resp.get("selected_rows")
        new_sel: Optional[str] = None
        new_name: Optional[str] = None
        if sel_rows is not None:
            if isinstance(sel_rows, pd.DataFrame) and len(sel_rows):
                new_sel = str(sel_rows.iloc[0].get("symbolCode", "")) or None
                new_name = str(sel_rows.iloc[0].get("stockNameEng", "")) or None
            elif isinstance(sel_rows, list) and sel_rows:
                first = sel_rows[0]
                if isinstance(first, dict):
                    new_sel = str(first.get("symbolCode", "")) or None
                    new_name = str(first.get("stockNameEng", "")) or None
        if new_sel != selected_symbol:
            if new_sel:
                st.session_state[SEL_KEY] = new_sel
                st.session_state["nas_sel_name"] = new_name or new_sel
            else:
                st.session_state.pop(SEL_KEY, None)
                st.session_state.pop("nas_sel_name", None)
            st.rerun(scope="fragment")

        cur_sel = st.session_state.get(SEL_KEY)
        last_shown = st.session_state.get("_nas_chart_dialog_shown_for")
        if cur_sel and cur_sel != last_shown:
            st.session_state["_nas_chart_dialog_shown_for"] = cur_sel
            _chart_dialog()
        elif not cur_sel and last_shown is not None:
            st.session_state.pop("_nas_chart_dialog_shown_for", None)

        missing = set(chosen) - set(df["symbolCode"].astype(str).tolist())
        with st.expander("응답 원본 컬럼 (디버그)"):
            st.write(sorted(df.columns.tolist()))
            if missing:
                st.write(f"응답 없음 ({len(missing)}): ", sorted(missing))

    render_data_section()


main()
