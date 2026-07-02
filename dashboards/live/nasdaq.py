"""NASDAQ tab orchestrator — nasdaq_screener snapshot + stock cache compute + AgGrid + chart.

Called from ``dashboards/pages/3_Live.py`` inside ``st.tabs[2]``.

Session state keys (all prefixed ``nas_``):
  - ``nas_live_proc / _started / _finalized``  — live snapshot subprocess
  - ``nas_fetch_proc / _started / _finalized`` — FDR fetch subprocess
  - ``nas_notes``        — in-session memo dict
  - ``nas_sel_symbol``   — currently selected symbol
  - ``nas_sel_name``     — display name for the chart dialog
  - ``_nas_chart_dialog_shown_for`` — symbol the dialog was last opened for

Stock-side compute lives in :mod:`dashboards._stock_grid` (shared with KOSPI).
The universe (count for the toolbar) is discovered from the local 1D parquet
cache directory rather than the screener API.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pandas as pd

from data.loader import load_ohlcv
from data.sources.nasdaq_screener import discover_universe, load_snapshot
from dashboards._precompute import load_recs, load_refs
from dashboards._stock_grid import (
    PERIODS_D,
    STOCK_PAGE_CSS,
    ChartNavigator,
    apply_current_prices,
    apply_top_by_rank,
    breadth_counts,
    build_stock_grid_options,
    fmt_compact_count,
    fmt_compact_usd,
    load_notes,
    load_stars,
    render_breadth,
    render_chart_memo,
    render_chart_meta_line,
    render_chart_star,
    render_chart_title,
    render_top_by_select,
    render_top_n_input,
    render_tv_chart,
    safe_fragment_rerun,
    save_notes,
)
from dashboards.live._common import fetched_at_caption

try:
    from streamlit_lightweight_charts import renderLightweightCharts  # type: ignore # noqa: F401
    _HAS_LWC = True
except ImportError:  # pragma: no cover
    _HAS_LWC = False

from st_aggrid import AgGrid, DataReturnMode, GridUpdateMode

_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _ROOT / "data" / "cache" / "us"
_NOTES_PATH = _CACHE_DIR / "_notes.json"
_STARS_PATH = _CACHE_DIR / "_stars.json"
_REPORTS_DIR = _ROOT / "research" / "reports"


def _latest_report_path(code: str) -> Optional[Path]:
    """Return most recent ``research/reports/{code}/{code}_YYYYMMDD.md`` or None."""
    if not _REPORTS_DIR.exists():
        return None
    matches = sorted((_REPORTS_DIR / code).glob(f"{code}_*.md")) if (_REPORTS_DIR / code).exists() else []
    return matches[-1] if matches else None


_COLUMN_LABELS: dict[str, str] = {
    "symbolCode": "Symbol",
    "stockNameEng": "Name",
    "closePrice": "Last",
    "fluctuationsRatio": "Change %",
    "dollarVolume": "거래대금 (USD)",
    "marketValueRaw": "시총 (USD)",
    "accumulatedTradingVolume": "Volume (shares)",
    **{f"pct_{n}d": f"{n}d %" for n in PERIODS_D},
}

# Top by 드롭다운 옵션 — 스냅샷 원본 컬럼 + enrichment(refs·recs merge) 후에 붙는
# 파생 컬럼. dollarVolume 은 원래 sort 뒤에서 계산됐지만, 이 옵션에 포함되니
# render 흐름에서 sort 앞으로 이동시켰다.
_TOP_BY_LABELS: dict[str, str] = {
    "dollarVolume": "거래대금",
    "marketValueRaw": "시총",
    "pct_1d": "1일전",
    "pct_7d": "7일전",
    "pct_30d": "30일전",
    "pct_ma10__1d": "D10",
    "pct_ma20__1d": "D20",
    "pct_ma10__1w": "W10",
    "pct_ma20__1w": "W20",
    "pct_ma10__1M": "M10",
    "pct_ma20__1M": "M20",
    "g1": "G1",
    "g2": "G2",
    "gate_pass": "G3",
    "g4": "G4",
}
_ALL_SORT_KEYS = list(_TOP_BY_LABELS.keys())
_DEFAULT_SORT = "marketValueRaw"


def render(st: Any) -> None:
    """Render the NASDAQ tab into the current Streamlit container.

    Data-fetch / precompute is driven by the master "모든 데이터 받기"
    button on the parent page (``dashboards/pages/3_Live.py``).
    """
    st.markdown(STOCK_PAGE_CSS, unsafe_allow_html=True)

    universe = discover_universe()
    if not universe:
        st.warning(
            "`data/cache/us/` 가 비어 있습니다. 페이지 상단 `모든 데이터 받기` 로 NASDAQ 일봉을 먼저 받아주세요."
        )
        return

    # ── Chart cache only — refs/recs are disk-precomputed via dashboards._precompute ──
    @st.cache_data(ttl=300, show_spinner=False)
    def _chart_df_cached(symbol: str, iv: str) -> pd.DataFrame:
        if iv == "1M":
            daily = load_ohlcv("us", symbol, "1d")
            return daily.resample("ME").agg(
                {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
            ).dropna()
        return load_ohlcv("us", symbol, iv)

    _nav = ChartNavigator(
        st,
        codes_key="nas_nav_codes", names_key="nas_nav_names",
        sel_key="nas_sel_symbol", name_key="nas_sel_name",
        shown_key="_nas_chart_dialog_shown_for", btn_prefix="nas_chart_nav",
    )

    def _render_inline_chart(symbol: str, name: str) -> None:
        # Single compact header row: search + ‹ 번호 › + memo + ★ aligned to the
        # TOP line (meta + interval picker stack below inside c_title only).
        c_title, c_prev, c_pos, c_next, c_memo, c_star = st.columns(
            [3, 0.7, 1.5, 0.7, 3.4, 0.6], vertical_alignment="top",
        )
        with c_title:
            _nav.search_box(placeholder="종목명 검색")
            meta = st.session_state.get("nas_nav_meta", {}).get(symbol, {})
            render_chart_meta_line(st, [
                ("시총", fmt_compact_usd(meta.get("mcap"))),
                ("거래량", fmt_compact_count(meta.get("vol"))),
            ])
            with st.container(key="stock_chart_iv_picker"):
                _iv_col, _vp_col = st.columns([3, 1], gap="small",
                                              vertical_alignment="center")
                with _iv_col:
                    chart_iv = st.segmented_control(
                        "Interval",
                        options=["1d", "1w", "1M"],
                        default="1w",
                        key="nas_chart_iv",
                        label_visibility="collapsed",
                        help="Ctrl + ←/→ 로도 전환 (←/→ 는 종목 이동)",
                    )
                with _vp_col:
                    vp_on = st.checkbox(
                        "매물대", value=False, key="nas_vp_on",
                        help="Volume Profile — 가격대별 누적 거래량을 우측 수평 바로 표시",
                    )
        with c_prev:
            _nav.button_prev()
        with c_pos:
            _nav.position_input()
        with c_next:
            _nav.button_next()
        with c_memo:
            render_chart_memo(st, symbol, _NOTES_PATH, "nas_notes")
        with c_star:
            render_chart_star(st, symbol, _STARS_PATH, "nas_stars")
        _nav.inject_keys()
        if not chart_iv:
            chart_iv = "1w"

        tab_chart, tab_report = st.tabs(["Chart", "Report"])

        with tab_chart:
            try:
                cdf = _chart_df_cached(symbol, chart_iv)
            except FileNotFoundError:
                st.warning(f"`{symbol}` 캐시 없음 — `NASDAQ 데이터 받기` 로 먼저 받아주세요.")
            except Exception as e:  # noqa: BLE001
                st.warning(f"{symbol} 캐시 로드 실패: {e}")
            else:
                if cdf is None or len(cdf) == 0:
                    st.warning(f"{symbol} 데이터 비어있음")
                elif not _HAS_LWC:
                    st.warning(
                        "`streamlit-lightweight-charts` 미설치 — "
                        "`.venv/Scripts/python.exe -m pip install streamlit-lightweight-charts`"
                    )
                else:
                    render_tv_chart(
                        symbol, f"{name} · {symbol}", chart_iv, cdf, key_prefix="lwc_nasdaq",
                        vp_on=bool(vp_on),
                    )

        with tab_report:
            report_path = _latest_report_path(symbol)
            if report_path is None:
                st.info(
                    f"📄 `{symbol}` 리포트가 아직 없습니다. "
                    f'Claude 에게 "**{symbol} 리포트**" 라고 요청하면 한-페이지 정성 리포트를 생성합니다. '
                    f"(저장 경로: `research/reports/{symbol}/{symbol}_YYYYMMDD.md`)"
                )
            else:
                mt = pd.Timestamp.fromtimestamp(report_path.stat().st_mtime, tz="Asia/Seoul")
                st.caption(f"📄 {report_path.name} · {mt.strftime('%Y-%m-%d %H:%M')}")
                try:
                    md = report_path.read_text(encoding="utf-8")
                except Exception as e:  # noqa: BLE001
                    st.warning(f"리포트 로드 실패: {e}")
                else:
                    with st.container(height=600, border=False):
                        st.markdown(md, unsafe_allow_html=False)

    @st.dialog(" ", width="large")
    def _chart_dialog() -> None:
        sym = st.session_state.get("nas_sel_symbol")
        if not sym:
            return
        name = st.session_state.get("nas_sel_name") or sym
        _render_inline_chart(sym, name)

    @st.fragment
    def _render_data_section() -> None:
        df = load_snapshot()
        if df is None or df.empty:
            st.info(
                "📡 라이브 스냅샷 없음 — 위 `라이브 가격 갱신` 으로 먼저 받아주세요 (~2초)."
            )
            return

        st.caption(fetched_at_caption(df))

        full_breadth = breadth_counts(df.get("fluctuationsRatio"))

        stars = st.session_state.setdefault("nas_stars", load_stars(_STARS_PATH))

        f1, f2, f3 = st.columns([3, 1, 2])
        with f1:
            search = st.text_input("Symbol / name contains", value="", key="nas_search").strip()
        with f2:
            render_top_n_input(
                st,
                canonical_key="_nas_top_n_val",
                widget_key="nas_topn_toolbar",
                max_value=5000, step=50,
            )
        with f3:
            render_top_by_select(
                st,
                canonical_key="_nas_top_by_val",
                widget_key="nas_sort_toolbar",
                options=_ALL_SORT_KEYS, labels=_TOP_BY_LABELS,
                default=_DEFAULT_SORT,
                help_text="Top N 을 뽑을 기준 컬럼. 차트 ← → 순번도 이 기준을 따름 "
                          "(그리드 헤더 클릭으로 재정렬해도 차트 번호는 유지).",
            )

        # canonical 세션 값을 읽어 필터 로직에 사용 (bitget/kospi 동일 패턴).
        top_n = int(st.session_state.get("_nas_top_n_val", 0))
        sort_col_key = str(st.session_state.get("_nas_top_by_val", _DEFAULT_SORT))

        symbols_all = df["symbolCode"].dropna().astype(str).tolist()
        if symbols_all:
            current_prices = dict(zip(symbols_all, df.get("closePrice", pd.Series(dtype=float))))

            # ── Reference levels (precomputed on disk) ──
            refs = load_refs("us")
            if refs is None or refs.empty:
                st.warning("⚠️ 지표 미계산 — `NASDAQ 데이터 받기` 버튼을 누르면 fetch 후 자동 계산됩니다.")
            else:
                try:
                    derived = apply_current_prices(refs, current_prices)
                    if not derived.empty:
                        derived = derived.rename(columns={"symbol": "symbolCode"})
                        overlap = [c for c in derived.columns
                                   if c != "symbolCode" and c in df.columns]
                        if overlap:
                            df = df.drop(columns=overlap)
                        df = df.merge(derived, on="symbolCode", how="left")
                except Exception as e:
                    st.warning(f"지표 머지 실패: {e}")

            # ── 전략 추천 점수 (precomputed on disk) ──
            recs = load_recs("us")
            if recs is not None and not recs.empty:
                try:
                    recs_use = recs.drop(columns=["data_mtime"], errors="ignore")
                    recs_use = recs_use.rename(columns={"symbol": "symbolCode"})
                    overlap = [c for c in recs_use.columns
                               if c != "symbolCode" and c in df.columns]
                    if overlap:
                        df = df.drop(columns=overlap)
                    df = df.merge(recs_use, on="symbolCode", how="left")
                except Exception as e:
                    st.warning(f"추천 머지 실패: {e}")

        if search:
            mask = (
                df["symbolCode"].astype(str).str.contains(search, case=False, na=False)
                | df["stockNameEng"].astype(str).str.contains(search, case=False, na=False)
                | df["stockName"].astype(str).str.contains(search, case=False, na=False)
            )
            df = df[mask]
        # 거래대금 (USD) 파생 — 스냅샷은 주식 수량(Volume) 만 주므로 close × shares.
        # Top by 로 "거래대금" 을 뽑을 수 있도록, 또 아래 그리드 표시 정렬에서도
        # 쓰이므로 sort 이전에 계산.
        if "accumulatedTradingVolume" in df.columns and "closePrice" in df.columns:
            df = df.assign(
                dollarVolume=df["accumulatedTradingVolume"] * df["closePrice"],
            )
        # Top by 로 순위 매기고 head(top_n) — 이 순서가 차트 ← → 번호 기준.
        # MA-gap 컬럼은 |값| 오름차순(=MA 가까운 순), 나머지는 내림차순.
        df = apply_top_by_rank(df, sort_col_key, top_n)

        if df.empty:
            render_breadth(st, full=full_breadth)
            st.info("필터 조건에 맞는 종목이 없습니다.")
            return

        render_breadth(st, full=full_breadth,
                       shown=breadth_counts(df.get("fluctuationsRatio")))

        notes = st.session_state.setdefault("nas_notes", load_notes(_NOTES_PATH))

        # Display order drives ←/→ chart navigation (follows filter/sort).
        nav_codes = df["symbolCode"].astype(str).tolist()
        st.session_state["nas_nav_codes"] = nav_codes
        st.session_state["nas_nav_names"] = dict(
            zip(nav_codes, df["stockNameEng"].astype(str))
        )
        # 시총(USD)/거래량(주식수) — 차트 헤더 메타 라인용.
        st.session_state["nas_nav_meta"] = {
            str(r["symbolCode"]): {
                "mcap": r.get("marketValueRaw"),
                "vol": r.get("accumulatedTradingVolume"),
            }
            for _, r in df.iterrows()
        }

        SEL_KEY = "nas_sel_symbol"
        selected_symbol: Optional[str] = st.session_state.get(SEL_KEY)
        if selected_symbol and not (df["symbolCode"] == selected_symbol).any():
            st.session_state.pop(SEL_KEY, None)
            selected_symbol = None

        # 그리드 표시 순서는 항상 거래대금 내림차순 — Top by 는 Top N 컷 + 차트 번호
        # 부여 용도로만. (nav_codes 는 위에서 Top by 순서로 이미 저장.)
        if "dollarVolume" in df.columns:
            df = df.sort_values("dollarVolume", ascending=False,
                                na_position="last").reset_index(drop=True)

        df_grid, grid_options = build_stock_grid_options(
            df, selected_symbol,
            symbol_col="symbolCode", symbol_header="Symbol",
            name_col="stockNameEng", name_header="Name",
            price_col="closePrice", price_format="dec",
            volume_col="dollarVolume", volume_header="거래대금",
            volume_format="usd",
            market_cap_col="marketValueRaw", market_cap_header="시총",
            market_cap_format="usd",
            star_codes=stars,
        )
        grid_key = f"nas_grid::v8::{top_n}::{search}::{sort_col_key}::{len(stars)}"
        grid_resp = AgGrid(
            df_grid,
            gridOptions=grid_options,
            update_mode=(GridUpdateMode.SELECTION_CHANGED | GridUpdateMode.VALUE_CHANGED
                         | GridUpdateMode.SORTING_CHANGED | GridUpdateMode.FILTERING_CHANGED),
            data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
            allow_unsafe_jscode=True,
            fit_columns_on_grid_load=False,  # flex 레이아웃이 폭을 자동 분배
            height=580,
            theme="streamlit",
            key=grid_key,
        )

        # 차트 ← → 순번은 Top by 기준 고정 — 그리드 헤더 클릭 정렬은 표시 순서만
        # 바꾸고 ``nas_nav_codes`` 는 서버-사이드 sort 순서 그대로 유지한다.

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
        # Grid is authoritative only when *it* reports a changed selection —
        # see kospi.py for why comparing against the session symbol would
        # fight the ←/→ navigator (grid isn't re-mounted on arrow nav).
        prev_grid_sel = st.session_state.get("_nas_grid_prev_sel")
        st.session_state["_nas_grid_prev_sel"] = new_sel
        if new_sel != prev_grid_sel:
            if new_sel:
                st.session_state[SEL_KEY] = new_sel
                st.session_state["nas_sel_name"] = new_name or new_sel
            else:
                st.session_state.pop(SEL_KEY, None)
                st.session_state.pop("nas_sel_name", None)
            safe_fragment_rerun(st)

        cur_sel = st.session_state.get(SEL_KEY)
        last_shown = st.session_state.get("_nas_chart_dialog_shown_for")
        if cur_sel and cur_sel != last_shown:
            st.session_state["_nas_chart_dialog_shown_for"] = cur_sel
            _chart_dialog()
        elif not cur_sel and last_shown is not None:
            st.session_state.pop("_nas_chart_dialog_shown_for", None)

    _render_data_section()
