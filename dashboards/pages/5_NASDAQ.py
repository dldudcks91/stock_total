"""Live ticker table for NASDAQ stocks — Bitget-style.

Live prices come from a persisted snapshot
(``data/cache/us/_live_snapshot.parquet``). The page reads the snapshot on
render and never auto-fetches. The sidebar "라이브 가격 갱신" button kicks off
a background subprocess (``python -m data.sources.naver_us``) that merges
fresh Naver data into the snapshot (tickers absent from this round retain
previous values), then atomically replaces the file. The next page rerun
picks up the new snapshot.

Universe (for fallback / count) is the set of tickers already cached in
``data/cache/us/*.parquet`` (see ``us-fetch`` skill).

Period %, MA Δ%, High/Low Δ% come from the local 1D parquet cache.
Period columns fixed at 1d / 3d / 7d / 14d / 28d / 56d / 140d. Two independent
selectors: "MA Interval" (1d/1w/1M) picks the bar unit for MA10/MA20 (matches
the exchange-standard MA line on the candle chart); "HL Lookback"
(7d/28d/90d/1y/5y) picks the calendar window for High/Low Δ%. Both flip
client-side via JsCode valueGetter.

Layout: AgGrid client-side grid, modal chart dialog, persisted ``메모`` column,
sidebar background-subprocess buttons for snapshot refresh and FDR fetch.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.loader import load_ohlcv  # noqa: E402
from data.sources.naver_us import (  # noqa: E402
    SNAPSHOT_PATH,
    discover_universe,
    load_snapshot,
)
from dashboards._lib import render_fetch_log_sidebar  # noqa: E402
from dashboards._stock_grid import (  # noqa: E402
    DEFAULT_HL_LOOKBACK,
    DEFAULT_MA_INTERVAL,
    HL_LOOKBACK_OPTIONS,
    MA_INTERVAL_OPTIONS,
    PERIODS_D,
    STOCK_PAGE_CSS,
    build_stock_grid_options,
    compute_from_cache,
    load_cache_tails,
    load_notes,
    render_chart_memo,
    render_chart_title,
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

COLUMN_LABELS: dict[str, str] = {
    "symbolCode": "Symbol",
    "stockNameEng": "Name",
    "closePrice": "Last",
    "fluctuationsRatio": "Change %",
    "accumulatedTradingVolume": "Volume",
    "marketValueRaw": "시총 (USD)",
    **{f"pct_{n}d": f"{n}d %" for n in PERIODS_D},
}


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
# Page
# ---------------------------------------------------------------------------

def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="NASDAQ", page_icon="🇺🇸", layout="wide")
    st.markdown(STOCK_PAGE_CSS, unsafe_allow_html=True)

    sort_options = list(COLUMN_LABELS.keys())
    sort_default = "marketValueRaw"

    universe = discover_universe()
    if not universe:
        st.warning(
            "`data/cache/us/` 가 비어 있습니다. 사이드바의 `NASDAQ 데이터 받기` 로 NASDAQ 일봉을 받아주세요."
        )

    with st.sidebar:
        st.header("Universe")
        st.caption(f"캐시된 NASDAQ 심볼: **{len(universe)}** 개")

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

        live_proc = st.session_state.get("nas_live_proc")
        live_running = live_proc is not None and live_proc.poll() is None
        live_btn = st.button(
            "라이브 가격 갱신" if not live_running else "Fetching… (background)",
            use_container_width=True,
            key="nas_live_btn",
            disabled=live_running,
            help="Naver 비공식 API로 전 종목 라이브 가격을 받아 "
                 "_live_snapshot.parquet 에 머지 저장. 백그라운드.",
        )

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

        # 최근 내려받은 데이터 — 데이터 받기 버튼 아래에 상시 노출.
        render_fetch_log_sidebar(st, embedded=True)

    _fetch_log = US_CACHE_DIR / "_fetch.log"
    _live_log = US_CACHE_DIR / "_live_fetch.log"

    if live_btn and not live_running:
        import subprocess
        _live_log.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(_live_log, "w", encoding="utf-8", buffering=1)
        new_proc = subprocess.Popen(
            [sys.executable, "-m", "data.sources.naver_us"],
            cwd=str(_ROOT),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        st.session_state["nas_live_proc"] = new_proc
        st.session_state["nas_live_started"] = pd.Timestamp.now(tz="Asia/Seoul").isoformat(timespec="seconds")
        st.session_state["nas_live_finalized"] = False
        st.rerun()

    with st.sidebar:
        if live_running or live_proc is not None:
            try:
                log_text = _live_log.read_text(encoding="utf-8", errors="replace")
            except FileNotFoundError:
                log_text = ""
            tail = log_text.splitlines()[-8:]
        if live_running:
            st.info(
                f"⏳ 라이브 fetch 진행 중 (시작 {st.session_state.get('nas_live_started','?')})"
            )
            if tail:
                st.code("\n".join(tail))
            if st.button("🔄 상태 갱신", use_container_width=True, key="nas_live_refresh"):
                st.rerun()
        elif live_proc is not None:
            rc = live_proc.returncode
            if not st.session_state.get("nas_live_finalized"):
                st.session_state["nas_live_finalized"] = True
            if rc == 0:
                st.success("✅ 라이브 fetch 완료")
            else:
                st.error(f"❌ 라이브 fetch 실패 (rc={rc})")
            if tail:
                st.code("\n".join(tail))
            if st.button("Dismiss", use_container_width=True, key="nas_live_dismiss"):
                st.session_state["nas_live_proc"] = None
                st.session_state["nas_live_finalized"] = False
                st.rerun()

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
        col_left, col_memo = st.columns([2, 3], vertical_alignment="center")
        with col_left:
            render_chart_title(st, f"{name} · {symbol}")
            with st.container(key="stock_chart_iv_picker"):
                chart_iv = st.segmented_control(
                    "Interval",
                    options=["1d", "1w", "1M"],
                    default="1w",
                    key="nas_chart_iv",
                    label_visibility="collapsed",
                )
        with col_memo:
            render_chart_memo(st, symbol, NOTES_PATH, "nas_notes")
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

    @st.fragment
    def render_data_section() -> None:
        df = load_snapshot()
        if df is None or df.empty:
            st.info(
                "📡 라이브 스냅샷 없음 — 사이드바 `라이브 가격 갱신` 으로 먼저 받아주세요. "
                "초회 fetch는 3800종목 기준 ~2분 소요."
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

        f1, f2, f3, f4, f5 = st.columns([3, 1, 2, 2, 3])
        with f1:
            search = st.text_input("Symbol / name contains", value="", key="nas_search").strip()
        with f2:
            top_n = st.number_input(
                "Top N (0 = all)",
                min_value=0, max_value=5000, value=0, step=50,
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
            ma_interval = st.segmented_control(
                "MA Interval",
                options=MA_INTERVAL_OPTIONS,
                default=DEFAULT_MA_INTERVAL,
                key="nas_ma_interval",
                help="MA10/MA20 봉 단위. 거래소 표준 — 차트의 1d/1w/1M MA 라인과 동일.",
            )
            if not ma_interval:
                ma_interval = DEFAULT_MA_INTERVAL
        with f5:
            hl_lookback = st.segmented_control(
                "HL Lookback",
                options=HL_LOOKBACK_OPTIONS,
                default=DEFAULT_HL_LOOKBACK,
                key="nas_hl_lookback",
                help="High/Low Δ% 기간 (캘린더일). 1y = 최근 1년 최고가/최저가 대비.",
            )
            if not hl_lookback:
                hl_lookback = DEFAULT_HL_LOOKBACK

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
            df, ma_interval, hl_lookback, selected_symbol,
            symbol_col="symbolCode", symbol_header="Symbol",
            name_col="stockNameEng", name_header="Name",
            price_col="closePrice", price_format="dec",
            volume_col="accumulatedTradingVolume", volume_header="Volume",
            market_cap_col="marketValueRaw", market_cap_header="시총 (USD)",
        )
        grid_key = f"nas_grid::{top_n}::{search}::{sort_col_key}"
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

        missing_in_snapshot = set(universe) - set(df["symbolCode"].astype(str).tolist())
        with st.expander("스냅샷 메타 (디버그)"):
            st.write(sorted(df.columns.tolist()))
            if missing_in_snapshot:
                st.write(
                    f"universe에 있으나 스냅샷에 없음 ({len(missing_in_snapshot)}): ",
                    sorted(missing_in_snapshot),
                )

    render_data_section()


main()
