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

import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from data.loader import load_ohlcv
from data.sources.nasdaq_screener import SNAPSHOT_PATH, discover_universe, load_snapshot
from dashboards._precompute import load_recs, load_refs, precompute_status
from dashboards._stock_grid import (
    PERIODS_D,
    STOCK_PAGE_CSS,
    ChartNavigator,
    apply_current_prices,
    build_stock_grid_options,
    fmt_compact_count,
    fmt_compact_usd,
    load_notes,
    load_stars,
    render_chart_memo,
    render_chart_meta_line,
    render_chart_star,
    render_chart_title,
    render_tv_chart_stock,
    safe_fragment_rerun,
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
_CACHE_DIR = _ROOT / "data" / "cache" / "us"
_FETCH_LOG = _CACHE_DIR / "_fetch.log"
_LIVE_LOG = _CACHE_DIR / "_live_fetch.log"
_PRE_LOG = _CACHE_DIR / "_precompute.log"
_NOTES_PATH = _CACHE_DIR / "_notes.json"
_STARS_PATH = _CACHE_DIR / "_stars.json"
_REPORTS_DIR = _ROOT / "research" / "reports"


def _latest_report_path(code: str) -> Optional[Path]:
    """Return most recent ``research/reports/{code}_YYYYMMDD.md`` or None."""
    if not _REPORTS_DIR.exists():
        return None
    matches = sorted(_REPORTS_DIR.glob(f"{code}_*.md"))
    return matches[-1] if matches else None


def _precompute_caption(asset: str) -> str:
    """'📊 지표 12:34 · 5m ago · 3849종목' for the toolbar caption."""
    info = precompute_status(asset)
    mt = info.get("refs_mtime")
    if mt is None:
        return "📊 지표 미계산 — `NASDAQ 데이터 받기` 시 자동 계산"
    ts = pd.Timestamp.fromtimestamp(mt, tz="Asia/Seoul")
    ago = pd.Timestamp.now(tz="Asia/Seoul") - ts
    secs = int(ago.total_seconds())
    if secs < 60:
        ago_s = f"{secs}s"
    elif secs < 3600:
        ago_s = f"{secs // 60}m"
    elif secs < 86400:
        ago_s = f"{secs // 3600}h"
    else:
        ago_s = f"{secs // 86400}d"
    return f"📊 지표 {ts.strftime('%H:%M:%S')} · {ago_s} ago · {info['n_symbols']}종목"

_COLUMN_LABELS: dict[str, str] = {
    "symbolCode": "Symbol",
    "stockNameEng": "Name",
    "closePrice": "Last",
    "fluctuationsRatio": "Change %",
    "accumulatedTradingVolume": "Volume",
    "marketValueRaw": "시총 (USD)",
    **{f"pct_{n}d": f"{n}d %" for n in PERIODS_D},
}
_ALL_SORT_KEYS = list(_COLUMN_LABELS.keys())
_DEFAULT_SORT = "marketValueRaw"


def render(st: Any) -> None:
    """Render the NASDAQ tab into the current Streamlit container."""
    st.markdown(STOCK_PAGE_CSS, unsafe_allow_html=True)

    universe = discover_universe()
    if not universe:
        st.warning(
            "`data/cache/us/` 가 비어 있습니다. 아래 `NASDAQ 데이터 받기` 로 NASDAQ 일봉을 먼저 받아주세요."
        )

    # ── Top toolbar ──
    # 지표 계산은 `NASDAQ 데이터 받기` 완료 시 자동 체이닝(아래 on_success_followup).
    # 강제 재계산이 필요하면 CLI: .venv/Scripts/python.exe -m dashboards._precompute --asset us
    bar_caption, bar_live, bar_fetch = st.columns([3, 2, 2])
    with bar_caption:
        st.caption(snapshot_age_caption(SNAPSHOT_PATH))
        st.caption(_precompute_caption("us"))
        st.caption(f"캐시된 NASDAQ 심볼: **{len(universe)}** 개")
    with bar_live:
        render_subprocess_launcher(
            st,
            label="라이브 가격 갱신",
            session_prefix="nas_live",
            log_path=_LIVE_LOG,
            args=python_module_args("data.sources.nasdaq_screener"),
            cwd=_ROOT,
            button_key="nas_live_btn",
            button_help="api.nasdaq.com screener 한 방 요청으로 전 종목 라이브 가격 갱신 (~2초). 백그라운드.",
        )
    with bar_fetch:
        render_subprocess_launcher(
            st,
            label="NASDAQ 데이터 받기",
            session_prefix="nas_fetch",
            log_path=_FETCH_LOG,
            args=python_module_args("data.sources.stocks", "--market", "NASDAQ"),
            cwd=_ROOT,
            button_key="nas_fetch_btn",
            button_help="FDR 로 NASDAQ 전 종목 일봉을 data/cache/us/ 로 증분 다운로드. "
                        "완료 시 지표 계산(_refs/_recs.parquet) 자동 체이닝. 백그라운드.",
        )

    render_subprocess_status(
        st,
        label="라이브 fetch",
        session_prefix="nas_live",
        log_path=_LIVE_LOG,
        success_msg="✅ 라이브 fetch 완료",
        error_msg="❌ 라이브 fetch 실패",
    )
    # NASDAQ 데이터 받기가 끝나면 자동으로 지표 계산을 이어서 시동
    render_subprocess_status(
        st,
        label="NASDAQ fetch",
        session_prefix="nas_fetch",
        log_path=_FETCH_LOG,
        success_msg="✅ NASDAQ fetch 완료 — 지표 자동 계산 시작",
        error_msg="❌ NASDAQ fetch 실패",
        on_success_clear_cache=True,
        on_success_followup=dict(
            session_prefix="nas_pre",
            log_path=_PRE_LOG,
            args=python_module_args("dashboards._precompute", "--asset", "us"),
            cwd=_ROOT,
        ),
    )
    render_subprocess_status(
        st,
        label="지표 계산",
        session_prefix="nas_pre",
        log_path=_PRE_LOG,
        success_msg="✅ 지표 계산 완료",
        error_msg="❌ 지표 계산 실패",
    )

    if not universe:
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
        c_title, c_prev, c_pos, c_next, c_memo, c_star = st.columns(
            [4, 0.8, 2.0, 0.8, 3.1, 0.7], vertical_alignment="center",
        )
        with c_title:
            render_chart_title(st, f"{name} · {symbol}")
            meta = st.session_state.get("nas_nav_meta", {}).get(symbol, {})
            render_chart_meta_line(st, [
                ("시총", fmt_compact_usd(meta.get("mcap"))),
                ("거래량", fmt_compact_count(meta.get("vol"))),
            ])
            with st.container(key="stock_chart_iv_picker"):
                chart_iv = st.segmented_control(
                    "Interval",
                    options=["1d", "1w", "1M"],
                    default="1w",
                    key="nas_chart_iv",
                    label_visibility="collapsed",
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
                    render_tv_chart_stock(
                        symbol, f"{name} · {symbol}", chart_iv, cdf, key_prefix="lwc_nasdaq",
                    )

        with tab_report:
            report_path = _latest_report_path(symbol)

            b1, _b2 = st.columns([1, 2])
            with b1:
                gen = st.button(
                    "🤖 리포트 생성" if report_path is None else "🔄 리포트 재생성",
                    key=f"nas_report_gen_{symbol}",
                    use_container_width=True,
                    help="research.report 파이프라인 — 정량 분석(가격·수익률·RSI). "
                         "한경 컨센서스는 대형주만 일부, DART·업종은 KR 전용이라 비어있습니다. 수십 초.",
                )
            st.caption("ℹ️ US는 정량 분석 위주입니다 (정성 섹션은 KR 전용 소스라 제한적).")
            if gen:
                import subprocess
                _report_log = _REPORTS_DIR / f"_gen_{symbol}.log"
                _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
                with st.spinner(f"{name}({symbol}) 리포트 생성 중… (수십 초)"):
                    with open(_report_log, "w", encoding="utf-8") as _lh:
                        rc = subprocess.run(
                            python_module_args("research.report", symbol, name),
                            cwd=str(_ROOT), stdout=_lh, stderr=subprocess.STDOUT,
                        ).returncode
                if rc == 0:
                    st.success("✅ 리포트 생성 완료")
                    report_path = _latest_report_path(symbol)
                else:
                    st.error(f"❌ 리포트 생성 실패 (exit {rc})")
                    try:
                        st.code(_report_log.read_text(encoding="utf-8", errors="replace")[-1500:] or "(로그 없음)")
                    except Exception:  # noqa: BLE001
                        pass

            if report_path is None:
                st.caption(
                    "리포트가 아직 없습니다. 위 **🤖 리포트 생성** 을 눌러주세요. "
                    f"(CLI: `.venv/Scripts/python.exe -m research.report {symbol} \"{name}\"`)"
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

        stars = st.session_state.setdefault("nas_stars", load_stars(_STARS_PATH))

        f1, f2, f3, f4 = st.columns([3, 1, 2, 1.2])
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
                options=_ALL_SORT_KEYS,
                index=_ALL_SORT_KEYS.index(_DEFAULT_SORT),
                format_func=lambda k: _COLUMN_LABELS.get(k, k),
                key="nas_sort",
            )
        with f4:
            star_only = st.checkbox(
                f"⭐ 별표만 ({len(stars)})", value=False, key="nas_star_only",
            )

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

        if star_only:
            df = df[df["symbolCode"].astype(str).isin(stars)]
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
            st.info("⭐ 별표한 종목이 없습니다." if star_only
                    else "필터 조건에 맞는 종목이 없습니다.")
            return

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

        df_grid, grid_options = build_stock_grid_options(
            df, selected_symbol,
            symbol_col="symbolCode", symbol_header="Symbol",
            name_col="stockNameEng", name_header="Name",
            price_col="closePrice", price_format="dec",
            volume_col="accumulatedTradingVolume", volume_header="Volume",
            market_cap_col="marketValueRaw", market_cap_header="시총 (USD)",
            star_codes=stars,
        )
        grid_key = f"nas_grid::v4::{top_n}::{search}::{sort_col_key}::{star_only}::{len(stars)}"
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
