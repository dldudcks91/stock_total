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
    breadth_counts,
    build_stock_grid_options,
    fmt_compact_krw,
    load_notes,
    load_stars,
    render_chart_memo,
    render_drawing_controls,
    render_chart_meta_line,
    render_chart_star,
    render_chart_title,
    render_breadth,
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

from st_aggrid import AgGrid, GridUpdateMode

_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _ROOT / "data" / "cache" / "kr"
_NOTES_PATH = _CACHE_DIR / "_notes.json"
_STARS_PATH = _CACHE_DIR / "_stars.json"
_DRAWINGS_PATH = _CACHE_DIR / "_drawings.json"
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
_ALL_SORT_KEYS = list(_COLUMN_LABELS.keys())
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
        # Search box replaces the plain title text (name only).
        # ``vertical_alignment="center"`` puts ‹/›/memo/★ at the vertical
        # midpoint of the c_title stack.
        c_title, c_prev, c_pos, c_next, c_memo, c_star = st.columns(
            [3, 0.8, 2.0, 0.8, 4.1, 0.7], vertical_alignment="center",
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
                    fib_n, trendlines = render_drawing_controls(
                        st, code=code, dates=cdf.index,
                        last_close=float(cdf["Close"].iloc[-1]),
                        drawings_path=_DRAWINGS_PATH, session_key="kospi_drawings",
                    )
                    render_tv_chart(
                        code, f"{name} · {code}", chart_iv, cdf, key_prefix="lwc_kospi",
                        fib_n=fib_n, trendlines=trendlines,
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

        f1, f2, f3, f4 = st.columns([3, 1, 2, 1.2])
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
            star_only = st.checkbox(
                f"⭐ 별표만 ({len(stars)})", value=False, key="kospi_star_only",
            )

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

        if star_only:
            df = df[df["itemCode"].astype(str).isin(stars)]
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
            render_breadth(st, full=full_breadth)
            st.info("⭐ 별표한 종목이 없습니다." if star_only
                    else "필터 조건에 맞는 종목이 없습니다.")
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
        grid_key = f"kospi_grid::v8::{top_n}::{search}::{sort_col_key}::{star_only}::{len(stars)}"
        grid_resp = AgGrid(
            df_grid,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.SELECTION_CHANGED | GridUpdateMode.VALUE_CHANGED,
            allow_unsafe_jscode=True,
            fit_columns_on_grid_load=False,  # flex 레이아웃이 폭을 자동 분배
            height=580,
            theme="streamlit",
            key=grid_key,
        )

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
