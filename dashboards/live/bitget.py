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
import re
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from data.loader import load_ohlcv
from data.sources.bitget_live import SNAPSHOT_PATH, load_snapshot
from dashboards._precompute import load_recs, load_refs, precompute_status
from dashboards.live._bitget_grid import (
    BITGET_PAGE_CSS,
    COLUMN_LABELS,
    build_grid_options,
)
from dashboards.live._common import (
    fetched_at_caption,
    python_module_args,
    render_subprocess_launcher,
    render_subprocess_status,
    snapshot_age_caption,
)
from dashboards.live._crypto_compute import (
    CANDLE_FETCH_CAP,
    DEFAULT_HL_LOOKBACK_CRYPTO,
    DEFAULT_MA_INTERVAL_CRYPTO,
    HL_LOOKBACK_OPTIONS_CRYPTO,
    MA_INTERVAL_OPTIONS_CRYPTO,
    apply_current_prices,
)

try:
    from dashboards.live._bitget_chart import render_tv_chart
    _HAS_LWC = True
except ImportError:  # pragma: no cover
    _HAS_LWC = False

from st_aggrid import AgGrid, GridUpdateMode

_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _ROOT / "data" / "cache" / "crypto"
_FETCH_LOG = _CACHE_DIR / "_fetch.log"
_LIVE_LOG = _CACHE_DIR / "_live_fetch.log"
_PRE_LOG = _CACHE_DIR / "_precompute.log"
_NOTES_PATH = _CACHE_DIR / "_notes.json"

_ALL_SORT_KEYS = list(COLUMN_LABELS.keys())
_DEFAULT_SORT = "quoteVolume"


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
# Precompute caption (mirrors kospi/nasdaq toolbar caption)
# ---------------------------------------------------------------------------

def _precompute_caption() -> str:
    """'📊 지표 12:34 · 5m ago · 600종목' for the toolbar caption."""
    info = precompute_status("crypto")
    mt = info.get("refs_mtime")
    if mt is None:
        return "📊 지표 미계산 — `Bitget 데이터 받기` 시 자동 계산"
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


# ---------------------------------------------------------------------------
# Fetch-log progress parser (for the data-fetch subprocess progress bar)
# ---------------------------------------------------------------------------

