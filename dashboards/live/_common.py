"""Shared helpers across the three live ticker tabs.

The three market tabs share the same top-bar layout pattern:

    [📡 스냅샷 12:34 · 5m ago]  [🔄 라이브 가격 갱신]  [📥 데이터 받기]
    [⏳ background fetch 진행 중 (시작 …) — log tail]    (when running)

This module centralizes that pattern + the timestamp formatting so each
market's orchestrator stays focused on its own data wiring.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Time formatting
# ---------------------------------------------------------------------------

def humanize_ago(delta: pd.Timedelta) -> str:
    """Compact 'Ns / Nm / Nh / Nd' age from a Timedelta."""
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def snapshot_age_caption(snapshot_path: Path) -> str:
    """'📡 스냅샷 12:34:56 · 5m ago' for a parquet file's mtime, KST.

    Returns a placeholder string if the file doesn't exist — callers can
    pass this directly to ``st.caption``.
    """
    if not snapshot_path.exists():
        return "📡 스냅샷 없음 — 아래 버튼으로 최초 받기"
    mtime = pd.Timestamp.fromtimestamp(snapshot_path.stat().st_mtime, tz="Asia/Seoul")
    ago = pd.Timestamp.now(tz="Asia/Seoul") - mtime
    return f"📡 스냅샷 {mtime.strftime('%H:%M:%S')} · {humanize_ago(ago)} ago"


def fetched_at_caption(df: pd.DataFrame) -> str:
    """'📡 시세 12:34:56 · 5m ago · 948/948 freshly updated' from a snapshot df.

    Reads the ``fetched_at`` column (per-row UTC timestamp recorded by the
    live snapshotters) and reports the latest value + how many rows share it.
    Falls back to a generic row count if the column is missing.
    """
    if "fetched_at" not in df.columns:
        return f"📡 시세 (no timestamp) · {len(df)} rows"
    fetched_ts = pd.to_datetime(df["fetched_at"], errors="coerce", utc=False)
    latest = fetched_ts.max()
    if pd.isna(latest):
        return f"📡 시세 (timestamp unknown) · {len(df)} rows"
    latest_kst = latest.tz_convert("Asia/Seoul") if latest.tzinfo is not None else latest
    ago = pd.Timestamp.now(tz="Asia/Seoul") - latest_kst
    fresh_count = int((fetched_ts == latest).sum())
    return (
        f"📡 시세 {latest_kst.strftime('%H:%M:%S')} · "
        f"{humanize_ago(ago)} ago · "
        f"{fresh_count}/{len(df)} freshly updated"
    )


# ---------------------------------------------------------------------------
# Background subprocess section (button + status + log tail)
# ---------------------------------------------------------------------------

def _read_log_tail(log_path: Path, n: int = 8) -> tuple[str, list[str]]:
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return "", []
    return text, text.splitlines()[-n:]


def render_subprocess_launcher(
    st: Any,
    *,
    label: str,
    session_prefix: str,
    log_path: Path,
    args: list[str],
    cwd: Path,
    button_key: str,
    button_help: str,
) -> None:
    """Render the launch button only — pair with ``render_subprocess_status``.

    Split from the status panel so callers can place the button in a narrow
    column (e.g. a 2-button toolbar row) while the status panel renders
    full-width below.

    Manages three session_state keys (namespaced by ``session_prefix``):
      - ``{prefix}_proc``      — the Popen handle (or None)
      - ``{prefix}_started``   — KST ISO string when the proc was launched
      - ``{prefix}_finalized`` — bool flag to avoid double cache-clear in
        the status panel's success branch

    After starting a new proc, calls ``st.rerun()`` so the status panel
    appears immediately on the next render.
    """
    proc_key = f"{session_prefix}_proc"
    started_key = f"{session_prefix}_started"
    finalized_key = f"{session_prefix}_finalized"

    proc = st.session_state.get(proc_key)
    running = proc is not None and proc.poll() is None

    btn = st.button(
        label if not running else "Fetching… (background)",
        use_container_width=True,
        key=button_key,
        disabled=running,
        help=button_help,
    )

    if btn and not running:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_path, "w", encoding="utf-8", buffering=1)
        new_proc = subprocess.Popen(
            args,
            cwd=str(cwd),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        st.session_state[proc_key] = new_proc
        st.session_state[started_key] = pd.Timestamp.now(tz="Asia/Seoul").isoformat(timespec="seconds")
        st.session_state[finalized_key] = False
        st.rerun()


def render_subprocess_status(
    st: Any,
    *,
    label: str,
    session_prefix: str,
    log_path: Path,
    success_msg: str,
    error_msg: str,
    on_success_clear_cache: bool = False,
    parse_progress: Optional[Callable[[str], dict]] = None,
    info_template: str = "⏳ {label} 진행 중 (시작 {started})",
) -> None:
    """Render the live status panel for a subprocess started by the launcher.

    No-op if the matching ``{session_prefix}_proc`` is absent (i.e. nothing
    launched in this session). When the proc is running, shows an info box +
    optional progress bar (via ``parse_progress``) + log tail + a "🔄 상태 갱신"
    rerun button. When it finishes, shows success/error + log tail + a
    "Dismiss" button to clear the panel.

    On success: optionally clears ``st.cache_data`` once (e.g. after a parquet
    refresh that invalidates the dashboard's cached MA/HL pass).
    """
    proc_key = f"{session_prefix}_proc"
    started_key = f"{session_prefix}_started"
    finalized_key = f"{session_prefix}_finalized"

    proc = st.session_state.get(proc_key)
    if proc is None:
        return
    running = proc.poll() is None

    _, tail = _read_log_tail(log_path)

    if running:
        st.info(info_template.format(label=label, started=st.session_state.get(started_key, "?")))
        if parse_progress is not None:
            log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            prog = parse_progress(log_text)
            total = prog.get("total")
            if total:
                pct = prog["idx"] / total
                detail = prog.get("detail", "")
                detail_part = f" — {detail}" if detail else ""
                st.progress(
                    min(pct, 1.0),
                    text=f"{prog.get('stage','')} {prog['idx']}/{total} ({pct*100:.1f}%)" + detail_part,
                )
            else:
                st.caption("starting…")
        if tail:
            st.code("\n".join(tail))
        if st.button("🔄 상태 갱신", use_container_width=True, key=f"{session_prefix}_refresh"):
            st.rerun()
        return

    # proc is done — show outcome
    rc = proc.returncode
    if not st.session_state.get(finalized_key):
        if rc == 0 and on_success_clear_cache:
            st.cache_data.clear()
        st.session_state[finalized_key] = True

    if rc == 0:
        st.success(success_msg)
    else:
        st.error(f"{error_msg} (rc={rc})")
    if tail:
        st.code("\n".join(tail))
    if st.button("Dismiss", use_container_width=True, key=f"{session_prefix}_dismiss"):
        st.session_state[proc_key] = None
        st.session_state[finalized_key] = False
        st.rerun()


def python_module_args(module: str, *extra: str) -> list[str]:
    """``[sys.executable, '-m', module, *extra]`` — used for subprocess.Popen.

    Wraps the venv python explicitly so background processes match the
    interpreter the dashboard is running under (per CLAUDE.md venv policy).
    """
    return [sys.executable, "-m", module, *extra]
