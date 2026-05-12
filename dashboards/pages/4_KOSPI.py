"""Live ticker table for KOSPI stocks — Bitget-style.

Live prices: Naver Finance unofficial mobile endpoint
``https://m.stock.naver.com/api/stocks/marketValue/KOSPI``.

Period %, MA Δ%, Window High/Low Δ% come from the local 1D parquet cache
(``data/cache/kr/{6digits}.parquet``). Period columns are fixed at
1d / 3d / 7d / 14d / 28d / 56d / 140d. The window selector flips MA10/MA20
and High/Low Δ% values purely on the client (no server recompute) — the
underlying row data already carries every window's value with a
``__{window}`` suffix.

Layout mirrors the Bitget page: AgGrid client-side grid, modal chart dialog,
persisted ``메모`` column, sidebar "KOSPI 데이터 받기" background fetch.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests

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

KR_CACHE_DIR = _ROOT / "data" / "cache" / "kr"
NOTES_PATH = KR_CACHE_DIR / "_notes.json"

NAVER_LIST_URL = "https://m.stock.naver.com/api/stocks/marketValue/{exchange}"
NAVER_PAGE_SIZE = 100
FETCH_CONCURRENCY = 4
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Column labels for the "Sort by" dropdown (raw API keys → friendly names).
COLUMN_LABELS: dict[str, str] = {
    "itemCode": "Code",
    "stockName": "Name",
    "closePrice": "Price",
    "fluctuationsRatio": "Change",
    "accumulatedTradingValue": "거래대금 (KRW)",
    "marketValue": "시총 (KRW)",
    "accumulatedTradingVolume": "Volume",
    **{f"pct_{n}d": f"{n}d" for n in PERIODS_D},
}


# ---------------------------------------------------------------------------
# Naver fetch (live ticker snapshot)
# ---------------------------------------------------------------------------

def _fetch_page(exchange: str, page: int, page_size: int, timeout: float = 8.0) -> dict[str, Any]:
    resp = requests.get(
        NAVER_LIST_URL.format(exchange=exchange),
        params={"page": page, "pageSize": page_size},
        headers={"User-Agent": USER_AGENT, "Referer": "https://m.stock.naver.com/"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


async def _fetch_page_async(session, sem, exchange: str, page: int, page_size: int) -> dict[str, Any]:
    import aiohttp
    params = {"page": page, "pageSize": page_size}
    async with sem:
        try:
            async with session.get(
                NAVER_LIST_URL.format(exchange=exchange), params=params,
                headers={"User-Agent": USER_AGENT, "Referer": "https://m.stock.naver.com/"},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                return await r.json()
        except Exception:
            return {"stocks": []}


async def _fetch_pages_async(exchange: str, total_pages: int, page_size: int) -> list[dict[str, Any]]:
    import aiohttp
    sem = asyncio.Semaphore(FETCH_CONCURRENCY)
    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_page_async(session, sem, exchange, p, page_size) for p in range(1, total_pages + 1)]
        return await asyncio.gather(*tasks)


def fetch_market(exchange: str, top_n: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    page_size = NAVER_PAGE_SIZE
    total_pages = max(1, -(-top_n // page_size))
    first = _fetch_page(exchange, 1, page_size)
    meta = {
        "marketStatus": first.get("marketStatus"),
        "totalCount": first.get("totalCount"),
        "localOpenTimeDesc": first.get("localOpenTimeDesc"),
    }
    stocks = list(first.get("stocks", []))
    if total_pages > 1:
        rest = asyncio.run(_fetch_pages_async(exchange, total_pages, page_size))
        for payload in rest[1:]:
            stocks.extend(payload.get("stocks", []))
    stocks = stocks[:top_n]
    return _normalize(stocks), meta


def _normalize(stocks: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for s in stocks:
        rows.append({
            "itemCode": s.get("itemCode"),
            "stockName": s.get("stockName"),
            "closePrice": _to_float(s.get("closePriceRaw")),
            "fluctuationsRatio": _to_pct(s.get("fluctuationsRatio")),
            "accumulatedTradingVolume": _to_float(s.get("accumulatedTradingVolumeRaw")),
            "accumulatedTradingValue": _to_float(s.get("accumulatedTradingValueRaw")),
            "marketValue": _to_float(s.get("marketValueRaw")),
            "marketStatus": s.get("marketStatus"),
            "localTradedAt": s.get("localTradedAt"),
        })
        direction = (s.get("compareToPreviousPrice") or {}).get("code")
        if direction in {"4", "5"} and rows[-1]["fluctuationsRatio"] is not None:
            rows[-1]["fluctuationsRatio"] = -abs(rows[-1]["fluctuationsRatio"])
    return pd.DataFrame(rows)


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


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="KOSPI", page_icon="🇰🇷", layout="wide")
    render_fetch_log_sidebar(st)
    st.markdown(STOCK_PAGE_CSS, unsafe_allow_html=True)

    sort_options = list(COLUMN_LABELS.keys())
    sort_default = "marketValue"

    with st.sidebar:
        st.header("Refresh")
        auto = st.toggle("Auto-refresh", value=False, key="kospi_auto")
        interval = st.select_slider(
            "Interval (sec)", options=[10, 30, 60, 120], value=30, key="kospi_interval",
        )
        manual = st.button("Refresh now", use_container_width=True, key="kospi_manual")

        fetch_proc = st.session_state.get("kospi_fetch_proc")
        fetch_running = fetch_proc is not None and fetch_proc.poll() is None
        fetch_btn = st.button(
            "KOSPI 데이터 받기" if not fetch_running else "Fetching… (background)",
            use_container_width=True,
            key="kospi_fetch_btn",
            disabled=fetch_running,
            help="FDR 로 KOSPI 전 종목 일봉을 data/cache/kr/ 로 증분 다운로드. 백그라운드 실행.",
        )

    if manual:
        st.cache_data.clear()

    _fetch_log = KR_CACHE_DIR / "_fetch.log"

    if fetch_btn and not fetch_running:
        import subprocess
        _fetch_log.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(_fetch_log, "w", encoding="utf-8", buffering=1)
        new_proc = subprocess.Popen(
            [sys.executable, "-m", "data.sources.stocks", "--market", "KOSPI"],
            cwd=str(_ROOT),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        st.session_state["kospi_fetch_proc"] = new_proc
        st.session_state["kospi_fetch_started"] = pd.Timestamp.now(tz="Asia/Seoul").isoformat(timespec="seconds")
        st.session_state["kospi_fetch_finalized"] = False
        st.rerun()

    with st.sidebar:
        if fetch_running or fetch_proc is not None:
            try:
                log_text = _fetch_log.read_text(encoding="utf-8", errors="replace")
            except FileNotFoundError:
                log_text = ""
            tail = log_text.splitlines()[-8:]
        if fetch_running:
            st.info(f"⏳ KOSPI fetch 진행 중 (시작 {st.session_state.get('kospi_fetch_started','?')})")
            if tail:
                st.code("\n".join(tail))
            if st.button("🔄 상태 갱신", use_container_width=True, key="kospi_fetch_refresh"):
                st.rerun()
        elif fetch_proc is not None:
            rc = fetch_proc.returncode
            if not st.session_state.get("kospi_fetch_finalized"):
                if rc == 0:
                    st.cache_data.clear()
                st.session_state["kospi_fetch_finalized"] = True
            if rc == 0:
                st.success("✅ KOSPI fetch 완료")
            else:
                st.error(f"❌ KOSPI fetch 실패 (rc={rc})")
            if tail:
                st.code("\n".join(tail))
            if st.button("Dismiss", use_container_width=True, key="kospi_fetch_dismiss"):
                st.session_state["kospi_fetch_proc"] = None
                st.session_state["kospi_fetch_finalized"] = False
                st.rerun()

    @st.cache_data(ttl=5, show_spinner=False)
    def _cached_market(exchange: str, n: int):
        return fetch_market(exchange, n)

    @st.cache_data(ttl=300, show_spinner=False)
    def _cached_cache_tails(code: str, n: int):
        return load_cache_tails(KR_CACHE_DIR / f"{code}.parquet", n)

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
            daily = load_ohlcv("kr", symbol, "1d")
            return daily.resample("ME").agg(
                {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
            ).dropna()
        return load_ohlcv("kr", symbol, iv)

    def _render_inline_chart(code: str, name: str) -> None:
        with st.container(key="stock_chart_iv_picker"):
            chart_iv = st.segmented_control(
                "Interval",
                options=["1d", "1w", "1M"],
                default="1w",
                key="kospi_chart_iv",
                label_visibility="collapsed",
            )
        if not chart_iv:
            chart_iv = "1w"
        try:
            cdf = _chart_df_cached(code, chart_iv)
        except FileNotFoundError:
            st.warning(f"`{code}` 캐시 없음 — `KOSPI 데이터 받기` 로 먼저 받아주세요.")
            return
        except Exception as e:  # noqa: BLE001
            st.warning(f"{code} 캐시 로드 실패: {e}")
            return
        if cdf is None or len(cdf) == 0:
            st.warning(f"{code} 데이터 비어있음")
            return
        if not _HAS_LWC:
            st.warning(
                "`streamlit-lightweight-charts` 미설치 — "
                "`.venv/Scripts/python.exe -m pip install streamlit-lightweight-charts`"
            )
            return
        render_tv_chart_stock(
            code, f"{name} · {code}", chart_iv, cdf, key_prefix="lwc_kospi",
        )

    @st.dialog(" ", width="large")
    def _chart_dialog() -> None:
        code = st.session_state.get("kospi_sel_code")
        if not code:
            return
        name = st.session_state.get("kospi_sel_name") or code
        _render_inline_chart(code, name)

    run_every = interval if auto else None

    @st.fragment(run_every=run_every)
    def render_data_section() -> None:
        f1, f2, f3, f4 = st.columns([3, 1, 2, 3])
        with f1:
            search = st.text_input("Name / code contains", value="", key="kospi_search").strip()
        with f2:
            top_n = st.number_input(
                "Top N (0 = all)",
                min_value=0, max_value=2000, value=0, step=50,
                key="kospi_topn",
            )
        with f3:
            sort_col_key = st.selectbox(
                "Sort by",
                options=sort_options,
                index=sort_options.index(sort_default),
                format_func=lambda k: COLUMN_LABELS.get(k, k),
                key="kospi_sort",
            )
        with f4:
            window_label = st.segmented_control(
                "Window",
                options=WINDOW_OPTIONS,
                default=DEFAULT_WINDOW,
                key="kospi_window",
                help="Window High/Low Δ% 기간 + MA10/MA20 봉 stride. "
                     "예) 28d → MA10 = 28일 봉 10개 평균(=280일).",
            )
            if not window_label:
                window_label = DEFAULT_WINDOW

        fetch_n = int(top_n) if top_n > 0 else 1000
        try:
            with st.spinner(f"Naver 시세 fetching (top {fetch_n})…"):
                df, _meta = _cached_market("KOSPI", fetch_n)
        except Exception as e:
            st.error(f"Naver API 실패: {e}")
            return

        if df.empty:
            st.warning("응답이 비어 있습니다.")
            return

        codes_all = df["itemCode"].dropna().astype(str).tolist()
        if codes_all:
            current_prices = dict(zip(codes_all, df.get("closePrice", pd.Series(dtype=float))))
            try:
                with st.spinner(f"캐시 계산 ({len(codes_all)}개, all windows)…"):
                    derived = _cached_compute_all_windows(
                        tuple(codes_all),
                        tuple(sorted(current_prices.items())),
                    )
                if not derived.empty:
                    derived = derived.rename(columns={"symbol": "itemCode"})
                    overlap = [c for c in derived.columns
                               if c != "itemCode" and c in df.columns]
                    if overlap:
                        df = df.drop(columns=overlap)
                    df = df.merge(derived, on="itemCode", how="left")
            except Exception as e:
                st.warning(f"캐시 계산 실패: {e}")

        if search:
            mask = (
                df["stockName"].astype(str).str.contains(search, case=False, na=False)
                | df["itemCode"].astype(str).str.contains(search, case=False, na=False)
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

        notes = st.session_state.setdefault("kospi_notes", load_notes(NOTES_PATH))
        df["note"] = df["itemCode"].astype(str).map(notes).fillna("")

        SEL_KEY = "kospi_sel_code"
        selected_symbol: Optional[str] = st.session_state.get(SEL_KEY)
        if selected_symbol and not (df["itemCode"] == selected_symbol).any():
            st.session_state.pop(SEL_KEY, None)
            selected_symbol = None

        df_grid, grid_options = build_stock_grid_options(
            df, window_label, selected_symbol,
            symbol_col="itemCode", symbol_header="Code",
            name_col="stockName", name_header="Name",
            price_col="closePrice", price_header="Price", price_format="int",
            volume_col="accumulatedTradingValue", volume_header="거래대금",
            volume_format="millions",
            market_cap_col="marketValue", market_cap_header="시총",
            market_cap_format="millions",
            pct_header_suffix="",
        )
        grid_key = f"kospi_grid::{top_n}::{search}::{sort_col_key}"
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
            for code, new_val in zip(edited_df["itemCode"].astype(str), edited_df["note"].astype(str)):
                new_val = (new_val or "").strip()
                cur_val = notes.get(code, "")
                if new_val != cur_val:
                    if new_val:
                        notes[code] = new_val
                    else:
                        notes.pop(code, None)
                    notes_changed = True
            if notes_changed:
                save_notes(NOTES_PATH, notes)

        # ── Selection → chart dialog ──
        sel_rows = grid_resp.get("selected_rows")
        new_sel: Optional[str] = None
        new_name: Optional[str] = None
        if sel_rows is not None:
            if isinstance(sel_rows, pd.DataFrame) and len(sel_rows):
                new_sel = str(sel_rows.iloc[0].get("itemCode", "")) or None
                new_name = str(sel_rows.iloc[0].get("stockName", "")) or None
            elif isinstance(sel_rows, list) and sel_rows:
                first = sel_rows[0]
                if isinstance(first, dict):
                    new_sel = str(first.get("itemCode", "")) or None
                    new_name = str(first.get("stockName", "")) or None
        if new_sel != selected_symbol:
            if new_sel:
                st.session_state[SEL_KEY] = new_sel
                st.session_state["kospi_sel_name"] = new_name or new_sel
            else:
                st.session_state.pop(SEL_KEY, None)
                st.session_state.pop("kospi_sel_name", None)
            st.rerun(scope="fragment")

        cur_sel = st.session_state.get(SEL_KEY)
        last_shown = st.session_state.get("_kospi_chart_dialog_shown_for")
        if cur_sel and cur_sel != last_shown:
            st.session_state["_kospi_chart_dialog_shown_for"] = cur_sel
            _chart_dialog()
        elif not cur_sel and last_shown is not None:
            st.session_state.pop("_kospi_chart_dialog_shown_for", None)

        with st.expander("응답 원본 컬럼 (디버그)"):
            st.write(sorted(df.columns.tolist()))

    render_data_section()


main()
