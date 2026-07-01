"""Live ticker dashboard — Bitget / KOSPI / NASDAQ in one tabbed page.

Replaces the previous one-page-per-market layout
(``3_Bitget.py`` / ``4_KOSPI.py`` / ``5_NASDAQ.py``). Routing the three markets
through ``st.tabs`` keeps each market's AgGrid component mounted across tab
switches — Streamlit renders all tab panes into the DOM and only toggles
visibility via CSS when the user clicks a tab, so the iframe-remount cost of
navigating between separate pages goes away.

The actual market views live in ``dashboards/live/{bitget,kospi,nasdaq}.py``;
this page is just the assembly point. The master "모든 데이터 받기" button
above the tabs runs the full pipeline (KR/US/Crypto OHLCV + live snapshots +
precompute) as a single background subprocess.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboards._lib import render_fetch_log_sidebar  # noqa: E402
from dashboards.live import bitget, kospi, nasdaq  # noqa: E402
from dashboards.live._common import render_subprocess_launcher  # noqa: E402


def _render_compact_status(st, *, session_prefix: str, log_path: Path,
                           success_msg: str, error_msg: str) -> None:
    """Sidebar-friendly slim status — 1 line + collapsed log expander.

    Replaces ``render_subprocess_status`` which uses full-width ``st.info``/
    ``st.code`` blocks that look cramped in the narrow sidebar.
    """
    proc_key = f"{session_prefix}_proc"
    started_key = f"{session_prefix}_started"
    finalized_key = f"{session_prefix}_finalized"

    proc = st.session_state.get(proc_key)
    if proc is None:
        return
    running = proc.poll() is None

    def _tail_lines(n: int = 10) -> list[str]:
        try:
            return log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
        except FileNotFoundError:
            return []

    def _log_expander() -> None:
        lines = _tail_lines()
        if not lines:
            return
        with st.expander("로그", expanded=False):
            st.code("\n".join(lines))

    if running:
        @st.fragment(run_every="2s")
        def _poll() -> None:
            cur = st.session_state.get(proc_key)
            if cur is None or cur.poll() is not None:
                st.rerun(scope="app")
                return
            started = st.session_state.get(started_key, "?")
            st.caption(f"⏳ 진행 중 · 시작 {started[-8:] if isinstance(started, str) else started}")
            _log_expander()
        _poll()
        return

    rc = proc.returncode
    if not st.session_state.get(finalized_key):
        if rc == 0:
            st.cache_data.clear()
        st.session_state[finalized_key] = True

    if rc == 0:
        st.caption(f"✅ {success_msg}")
    else:
        st.caption(f"❌ {error_msg} (rc={rc})")
    _log_expander()
    if st.button("Dismiss", use_container_width=True, key=f"{session_prefix}_dismiss"):
        st.session_state[proc_key] = None
        st.session_state[finalized_key] = False
        st.rerun()

_FETCH_ALL_LOG = _ROOT / "data" / "cache" / "_fetch_all.log"

# Sequential wrapper: OHLCV(KR/US/Crypto 1d/1h) → live snapshots → precompute.
# CLAUDE.md 데이터 업데이트 표준 순서를 그대로 따르되 단일 파이썬 프로세스로 묶어
# stage 로그가 한 파일에 흐르도록. 병렬로 돌리면 fetch_log 파일 경합 위험이 있어
# 순차로 유지.
_FETCH_ALL_WRAPPER = r"""
import subprocess, sys
cmds = [
    (sys.executable, '-m', 'data.sources.stocks', '--market', 'KOSPI'),
    (sys.executable, '-m', 'data.sources.stocks', '--market', 'NASDAQ'),
    (sys.executable, '-m', 'data.sources.bitget', '--granularity', '1d'),
    (sys.executable, '-m', 'data.sources.bitget', '--granularity', '1h'),
    (sys.executable, '-m', 'data.sources.naver_kr'),
    (sys.executable, '-m', 'data.sources.nasdaq_screener'),
    (sys.executable, '-m', 'data.sources.bitget_live'),
    (sys.executable, '-m', 'dashboards._precompute', '--asset', 'all'),
]
rc = 0
for c in cmds:
    print(f'>>> stage: {" ".join(c[2:])}', flush=True)
    r = subprocess.call(list(c))
    print(f'<<< rc={r}', flush=True)
    rc = r or rc
sys.exit(rc)
"""


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Live", page_icon="📡", layout="wide")

    # ── Sidebar: master pipeline button + last-fetch timestamps ──
    with st.sidebar:
        render_subprocess_launcher(
            st,
            label="모든 데이터 받기",
            session_prefix="fetch_all",
            log_path=_FETCH_ALL_LOG,
            args=[sys.executable, "-c", _FETCH_ALL_WRAPPER],
            cwd=_ROOT,
            button_key="fetch_all_btn",
            button_help=(
                "KR/US 일봉 + Crypto 1d/1h + 라이브 스냅샷 3종 + 지표 precompute 를 "
                "한 번에 순차 실행 (백그라운드)."
            ),
        )
        _render_compact_status(
            st,
            session_prefix="fetch_all",
            log_path=_FETCH_ALL_LOG,
            success_msg="전체 데이터 갱신 완료",
            error_msg="일부 실패",
        )
        render_fetch_log_sidebar(st, embedded=True)

    tab_crypto, tab_kospi, tab_nasdaq = st.tabs(["Crypto", "KOSPI", "NASDAQ"])
    with tab_crypto:
        bitget.render(st)
    with tab_kospi:
        kospi.render(st)
    with tab_nasdaq:
        nasdaq.render(st)


main()