def _parse_fetch_progress(log_text: str) -> dict:
    """Extract latest granularity / counter / symbol from ``bitget.py`` stdout."""
    gran = None
    last_idx = 0
    total = 0
    last_sym = ""
    last_rows = ""
    for line in log_text.splitlines():
        m = re.search(r"granularity=(\w+)", line)
        if m:
            gran = m.group(1)
            last_idx = 0  # stage switch — reset counter
        m = re.match(r"\[\s*(\d+)/(\d+)\]\s+(\S+)\s+rows=\s*(\d+)", line)
        if m:
            last_idx = int(m.group(1))
            total = int(m.group(2))
            last_sym = m.group(3)
            last_rows = m.group(4)
    return {
        "stage": gran or "",
        "idx": last_idx,
        "total": total,
        "detail": f"last: {last_sym} rows={last_rows}" if last_sym else "",
    }


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def render(st: Any) -> None:
    """Render the Bitget tab into the current Streamlit container.

    Called from inside ``with st.tabs(...)[0]:`` — does NOT call set_page_config
    (the parent page owns that). Wraps the data section in ``@st.fragment`` so
    widget interactions (filter / sort / window toggle / row select) don't
    rerun the other markets' tabs.
    """
    st.markdown(BITGET_PAGE_CSS, unsafe_allow_html=True)

    # ── Top toolbar: caption (2 lines) + 2 launch buttons ──
    # 지표 계산은 `Bitget 데이터 받기` 완료 시 자동 체이닝(아래 on_success_followup).
    # 강제 재계산이 필요하면 CLI: .venv/Scripts/python.exe -m dashboards._precompute --asset crypto
    bar_caption, bar_live, bar_fetch = st.columns([3, 2, 2])
    with bar_caption:
        st.caption(snapshot_age_caption(SNAPSHOT_PATH))
        st.caption(_precompute_caption())
    with bar_live:
        render_subprocess_launcher(
            st,
            label="라이브 가격 갱신",
            session_prefix="bitget_live",
            log_path=_LIVE_LOG,
            args=python_module_args("data.sources.bitget_live"),
            cwd=_ROOT,
            button_key="bitget_live_btn",
            button_help="Bitget 티커 + CoinGecko 시총을 받아 _live_snapshot.parquet 에 머지. 백그라운드.",
        )
    with bar_fetch:
        # 1d → 1h 순차 실행을 한 파이썬 프로세스로 묶음 — Popen 한 번으로 stage 추적이 깔끔.
        fetch_wrapper = (
            "import subprocess, sys;"
            "rc1 = subprocess.call([sys.executable,'-m','data.sources.bitget','--granularity','1d']);"
            "rc2 = subprocess.call([sys.executable,'-m','data.sources.bitget','--granularity','1h']);"
            "sys.exit(rc1 or rc2)"
        )
        render_subprocess_launcher(
            st,
            label="Bitget 데이터 받기",
            session_prefix="bitget_fetch",
            log_path=_FETCH_LOG,
            args=[sys.executable, "-c", fetch_wrapper],
            cwd=_ROOT,
            button_key="bitget_fetch_btn",
            button_help="Bitget USDT-M 전 종목 1D + 1H OHLCV 를 data/cache/crypto/ 로 증분 다운로드. "
                        "완료 시 지표 계산(_refs.parquet) 자동 체이닝. 백그라운드.",
        )

    # ── Status panels (full-width, only visible when a proc is/was running) ──
    render_subprocess_status(
        st,
        label="라이브 fetch",
        session_prefix="bitget_live",
        log_path=_LIVE_LOG,
        success_msg="✅ 라이브 fetch 완료",
        error_msg="❌ 라이브 fetch 실패",
    )
    # Bitget 데이터 받기가 끝나면 자동으로 지표 계산을 이어서 시동 (kospi/nasdaq 와 동일 패턴)
    render_subprocess_status(
        st,
        label="Bitget fetch",
        session_prefix="bitget_fetch",
        log_path=_FETCH_LOG,
        success_msg="✅ Bitget fetch 완료 — 지표 자동 계산 시작",
        error_msg="❌ Bitget fetch 실패",
        on_success_clear_cache=True,
        parse_progress=_parse_fetch_progress,
        on_success_followup=dict(
            session_prefix="bitget_pre",
            log_path=_PRE_LOG,
            args=python_module_args("dashboards._precompute", "--asset", "crypto"),
            cwd=_ROOT,
        ),
    )
    render_subprocess_status(
        st,
        label="지표 계산",
        session_prefix="bitget_pre",
        log_path=_PRE_LOG,
        success_msg="✅ 지표 계산 완료",
        error_msg="❌ 지표 계산 실패",
    )

    # ── Chart cache only — refs are disk-precomputed via dashboards._precompute ──
    @st.cache_data(ttl=300, show_spinner=False)
    def _chart_df_cached(symbol: str, interval: str) -> pd.DataFrame:
        # cache/crypto/{1h,1d}/{SYMBOL}.parquet → 1h/4h/1d/1w (raw or resample)
        return load_ohlcv("crypto", symbol, interval)

    # ── Chart dialog (modal popup) ──
    def _render_inline_chart(symbol: str) -> None:
        col_left, _spacer = st.columns([2, 3], vertical_alignment="center")
        with col_left:
            st.markdown(
                f"<div style='text-align:left; font-size:17px; font-weight:600; "
                f"padding-top:0px; margin-top:-6px; line-height:28px; white-space:nowrap; "
                f"overflow:hidden; text-overflow:ellipsis;'>{symbol}</div>",
                unsafe_allow_html=True,
            )
            with st.container(key="chart_iv_picker"):
                chart_iv = st.segmented_control(
                    "Interval",
                    options=["1d", "1w", "1M"],
                    default="1w",
                    key="chart_iv",
                    label_visibility="collapsed",
                )
        if not chart_iv:
            chart_iv = "1w"

        try:
            cdf = _chart_df_cached(symbol, chart_iv)
        except FileNotFoundError:
            st.warning(
                f"`{symbol}` 캐시 없음 — `/crypto-fetch {symbol}` 으로 먼저 받아주세요."
            )
            return
        except Exception as e:  # noqa: BLE001
            st.warning(f"{symbol} 캐시 로드 실패: {e}")
            return
        if cdf is None or len(cdf) == 0:
            st.warning(f"{symbol} 데이터 비어있음")
            return

        if _HAS_LWC:
            render_tv_chart(symbol, chart_iv, cdf)
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

        # Filter bar — 5 cols, mirrors KOSPI/NASDAQ layout.
        f1, f2, f3, f4, f5 = st.columns([3, 1, 2, 2, 3])
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
                options=_ALL_SORT_KEYS,
                index=_ALL_SORT_KEYS.index(_DEFAULT_SORT),
                format_func=lambda k: COLUMN_LABELS.get(k, k),
                key="flt_sort",
            )
        with f4:
            ma_interval = st.segmented_control(
                "MA Interval",
                options=MA_INTERVAL_OPTIONS_CRYPTO,
                default=DEFAULT_MA_INTERVAL_CRYPTO,
                key="flt_ma_interval",
                help="MA10/MA20 봉 단위. 1h/4h → 1H 캐시, 1d/1w → 1D 캐시 stride 샘플링.",
            )
            if not ma_interval:
                ma_interval = DEFAULT_MA_INTERVAL_CRYPTO
        with f5:
            hl_lookback = st.segmented_control(
                "HL Lookback",
                options=HL_LOOKBACK_OPTIONS_CRYPTO,
                default=DEFAULT_HL_LOOKBACK_CRYPTO,
                key="flt_hl_lookback",
                help="High/Low Δ% 기간 (wall-clock anchored). "
                     "24h → 1H 캐시 24봉, 그 외 → 1D 캐시.",
            )
            if not hl_lookback:
                hl_lookback = DEFAULT_HL_LOOKBACK_CRYPTO

        # Apply filter / sort / top_n (always descending — Top N + sort-by-volume).
        if search:
            df = df[df["symbol"].astype(str).str.contains(search, case=False, na=False)]
        if sort_col_key in df.columns:
            df = df.sort_values(sort_col_key, ascending=False, na_position="last")
        if top_n > 0:
            df = df.head(int(top_n))
        df = df.reset_index(drop=True)

        if df.empty:
            st.info("필터 조건에 맞는 심볼이 없습니다.")
            return

        # Disk-precomputed refs (anchored to current hour bucket via
        # dashboards._precompute --asset crypto) + cheap per-rerun apply that
        # combines refs with live mark prices. Same pattern as kospi/nasdaq.
        visible_symbols = df["symbol"].astype(str).tolist()
        if len(visible_symbols) > CANDLE_FETCH_CAP:
            st.info(
                f"표시 심볼 {len(visible_symbols)}개 > cap({CANDLE_FETCH_CAP}). "
                "Top N 을 줄이거나 검색 필터를 적용하세요."
            )
        else:
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

        # Per-symbol notes (memo column).
        notes = st.session_state.setdefault("bitget_notes", _load_notes())
        df["note"] = df["symbol"].astype(str).map(notes).fillna("")

        SEL_KEY = "bitget_sel_symbol"
        selected_symbol: Optional[str] = st.session_state.get(SEL_KEY)
        if selected_symbol and not (df["symbol"] == selected_symbol).any():
            st.session_state.pop(SEL_KEY, None)
            selected_symbol = None

        df_grid, grid_options = build_grid_options(
            df, ma_interval, hl_lookback, selected_symbol,
        )
        # Re-key the grid on every visible-state change including MA Interval
        # and HL Lookback. Without the window keys in the grid_key,
        # streamlit-aggrid reuses the existing component with cached gridOptions
        # and the JsCode valueGetter doesn't pick up the new window suffix —
        # so cells show stale values even though the underlying df_grid carries
        # the right columns. Matches the stock-side strategy in _stock_grid.py.
        grid_key = f"bitget_grid::v2::{top_n}::{search}::{sort_col_key}::{ma_interval}::{hl_lookback}"
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

        # Persist memo edits (silent, no rerun).
        edited_df = grid_resp.get("data")
        if edited_df is not None and "note" in edited_df.columns:
            notes_changed = False
            for sym, new_val in zip(edited_df["symbol"].astype(str), edited_df["note"].astype(str)):
                new_val = (new_val or "").strip()
                cur_val = notes.get(sym, "")
                if new_val != cur_val:
                    if new_val:
                        notes[sym] = new_val
                    else:
                        notes.pop(sym, None)
                    notes_changed = True
            if notes_changed:
                _save_notes(notes)

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
        if new_sel != selected_symbol:
            if new_sel:
                st.session_state[SEL_KEY] = new_sel
            else:
                st.session_state.pop(SEL_KEY, None)
            st.rerun(scope="fragment")

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
