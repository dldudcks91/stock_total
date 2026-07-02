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

from pathlib import Path
from typing import Any, Optional

import pandas as pd

from data.loader import load_ohlcv
from data.sources.naver_kr import load_snapshot
from dashboards._precompute import load_recs, load_refs
from dashboards._stock_grid import (
    PERIODS_D,
    STOCK_PAGE_CSS,
    ChartNavigator,
    apply_current_prices,
    apply_top_by_rank,
    breadth_counts,
    build_stock_grid_options,
    fmt_compact_krw,
    load_notes,
    load_stars,
    render_chart_memo,
    render_chart_meta_line,
    render_chart_star,
    render_chart_title,
    render_breadth,
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
_CACHE_DIR = _ROOT / "data" / "cache" / "kr"
_NOTES_PATH = _CACHE_DIR / "_notes.json"
_STARS_PATH = _CACHE_DIR / "_stars.json"
_LISTING_CSV = _CACHE_DIR / "_listing.csv"
_REPORTS_DIR = _ROOT / "research" / "reports"


def _latest_report_path(code: str) -> Optional[Path]:
    """Return most recent ``research/reports/{code}/{code}_YYYYMMDD.md`` or None."""
    if not _REPORTS_DIR.exists():
        return None
    matches = sorted((_REPORTS_DIR / code).glob(f"{code}_*.md")) if (_REPORTS_DIR / code).exists() else []
    return matches[-1] if matches else None


def _load_stock_whitelist() -> Optional[set]:
    """Return KOSPI common/preferred stock codes from ``_listing.csv``.

    Why: Naver's ``marketValue/KOSPI`` endpoint returns *every* instrument
    listed on the KOSPI exchange (~2400 rows) — including ETFs, ETNs, and
    REITs. The dashboard is for picking stocks, so non-stock instruments are
    just noise. ``_listing.csv`` is written by ``data.sources.stocks`` using
    ``FinanceDataReader.StockListing('KOSPI')``, which only returns common
    and preferred stocks (~948 rows) — naturally excluding ETF/ETN/REIT.

    Returns None if the listing is missing — caller should fall back to no
    filter (better to show extras than show nothing).
    """
    if not _LISTING_CSV.exists():
        return None
    try:
        df = pd.read_csv(_LISTING_CSV, dtype={"Symbol": str}, usecols=["Symbol"])
    except Exception:
        return None
    return set(df["Symbol"].dropna().astype(str))


# KRW→USD 고정 환산율. 실제 환율(≈1,300) 과 차이가 있지만 자산 간 대략 크기 비교용.
# 실시간 환율 fetcher 미탑재 — 필요해지면 별도 파이프라인으로 분리.
_USD_KRW = 1500.0

_COLUMN_LABELS: dict[str, str] = {
    "itemCode": "Symbol",
    "stockName": "Name",
    "closePrice": "Price",
    "fluctuationsRatio": "Change",
    "accumulatedTradingValue": "거래대금 (USD @₩1500)",
    "marketValue": "시총 (USD @₩1500)",
    "accumulatedTradingVolume": "Volume",
    **{f"pct_{n}d": f"{n}d" for n in PERIODS_D},
}

# Top by 드롭다운 옵션 — 스냅샷 원본 컬럼 + enrichment(refs·recs merge) 후에 붙는
# 파생 컬럼. render 흐름이 이미 enrich → sort 순서라 그대로 참조 가능.
_TOP_BY_LABELS: dict[str, str] = {
    "accumulatedTradingValue": "거래대금",
    "marketValue": "시총",
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
_DEFAULT_SORT = "marketValue"


def render(st: Any) -> None:
    """Render the KOSPI tab into the current Streamlit container.

    Data-fetch / precompute is now driven by the master "모든 데이터 받기"
    button on the parent page (``dashboards/pages/3_Live.py``). This tab is
    read-only from that pipeline's outputs (snapshot + refs/recs parquet).
    """
    st.markdown(STOCK_PAGE_CSS, unsafe_allow_html=True)

    # ── Chart cache only — refs/recs are disk-precomputed via dashboards._precompute ──
    @st.cache_data(ttl=300, show_spinner=False)
    def _chart_df_cached(symbol: str, iv: str) -> pd.DataFrame:
        if iv == "1M":
            daily = load_ohlcv("kr", symbol, "1d")
            return daily.resample("ME").agg(
                {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
            ).dropna()
        return load_ohlcv("kr", symbol, iv)

    _nav = ChartNavigator(
        st,
        codes_key="kospi_nav_codes", names_key="kospi_nav_names",
        sel_key="kospi_sel_code", name_key="kospi_sel_name",
        shown_key="_kospi_chart_dialog_shown_for", btn_prefix="kospi_chart_nav",
    )

    def _render_inline_chart(code: str, name: str) -> None:
        # Single compact header row: search + ‹ 번호 › + memo + ★ aligned to the
        # TOP line (meta stacks below inside c_title only).
        c_title, c_prev, c_pos, c_next, c_memo, c_star = st.columns(
            [3, 0.7, 1.5, 0.7, 3.4, 0.6], vertical_alignment="top",
        )
        with c_title:
            _nav.search_box(placeholder="종목명 검색")
            meta = st.session_state.get("kospi_nav_meta", {}).get(code, {})
            render_chart_meta_line(st, [
                ("시총", fmt_compact_krw(meta.get("mcap"))),
                ("거래대금", fmt_compact_krw(meta.get("vol"))),
            ])
        with c_prev:
            _nav.button_prev()
        with c_pos:
            _nav.position_input()
        with c_next:
            _nav.button_next()
        with c_memo:
            render_chart_memo(st, code, _NOTES_PATH, "kospi_notes")
        with c_star:
            render_chart_star(st, code, _STARS_PATH, "kospi_stars")
        _nav.inject_keys()

        tab_chart, tab_report = st.tabs(["Chart", "Report"])

        with tab_chart:
            with st.container(key="stock_chart_iv_picker"):
                _iv_col, _vp_col = st.columns([3, 1], gap="small",
                                              vertical_alignment="center")
                with _iv_col:
                    chart_iv = st.segmented_control(
                        "Interval",
                        options=["1d", "1w", "1M"],
                        default="1w",
                        key="kospi_chart_iv",
                        label_visibility="collapsed",
                        help="Ctrl + ←/→ 로도 전환 (←/→ 는 종목 이동)",
                    )
                with _vp_col:
                    vp_on = st.checkbox(
                        "매물대", value=False, key="kospi_vp_on",
                        help="Volume Profile — 가격대별 누적 거래량을 우측 수평 바로 표시",
                    )
            if not chart_iv:
                chart_iv = "1w"
            try:
                cdf = _chart_df_cached(code, chart_iv)
            except FileNotFoundError:
                st.warning(f"`{code}` 캐시 없음 — `KOSPI 데이터 받기` 로 먼저 받아주세요.")
            except Exception as e:  # noqa: BLE001
                st.warning(f"{code} 캐시 로드 실패: {e}")
            else:
                if cdf is None or len(cdf) == 0:
                    st.warning(f"{code} 데이터 비어있음")
                elif not _HAS_LWC:
                    st.warning(
                        "`streamlit-lightweight-charts` 미설치 — "
                        "`.venv/Scripts/python.exe -m pip install streamlit-lightweight-charts`"
                    )
                else:
                    render_tv_chart(
                        code, f"{name} · {code}", chart_iv, cdf, key_prefix="lwc_kospi",
                        vp_on=bool(vp_on),
                    )

        with tab_report:
            report_path = _latest_report_path(code)
            if report_path is None:
                st.info(
                    f"📄 `{code}` 리포트가 아직 없습니다. "
                    f'Claude 에게 "**{code} 리포트**" 라고 요청하면 한-페이지 정성 리포트를 생성합니다. '
                    f"(저장 경로: `research/reports/{code}/{code}_YYYYMMDD.md`)"
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

        # Drop non-stock instruments (ETF / ETN / REIT) using FDR KOSPI listing.
        whitelist = _load_stock_whitelist()
        if whitelist is not None:
            df = df[df["itemCode"].astype(str).isin(whitelist)].reset_index(drop=True)

        st.caption(fetched_at_caption(df))

        full_breadth = breadth_counts(df.get("fluctuationsRatio"))

        stars = st.session_state.setdefault("kospi_stars", load_stars(_STARS_PATH))

        f1, f2, f3 = st.columns([3, 1, 2])
        with f1:
            search = st.text_input("Name / code contains", value="", key="kospi_search").strip()
        with f2:
            render_top_n_input(
                st,
                canonical_key="_kospi_top_n_val",
                widget_key="kospi_topn_toolbar",
                max_value=5000, step=50,
            )
        with f3:
            render_top_by_select(
                st,
                canonical_key="_kospi_top_by_val",
                widget_key="kospi_sort_toolbar",
                options=_ALL_SORT_KEYS, labels=_TOP_BY_LABELS,
                default=_DEFAULT_SORT,
                help_text="Top N 을 뽑을 기준 컬럼. 차트 ← → 순번도 이 기준을 따름 "
                          "(그리드 헤더 클릭으로 재정렬해도 차트 번호는 유지).",
            )

        # canonical 세션 값을 읽어 필터 로직에 사용 — toolbar 와 차트 다이얼로그가
        # 같은 값을 공유하기 위함 (bitget.py 동일 패턴 참고).
        top_n = int(st.session_state.get("_kospi_top_n_val", 0))
        sort_col_key = str(st.session_state.get("_kospi_top_by_val", _DEFAULT_SORT))

        # AgGrid(iframe custom component)는 @st.fragment 의 부분 rerun 에서 key 가
        # 바뀌어도 새 데이터로 re-mount 되지 않는다(표가 그대로 남음). 필터/정렬/TopN
        # 위젯이 바뀌면 시그니처 비교로 감지해 전체 rerun 으로 승격, 표를 갱신한다.
        _filter_sig = (search, int(top_n), sort_col_key)
        if "_kospi_filter_sig" not in st.session_state:
            st.session_state["_kospi_filter_sig"] = _filter_sig
        elif st.session_state["_kospi_filter_sig"] != _filter_sig:
            st.session_state["_kospi_filter_sig"] = _filter_sig
            st.rerun()

        codes_all = df["itemCode"].dropna().astype(str).tolist()
        if codes_all:
            current_prices = dict(zip(codes_all, df.get("closePrice", pd.Series(dtype=float))))

            # ── Reference levels (precomputed on disk) ──
            refs = load_refs("kr")
            if refs is None or refs.empty:
                st.warning("⚠️ 지표 미계산 — `KOSPI 데이터 받기` 버튼을 누르면 fetch 후 자동 계산됩니다.")
            else:
                try:
                    derived = apply_current_prices(refs, current_prices)
                    if not derived.empty:
                        derived = derived.rename(columns={"symbol": "itemCode"})
                        overlap = [c for c in derived.columns
                                   if c != "itemCode" and c in df.columns]
                        if overlap:
                            df = df.drop(columns=overlap)
                        df = df.merge(derived, on="itemCode", how="left")
                except Exception as e:
                    st.warning(f"지표 머지 실패: {e}")

            # ── 전략 추천 점수 (precomputed on disk) ──
            recs = load_recs("kr")
            if recs is not None and not recs.empty:
                try:
                    recs_use = recs.drop(columns=["data_mtime"], errors="ignore")
                    recs_use = recs_use.rename(columns={"symbol": "itemCode"})
                    overlap = [c for c in recs_use.columns
                               if c != "itemCode" and c in df.columns]
                    if overlap:
                        df = df.drop(columns=overlap)
                    df = df.merge(recs_use, on="itemCode", how="left")
                except Exception as e:
                    st.warning(f"추천 머지 실패: {e}")

        if search:
            mask = (
                df["stockName"].astype(str).str.contains(search, case=False, na=False)
                | df["itemCode"].astype(str).str.contains(search, case=False, na=False)
            )
            df = df[mask]
        # Top by 로 순위 매기고 head(top_n) — 이 순서가 차트 ← → 번호 기준.
        # MA-gap 컬럼은 |값| 오름차순(=MA 가까운 순), 나머지는 내림차순.
        df = apply_top_by_rank(df, sort_col_key, top_n)

        if df.empty:
            render_breadth(st, full=full_breadth)
            st.info("필터 조건에 맞는 종목이 없습니다.")
            return

        render_breadth(st, full=full_breadth,
                       shown=breadth_counts(df.get("fluctuationsRatio")))

        notes = st.session_state.setdefault("kospi_notes", load_notes(_NOTES_PATH))

        # Display order drives ←/→ chart navigation (follows filter/sort).
        nav_codes = df["itemCode"].astype(str).tolist()
        st.session_state["kospi_nav_codes"] = nav_codes
        st.session_state["kospi_nav_names"] = dict(
            zip(nav_codes, df["stockName"].astype(str))
        )
        # 시총/거래대금 — 차트 헤더 메타 라인용 (code → {mcap, vol}).
        st.session_state["kospi_nav_meta"] = {
            str(r["itemCode"]): {
                "mcap": r.get("marketValue"),
                "vol": r.get("accumulatedTradingValue"),
            }
            for _, r in df.iterrows()
        }

        SEL_KEY = "kospi_sel_code"
        selected_symbol: Optional[str] = st.session_state.get(SEL_KEY)
        if selected_symbol and not (df["itemCode"] == selected_symbol).any():
            st.session_state.pop(SEL_KEY, None)
            selected_symbol = None

        # KRW → USD 환산 (자산 간 크기 비교용). 차트 헤더 메타 라인은 위에서
        # 이미 nav_meta 에 KRW 원본을 담아 fmt_compact_krw 로 렌더링 중이라
        # 그대로 두고, 그리드 컬럼만 USD 로 나눔.
        df = df.assign(
            marketValue=df["marketValue"] / _USD_KRW,
            accumulatedTradingValue=df["accumulatedTradingValue"] / _USD_KRW,
        )

        # 그리드 표시 순서는 항상 거래대금 내림차순 — Top by 는 Top N 컷 + 차트 번호
        # 부여 용도로만. (nav_codes 는 위에서 Top by 순서로 이미 저장.)
        if "accumulatedTradingValue" in df.columns:
            df = df.sort_values("accumulatedTradingValue", ascending=False,
                                na_position="last").reset_index(drop=True)

        df_grid, grid_options = build_stock_grid_options(
            df, selected_symbol,
            symbol_col="itemCode", symbol_header="Symbol",
            name_col="stockName", name_header="Name",
            price_col="closePrice", price_header="Price", price_format="int",
            volume_col="accumulatedTradingValue", volume_header="거래대금",
            volume_format="usd",
            market_cap_col="marketValue", market_cap_header="시총",
            market_cap_format="usd",
            star_codes=stars,
        )
        grid_key = f"kospi_grid::v8::{top_n}::{search}::{sort_col_key}::{len(stars)}"
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
        # 바꾸고 ``kospi_nav_codes`` 는 서버-사이드 sort 순서 그대로 유지한다.

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
        # Treat the grid as authoritative only when *it* reports a different
        # selection than last time. Comparing against ``selected_symbol``
        # (session) instead would fight the ←/→ navigator: arrow nav changes
        # the session symbol but not the grid (it isn't re-mounted), so the
        # grid keeps reporting the originally clicked row — which would then
        # be mistaken for a fresh click and revert the navigation.
        prev_grid_sel = st.session_state.get("_kospi_grid_prev_sel")
        st.session_state["_kospi_grid_prev_sel"] = new_sel
        if new_sel != prev_grid_sel:
            if new_sel:
                st.session_state[SEL_KEY] = new_sel
                st.session_state["kospi_sel_name"] = new_name or new_sel
            else:
                st.session_state.pop(SEL_KEY, None)
                st.session_state.pop("kospi_sel_name", None)
            safe_fragment_rerun(st)

        cur_sel = st.session_state.get(SEL_KEY)
        last_shown = st.session_state.get("_kospi_chart_dialog_shown_for")
        if cur_sel and cur_sel != last_shown:
            st.session_state["_kospi_chart_dialog_shown_for"] = cur_sel
            _chart_dialog()
        elif not cur_sel and last_shown is not None:
            st.session_state.pop("_kospi_chart_dialog_shown_for", None)

    _render_data_section()
