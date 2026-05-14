"""KOSPI tab orchestrator — Naver snapshot + stock cache compute + AgGrid + chart.

Called from ``dashboards/pages/3_Live.py`` inside ``st.tabs[1]``.

Session state keys (all prefixed ``kospi_``):
  - ``kospi_live_proc / _started / _finalized`` — live snapshot subprocess
  - ``kospi_fetch_proc / _started / _finalized`` — FDR fetch subprocess
  - ``kospi_notes``       — in-session memo dict
  - ``kospi_sel_code``    — currently selected ``itemCode``
  - ``kospi_sel_name``    — display name for the chart dialog
  - ``_kospi_chart_dialog_shown_for`` — code the dialog was last opened for

Stock-side compute lives in :mod:`dashboards._stock_grid` (shared with NASDAQ).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from data.loader import load_ohlcv
from data.sources.naver_kr import SNAPSHOT_PATH, load_snapshot
from dashboards._recommendation import compute_recommendations
from dashboards._stock_grid import (
    DEFAULT_HL_LOOKBACK,
    DEFAULT_MA_INTERVAL,
    HL_LOOKBACK_OPTIONS,
    MA_INTERVAL_OPTIONS,
    PERIODS_D,
    STOCK_PAGE_CSS,
    apply_current_prices,
    build_stock_grid_options,
    compute_reference_levels,
    load_cache_tails,
    load_notes,
    render_chart_memo,
    render_chart_title,
    render_tv_chart_stock,
    save_notes,
)
from dashboards.live._common import (
    fetched_at_caption,
    python_module_args,
    render_subprocess_launcher,
    render_subprocess_status,
    snapshot_age_caption,
)

try:
    from streamlit_lightweight_charts import renderLightweightCharts  # type: ignore # noqa: F401
    _HAS_LWC = True
except ImportError:  # pragma: no cover
    _HAS_LWC = False

from st_aggrid import AgGrid, GridUpdateMode

_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _ROOT / "data" / "cache" / "kr"
_FETCH_LOG = _CACHE_DIR / "_fetch.log"
_LIVE_LOG = _CACHE_DIR / "_live_fetch.log"
_NOTES_PATH = _CACHE_DIR / "_notes.json"

_COLUMN_LABELS: dict[str, str] = {
    "itemCode": "Code",
    "stockName": "Name",
    "closePrice": "Price",
    "fluctuationsRatio": "Change",
    "accumulatedTradingValue": "거래대금 (KRW)",
    "marketValue": "시총 (KRW)",
    "accumulatedTradingVolume": "Volume",
    **{f"pct_{n}d": f"{n}d" for n in PERIODS_D},
}
_ALL_SORT_KEYS = list(_COLUMN_LABELS.keys())
_DEFAULT_SORT = "marketValue"


def render(st: Any) -> None:
    """Render the KOSPI tab into the current Streamlit container."""
    st.markdown(STOCK_PAGE_CSS, unsafe_allow_html=True)

    # ── Top toolbar ──
    bar_caption, bar_live, bar_fetch = st.columns([4, 2, 2])
    with bar_caption:
        st.caption(snapshot_age_caption(SNAPSHOT_PATH))
    with bar_live:
        render_subprocess_launcher(
            st,
            label="라이브 가격 갱신",
            session_prefix="kospi_live",
            log_path=_LIVE_LOG,
            args=python_module_args("data.sources.naver_kr"),
            cwd=_ROOT,
            button_key="kospi_live_btn",
            button_help="Naver 비공식 페이지 endpoint로 KOSPI 전 종목 라이브 시세를 받아 머지. 백그라운드.",
        )
    with bar_fetch:
        render_subprocess_launcher(
            st,
            label="KOSPI 데이터 받기",
            session_prefix="kospi_fetch",
            log_path=_FETCH_LOG,
            args=python_module_args("data.sources.stocks", "--market", "KOSPI"),
            cwd=_ROOT,
            button_key="kospi_fetch_btn",
            button_help="FDR 로 KOSPI 전 종목 일봉을 data/cache/kr/ 로 증분 다운로드. 백그라운드.",
        )

    render_subprocess_status(
        st,
        label="라이브 fetch",
        session_prefix="kospi_live",
        log_path=_LIVE_LOG,
        success_msg="✅ 라이브 fetch 완료",
        error_msg="❌ 라이브 fetch 실패",
    )
    render_subprocess_status(
        st,
        label="KOSPI fetch",
        session_prefix="kospi_fetch",
        log_path=_FETCH_LOG,
        success_msg="✅ KOSPI fetch 완료",
        error_msg="❌ KOSPI fetch 실패",
        on_success_clear_cache=True,
    )

    # ── Cached helpers ──
    @st.cache_data(ttl=300, show_spinner=False)
    def _cached_cache_tails(code: str, n: int):
        return load_cache_tails(_CACHE_DIR / f"{code}.parquet", n)

    @st.cache_data(ttl=300, show_spinner=False)
    def _cached_reference_levels(symbols_tuple: tuple) -> pd.DataFrame:
        """Heavy parquet-read + MA/HL pass — price-independent.

        Cache key intentionally omits live prices: reference levels (prev close,
        SMA, max/min) only change when the underlying parquet does. Live-price
        refreshes hit this cache; only ``apply_current_prices`` reruns each time.
        """
        return compute_reference_levels(
            list(symbols_tuple),
            cache_loader=_cached_cache_tails,
        )

    @st.cache_data(ttl=900, show_spinner=False)
    def _cached_recommendations(symbols_tuple: tuple) -> pd.DataFrame:
        """전략 점수 (추천) — 일/주봉 마지막 봉 기준. TTL 15분."""
        _daily_cache: dict[str, Optional[pd.DataFrame]] = {}

        def _daily(sym: str):
            if sym in _daily_cache:
                return _daily_cache[sym]
            path = _CACHE_DIR / f"{sym}.parquet"
            if not path.exists():
                _daily_cache[sym] = None
                return None
            try:
                df = pd.read_parquet(path, columns=["Open", "High", "Low", "Close", "Volume"])
            except Exception:
                _daily_cache[sym] = None
                return None
            _daily_cache[sym] = df if not df.empty else None
            return _daily_cache[sym]

        def _weekly(sym: str):
            df = _daily(sym)
            if df is None:
                return None
            return df.resample("W-FRI").agg(
                {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
            ).dropna()

        return compute_recommendations("kr", list(symbols_tuple), _daily, _weekly)

    @st.cache_data(ttl=300, show_spinner=False)
    def _chart_df_cached(symbol: str, iv: str) -> pd.DataFrame:
        if iv == "1M":
            daily = load_ohlcv("kr", symbol, "1d")
            return daily.resample("ME").agg(
                {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
            ).dropna()
        return load_ohlcv("kr", symbol, iv)

    def _render_inline_chart(code: str, name: str) -> None:
        col_left, col_memo = st.columns([2, 3], vertical_alignment="center")
        with col_left:
            render_chart_title(st, f"{name} · {code}")
            with st.container(key="stock_chart_iv_picker"):
                chart_iv = st.segmented_control(
                    "Interval",
                    options=["1d", "1w", "1M"],
                    default="1w",
                    key="kospi_chart_iv",
                    label_visibility="collapsed",
                )
        with col_memo:
            render_chart_memo(st, code, _NOTES_PATH, "kospi_notes")
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

    @st.fragment
    def _render_data_section() -> None:
        df = load_snapshot()
        if df is None or df.empty:
            st.info(
                "📡 라이브 스냅샷 없음 — 위 `라이브 가격 갱신` 으로 먼저 받아주세요. "
                "KOSPI는 페이지 bulk endpoint라 ~5초면 완료."
            )
            return

        st.caption(fetched_at_caption(df))

        f1, f2, f3, f4, f5 = st.columns([3, 1, 2, 2, 3])
        with f1:
            search = st.text_input("Name / code contains", value="", key="kospi_search").strip()
        with f2:
            top_n = st.number_input(
                "Top N (0 = all)",
                min_value=0, max_value=5000, value=0, step=50,
                key="kospi_topn",
            )
        with f3:
            sort_col_key = st.selectbox(
                "Sort by",
                options=_ALL_SORT_KEYS,
                index=_ALL_SORT_KEYS.index(_DEFAULT_SORT),
                format_func=lambda k: _COLUMN_LABELS.get(k, k),
                key="kospi_sort",
            )
        with f4:
            ma_interval = st.segmented_control(
                "MA Interval",
                options=MA_INTERVAL_OPTIONS,
                default=DEFAULT_MA_INTERVAL,
                key="kospi_ma_interval",
                help="MA10/MA20 봉 단위. 거래소 표준 — 차트의 1d/1w/1M MA 라인과 동일.",
            )
            if not ma_interval:
                ma_interval = DEFAULT_MA_INTERVAL
        with f5:
            hl_lookback = st.segmented_control(
                "HL Lookback",
                options=HL_LOOKBACK_OPTIONS,
                default=DEFAULT_HL_LOOKBACK,
                key="kospi_hl_lookback",
                help="High/Low Δ% 기간 (캘린더일). 1y = 최근 1년 최고가/최저가 대비.",
            )
            if not hl_lookback:
                hl_lookback = DEFAULT_HL_LOOKBACK

        codes_all = df["itemCode"].dropna().astype(str).tolist()
        if codes_all:
            current_prices = dict(zip(codes_all, df.get("closePrice", pd.Series(dtype=float))))
            try:
                with st.spinner(f"캐시 계산 ({len(codes_all)}개, all windows)…"):
                    refs = _cached_reference_levels(tuple(codes_all))
                derived = apply_current_prices(refs, current_prices)
                if not derived.empty:
                    derived = derived.rename(columns={"symbol": "itemCode"})
                    overlap = [c for c in derived.columns
                               if c != "itemCode" and c in df.columns]
                    if overlap:
                        df = df.drop(columns=overlap)
                    df = df.merge(derived, on="itemCode", how="left")
            except Exception as e:
                st.warning(f"캐시 계산 실패: {e}")

            # ── 전략 추천 점수 ──
            try:
                with st.spinner(f"추천 계산 ({len(codes_all)}개, 4 전략)…"):
                    recs = _cached_recommendations(tuple(codes_all))
                if not recs.empty:
                    recs = recs.rename(columns={"symbol": "itemCode"})
                    overlap = [c for c in recs.columns
                               if c != "itemCode" and c in df.columns]
                    if overlap:
                        df = df.drop(columns=overlap)
                    df = df.merge(recs, on="itemCode", how="left")
            except Exception as e:
                st.warning(f"추천 계산 실패: {e}")

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

        notes = st.session_state.setdefault("kospi_notes", load_notes(_NOTES_PATH))
        df["note"] = df["itemCode"].astype(str).map(notes).fillna("")

        SEL_KEY = "kospi_sel_code"
        selected_symbol: Optional[str] = st.session_state.get(SEL_KEY)
        if selected_symbol and not (df["itemCode"] == selected_symbol).any():
            st.session_state.pop(SEL_KEY, None)
            selected_symbol = None

        df_grid, grid_options = build_stock_grid_options(
            df, ma_interval, hl_lookback, selected_symbol,
            symbol_col="itemCode", symbol_header="Code",
            name_col="stockName", name_header="Name",
            price_col="closePrice", price_header="Price", price_format="int",
            volume_col="accumulatedTradingValue", volume_header="거래대금",
            volume_format="millions",
            market_cap_col="marketValue", market_cap_header="시총",
            market_cap_format="millions",
            pct_header_suffix="",
        )
        grid_key = f"kospi_grid::v3::{top_n}::{search}::{sort_col_key}::{ma_interval}::{hl_lookback}"
        grid_resp = AgGrid(
            df_grid,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.SELECTION_CHANGED | GridUpdateMode.VALUE_CHANGED,
            allow_unsafe_jscode=True,
            fit_columns_on_grid_load=True,
            height=580,
            theme="streamlit",
            key=grid_key,
        )

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
                save_notes(_NOTES_PATH, notes)

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

    _render_data_section()
