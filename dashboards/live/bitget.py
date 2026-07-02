"""Bitget tab orchestrator — wires snapshot, cache compute, AgGrid, chart dialog.

Called from ``dashboards/pages/3_Live.py`` inside ``st.tabs[0]``.

Session state keys (all prefixed ``bitget_``):
  - ``bitget_live_proc / _started / _finalized``  — live snapshot subprocess
  - ``bitget_fetch_proc / _started / _finalized`` — OHLCV fetch subprocess
  - ``bitget_pre_proc / _started / _finalized``   — precompute subprocess
  - ``bitget_notes``       — in-session memo dict (also persisted to disk)
  - ``bitget_sel_symbol``  — currently selected row symbol
  - ``_chart_dialog_shown_for`` — symbol the chart dialog was last opened for

Data flow mirrors KOSPI / NASDAQ:

  1. live snapshot (Bitget ticker bulk endpoint) — fast, every-click
  2. OHLCV fetch (1d → 1h) — slow, chains into precompute on success
  3. precompute (dashboards._precompute --asset crypto) — writes
     ``data/cache/crypto/_refs.parquet`` anchored to the current hour bucket
  4. dashboard merges (1) snapshot + (3) precomputed refs and applies live
     mark prices via ``apply_current_prices`` to derive pct columns

CSS lives in :mod:`._bitget_grid` and is injected once per tab render. Re-
injection is idempotent (Streamlit dedupes by html content) so wrapping it
inside the fragment is safe.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from data.loader import load_ohlcv
from data.sources.bitget_live import load_snapshot
from data.sources.bitget_rwa import load_rwa_cache
from dashboards._precompute import load_recs, load_refs
from dashboards._stock_grid import (
    ChartNavigator,
    apply_top_by_rank,
    breadth_counts,
    build_stock_grid_options,
    fmt_compact_usd,
    load_stars,
    normalize_crypto_ohlcv,
    render_breadth,
    render_chart_memo,
    render_chart_meta_line,
    render_chart_star,
    render_top_by_select,
    render_top_n_input,
    render_tv_chart,
    safe_fragment_rerun,
)
from dashboards.live._bitget_grid import (
    BITGET_PAGE_CSS,
    COLUMN_LABELS,
)
from dashboards.live._common import fetched_at_caption
from dashboards.live._crypto_compute import (
    CANDLE_FETCH_CAP,
    apply_current_prices,
)

try:
    from streamlit_lightweight_charts import renderLightweightCharts  # type: ignore # noqa: F401
    _HAS_LWC = True
except ImportError:  # pragma: no cover
    _HAS_LWC = False

from st_aggrid import AgGrid, DataReturnMode, GridUpdateMode

_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _ROOT / "data" / "cache" / "crypto"
_NOTES_PATH = _CACHE_DIR / "_notes.json"
_STARS_PATH = _CACHE_DIR / "_stars.json"
_REPORTS_DIR = _ROOT / "research" / "reports"

# Top by 드롭다운 옵션 — 스냅샷 원본 컬럼 + enrichment(refs merge → pct_*·pct_ma_*·
# recs merge → g1/g2/gate_pass/g4) 후에 붙는 파생 컬럼. sort/head 전에 enrich 를
# 미리 돌려야 아래 pct_*·g* 키가 df 에 존재한다 (아래 render 흐름 참고).
_TOP_BY_LABELS: dict[str, str] = {
    "quoteVolume": "거래대금",
    "marketCap": "시총",
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
_DEFAULT_SORT = "quoteVolume"


def _coin_ticker(symbol: str) -> str:
    """Bitget USDT-M 심볼(BTCUSDT) → 코인 티커(BTC). 리포트 파일명 조회용."""
    s = str(symbol)
    return s.removesuffix("USDT") or s


def _latest_report_path(symbol: str) -> Optional[Path]:
    """Return most recent ``research/reports/{coin}/{coin}_YYYYMMDD.md`` or None.

    크립토 리포트는 코인 티커(BTC, ETH, …) 기준으로 저장 — Bitget 심볼의
    USDT 접미사를 제거해 매핑한다. KR/US 는 심볼 자체가 곧 코드.
    """
    if not _REPORTS_DIR.exists():
        return None
    coin = _coin_ticker(symbol)
    sub = _REPORTS_DIR / coin
    if not sub.exists():
        return None
    matches = sorted(sub.glob(f"{coin}_*.md"))
    return matches[-1] if matches else None


# ---------------------------------------------------------------------------
# Notes persistence
# ---------------------------------------------------------------------------

def _load_notes() -> dict:
    try:
        return json.loads(_NOTES_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_notes(notes: dict) -> None:
    _NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _NOTES_PATH.write_text(
        json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def render(st: Any) -> None:
    """Render the Bitget tab into the current Streamlit container.

    Called from inside ``with st.tabs(...)[0]:`` — does NOT call set_page_config
    (the parent page owns that). Wraps the data section in ``@st.fragment`` so
    widget interactions (filter / sort / window toggle / row select) don't
    rerun the other markets' tabs. Data-fetch / precompute is driven by the
    master "모든 데이터 받기" button on the parent page.
    """
    st.markdown(BITGET_PAGE_CSS, unsafe_allow_html=True)

    # ── Chart cache only — refs are disk-precomputed via dashboards._precompute ──
    @st.cache_data(ttl=300, show_spinner=False)
    def _chart_df_cached(symbol: str, interval: str) -> pd.DataFrame:
        # cache/crypto/{1h,1d}/{SYMBOL}.parquet → 1h/4h/1d/1w (raw or resample)
        return load_ohlcv("crypto", symbol, interval)

    _nav = ChartNavigator(
        st,
        codes_key="bitget_nav_codes", names_key="bitget_nav_names",
        sel_key="bitget_sel_symbol", name_key="bitget_sel_name",
        shown_key="_chart_dialog_shown_for", btn_prefix="bitget_chart_nav",
    )

    # ── Chart dialog (modal popup) ──
    def _render_inline_chart(symbol: str) -> None:
        # Single compact header row: search + ‹ 번호 › + memo + ★ aligned to the
        # TOP line (meta + interval picker stack below inside c_title only).
        c_title, c_prev, c_pos, c_next, c_memo, c_star = st.columns(
            [3, 0.7, 1.5, 0.7, 3.4, 0.6], vertical_alignment="top",
        )
        with c_title:
            _nav.search_box(placeholder="심볼 검색")
            meta = st.session_state.get("bitget_nav_meta", {}).get(symbol, {})
            render_chart_meta_line(st, [
                ("시총", fmt_compact_usd(meta.get("mcap"))),
                ("거래대금", fmt_compact_usd(meta.get("vol"))),
            ])
            with st.container(key="chart_iv_picker"):
                _iv_col, _vp_col = st.columns([3, 1], gap="small",
                                              vertical_alignment="center")
                with _iv_col:
                    chart_iv = st.segmented_control(
                        "Interval",
                        options=["1d", "1w", "1M"],
                        default="1w",
                        key="chart_iv",
                        label_visibility="collapsed",
                        help="Ctrl + ←/→ 로도 전환 (←/→ 는 종목 이동)",
                    )
                with _vp_col:
                    vp_on = st.checkbox(
                        "매물대", value=False, key="bitget_vp_on",
                        help="Volume Profile — 가격대별 누적 거래량을 우측 수평 바로 표시",
                    )
        with c_prev:
            _nav.button_prev()
        with c_pos:
            _nav.position_input()
        with c_next:
            _nav.button_next()
        with c_memo:
            render_chart_memo(st, symbol, _NOTES_PATH, "bitget_notes")
        with c_star:
            render_chart_star(st, symbol, _STARS_PATH, "bitget_stars")
        _nav.inject_keys()
        if not chart_iv:
            chart_iv = "1w"

        tab_chart, tab_report = st.tabs(["Chart", "Report"])

        with tab_chart:
            try:
                cdf = _chart_df_cached(symbol, chart_iv)
            except FileNotFoundError:
                st.warning(
                    f"`{symbol}` 캐시 없음 — `/crypto-fetch {symbol}` 으로 먼저 받아주세요."
                )
            except Exception as e:  # noqa: BLE001
                st.warning(f"{symbol} 캐시 로드 실패: {e}")
            else:
                if cdf is None or len(cdf) == 0:
                    st.warning(f"{symbol} 데이터 비어있음")
                elif _HAS_LWC:
                    ndf = normalize_crypto_ohlcv(cdf)
                    render_tv_chart(
                        symbol, symbol, chart_iv, ndf, key_prefix="lwc_bitget",
                        vp_on=bool(vp_on),
                    )
                else:
                    from dashboards.charts import plot_ohlcv, plotly_config
                    fig = plot_ohlcv(
                        cdf,
                        title=f"{symbol} · {chart_iv.upper()} · {len(cdf):,}봉",
                        ma_periods=(10, 20, 50), vwma_periods=(100,),
                        show_volume=True, height=420,
                    )
                    st.plotly_chart(fig, use_container_width=True,
                                    config=plotly_config())

        with tab_report:
            report_path = _latest_report_path(symbol)
            coin = _coin_ticker(symbol)
            if report_path is None:
                st.info(
                    f"📄 `{coin}` 리포트가 아직 없습니다. "
                    f'Claude 에게 "**{coin} 리포트**" 라고 요청하면 한-페이지 정성 리포트를 생성합니다. '
                    f"(저장 경로: `research/reports/{coin}/{coin}_YYYYMMDD.md`)"
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

    # Chart dialog opens when a row is freshly selected. Built-in Streamlit
    # dialog handles Esc / outside-click / X. ``_chart_dialog_shown_for``
    # tracks the symbol we last opened for so auto-reruns don't reopen a
    # dialog the user already dismissed.
    @st.dialog(" ", width="large")
    def _chart_dialog() -> None:
        sym = st.session_state.get("bitget_sel_symbol")
        if not sym:
            return
        _render_inline_chart(sym)

    @st.fragment
    def _render_data_section() -> None:
        df = load_snapshot()
        if df is None or df.empty:
            st.info(
                "📡 라이브 스냅샷 없음 — 위 `라이브 가격 갱신` 으로 먼저 받아주세요. "
                "Bitget 티커는 bulk endpoint라 1~2초면 완료."
            )
            return

        st.caption(fetched_at_caption(df))

        full_breadth = breadth_counts(df.get("change24h"))

        # Filter bar — 3 cols. Signed numeric columns always sort by |value|
        # (no toggle); see _bitget_grid.JS_ABS_COMPARATOR. MA Interval / HL
        # Lookback 토글은 제거됨 — 8개 TF×MA 갭 컬럼이 항상 표시된다.
        stars = st.session_state.setdefault("bitget_stars", load_stars(_STARS_PATH))
        rwa_set = load_rwa_cache()

        f1, f2, f3, f4 = st.columns([3, 1, 2, 1.4])
        with f1:
            search = st.text_input("Symbol contains", value="", key="flt_search").strip()
        with f2:
            render_top_n_input(
                st,
                canonical_key="_bitget_top_n_val",
                widget_key="flt_topn_toolbar",
                max_value=2000, step=10,
            )
        with f3:
            render_top_by_select(
                st,
                canonical_key="_bitget_top_by_val",
                widget_key="flt_sort_toolbar",
                options=_ALL_SORT_KEYS, labels=_TOP_BY_LABELS,
                default=_DEFAULT_SORT,
                help_text="Top N 을 뽑을 기준 컬럼. 차트 ← → 순번도 이 기준을 따름 "
                          "(그리드 헤더 클릭으로 재정렬해도 차트 번호는 유지).",
            )
        with f4:
            hide_rwa = st.checkbox(
                f"🚫 주식토큰 제외 ({len(rwa_set)})",
                value=True, key="flt_hide_rwa",
                help="Bitget contracts API isRwa=YES (토큰화 주식/ETF/원자재) 를 표에서 제거. "
                     "캐시 갱신: `.venv/Scripts/python.exe -m data.sources.bitget_rwa`",
            )

        # canonical 세션 값을 읽어 필터 로직에 사용 — 위젯 자체 값(flt_topn_*, flt_sort_*)
        # 대신 canonical 을 쓰는 이유는 toolbar 와 차트 다이얼로그 위젯이 같은 값을
        # 공유해야 하기 때문. 두 위젯 모두 render_top_*_ 헬퍼가 on_change 로 canonical
        # 을 갱신하므로 여기서 canonical 만 읽으면 어느 쪽에서 바꿔도 반영됨.
        top_n = int(st.session_state.get("_bitget_top_n_val", 0))
        sort_col_key = str(st.session_state.get("_bitget_top_by_val", _DEFAULT_SORT))

        # 1) 텍스트/RWA 필터를 먼저 적용해 universe 를 좁힌 뒤,
        # 2) refs·recs 를 머지해 pct_*·pct_ma_*·g1~g4 파생 컬럼을 붙이고,
        # 3) 마지막에 Top by 로 sort + head — 이 순서라야 파생 컬럼도 Top by
        # 대상으로 쓸 수 있다 (스냅샷 원본에는 없는 값).
        if hide_rwa and rwa_set:
            df = df[~df["symbol"].astype(str).isin(rwa_set)]
        if search:
            df = df[df["symbol"].astype(str).str.contains(search, case=False, na=False)]

        if df.empty:
            render_breadth(st, full=full_breadth)
            st.info("필터 조건에 맞는 심볼이 없습니다.")
            return

        # ── Enrichment (Top by sort 전에 미리 머지) ──
        # 벡터화된 pandas merge 이므로 필터된 universe 전체 (~500 심볼) 에 돌려도
        # 저렴하다. CANDLE_FETCH_CAP 는 아래 sort/head 이후 informational 경고로만 사용.
        current_prices = dict(zip(
            df["symbol"].astype(str),
            df.get("markPrice", pd.Series(dtype=float)),
        ))
        refs = load_refs("crypto")
        if refs is None or refs.empty:
            st.warning("⚠️ 지표 미계산 — `Bitget 데이터 받기` 버튼을 누르면 fetch 후 자동 계산됩니다.")
        else:
            try:
                derived = apply_current_prices(refs, current_prices)
                if not derived.empty:
                    overlap = [c for c in derived.columns
                               if c != "symbol" and c in df.columns]
                    if overlap:
                        df = df.drop(columns=overlap)
                    df = df.merge(derived, on="symbol", how="left")
            except Exception as e:
                st.warning(f"기간 변화율 계산 실패: {e}")

        # 전략 추천 점수 (precomputed on disk). kospi/nasdaq 와 동일 패턴 —
        # _recs.parquet 가 비어있으면 "추천" 컬럼은 모두 "—" 로 렌더링됨.
        recs = load_recs("crypto")
        if recs is not None and not recs.empty:
            try:
                recs_use = recs.drop(columns=["data_mtime"], errors="ignore")
                overlap = [c for c in recs_use.columns
                           if c != "symbol" and c in df.columns]
                if overlap:
                    df = df.drop(columns=overlap)
                df = df.merge(recs_use, on="symbol", how="left")
            except Exception as e:
                st.warning(f"추천 머지 실패: {e}")

        # ── Top by 로 순위 매기고 head(top_n) — 이 순서가 차트 ← → 번호 기준 ──
        # MA-gap 컬럼은 |값| 오름차순(=MA 가까운 순), 나머지는 내림차순(큰 값 순).
        df = apply_top_by_rank(df, sort_col_key, top_n)

        if df.empty:
            render_breadth(st, full=full_breadth)
            st.info("필터 조건에 맞는 심볼이 없습니다.")
            return

        render_breadth(st, full=full_breadth,
                       shown=breadth_counts(df.get("change24h")))

        if len(df) > CANDLE_FETCH_CAP:
            st.info(
                f"표시 심볼 {len(df)}개 > cap({CANDLE_FETCH_CAP}). "
                "Top N 을 줄이거나 검색 필터를 적용하세요."
            )

        # Per-symbol notes (memo column).
        notes = st.session_state.setdefault("bitget_notes", _load_notes())

        # Name column — Bitget USDT-M perp symbols end in "USDT"; the coin
        # name (BTCUSDT → BTC) matches KOSPI/NASDAQ's Symbol+Name pairing.
        df["name"] = df["symbol"].astype(str).map(
            lambda s: s.removesuffix("USDT") or s
        )

        # Display order drives ←/→ chart navigation (follows filter/sort).
        nav_syms = df["symbol"].astype(str).tolist()
        st.session_state["bitget_nav_codes"] = nav_syms
        st.session_state["bitget_nav_names"] = dict(
            zip(nav_syms, df["name"].astype(str))
        )
        # 시총/거래대금(USDT) — 차트 헤더 메타 라인용.
        _vol_col = "quoteVolume" if "quoteVolume" in df.columns else "usdtVolume"
        st.session_state["bitget_nav_meta"] = {
            str(r["symbol"]): {
                "mcap": r.get("marketCap"),
                "vol": r.get(_vol_col),
            }
            for _, r in df.iterrows()
        }

        SEL_KEY = "bitget_sel_symbol"
        selected_symbol: Optional[str] = st.session_state.get(SEL_KEY)
        if selected_symbol and not (df["symbol"] == selected_symbol).any():
            st.session_state.pop(SEL_KEY, None)
            selected_symbol = None

        # 그리드 표시 순서는 항상 거래대금 내림차순 — Top by 는 Top N 컷 + 차트 번호
        # 부여 용도로만 쓰고, 표에는 큰 거래대금부터 보여 익숙한 종목이 위에 오도록.
        # (nav_syms 는 위에서 Top by 순서로 이미 저장 → 차트 순번은 유지.)
        _display_col = "quoteVolume" if "quoteVolume" in df.columns else "usdtVolume"
        if _display_col in df.columns:
            df = df.sort_values(_display_col, ascending=False,
                                na_position="last").reset_index(drop=True)

        # KOSPI/NASDAQ 와 동일한 공유 빌더 — 병합 TF×MA(D10/D20/…), 터치, G1~G4
        # 컬럼이 그대로 적용된다. 크립토 스냅샷 컬럼만 매핑(가격 4자리·$-compact).
        df_grid, grid_options = build_stock_grid_options(
            df, selected_symbol,
            symbol_col="symbol", symbol_header="Symbol",
            name_col="name", name_header="Name",
            price_col="markPrice", price_header="Price", price_format="dec4",
            volume_col="quoteVolume", volume_header="거래대금", volume_format="usd",
            market_cap_col="marketCap", market_cap_header="시총", market_cap_format="usd",
            star_codes=stars,
        )
        # v6 = Name 컬럼 추가 (Symbol 옆). grid_key 를 올려 옛 v5 레이아웃 캐시를
        # 버리고 강제 re-mount 한다.
        grid_key = (
            f"bitget_grid::v6::{top_n}::{search}::{sort_col_key}::{len(stars)}"
        )
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
        # 바꾸고 ``bitget_nav_codes`` 는 서버-사이드 sort 순서 그대로 유지한다.

        # Selection → chart panel.
        sel_rows = grid_resp.get("selected_rows")
        new_sel: Optional[str] = None
        if sel_rows is not None:
            if isinstance(sel_rows, pd.DataFrame) and len(sel_rows):
                new_sel = str(sel_rows.iloc[0].get("symbol", "")) or None
            elif isinstance(sel_rows, list) and sel_rows:
                first = sel_rows[0]
                if isinstance(first, dict):
                    new_sel = str(first.get("symbol", "")) or None
        # Grid is authoritative only when *it* reports a changed selection —
        # comparing against the session symbol would fight the ←/→ navigator
        # (the grid isn't re-mounted on arrow nav, so it keeps reporting the
        # originally clicked row). See kospi.py for the full rationale.
        prev_grid_sel = st.session_state.get("_bitget_grid_prev_sel")
        st.session_state["_bitget_grid_prev_sel"] = new_sel
        if new_sel != prev_grid_sel:
            if new_sel:
                st.session_state[SEL_KEY] = new_sel
            else:
                st.session_state.pop(SEL_KEY, None)
            safe_fragment_rerun(st)

        # Chart popup: open dialog once per *new* selection. ``_shown_for``
        # tracks the symbol the dialog was last opened for, so dismissing
        # (Esc / outside-click / built-in X) doesn't trigger an immediate
        # reopen on the next rerun.
        cur_sel = st.session_state.get(SEL_KEY)
        last_shown = st.session_state.get("_chart_dialog_shown_for")
        if cur_sel and cur_sel != last_shown:
            st.session_state["_chart_dialog_shown_for"] = cur_sel
            _chart_dialog()
        elif not cur_sel and last_shown is not None:
            st.session_state.pop("_chart_dialog_shown_for", None)

    _render_data_section()
