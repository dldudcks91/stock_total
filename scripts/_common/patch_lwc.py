"""Patch the vendored ``streamlit-lightweight-charts`` frontend build so the
chart no longer auto-``fitContent()`` (which squeezes ALL bars into view).

Why
---
The wrapper's compiled frontend calls ``timeScale().fitContent()`` once per
render, fitting the *entire* dataset to the chart width. That forces the
renderer (``render_tv_chart`` / ``render_tv_chart_stock``) to slice to the last
N bars so the view isn't squashed — but then panning left hits a wall even when
the cache holds more history.

This patch replaces that single ``fitContent()`` call with
``scrollToRealTime()``, which keeps the configured ``barSpacing`` and simply
scrolls to the latest bar. We can then send the *full* history; the chart opens
zoomed on recent bars and the user scrolls left through everything — exchange
style.

Idempotent: safe to run repeatedly. **Re-run after every ``pip install`` /
reinstall of ``streamlit-lightweight-charts``** (a fresh install restores the
original build). Wired into ``requirements`` setup is recommended.

Usage
-----
    .venv/Scripts/python.exe -m scripts._common.patch_lwc          # apply
    .venv/Scripts/python.exe -m scripts._common.patch_lwc --check  # report only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_OLD = "timeScale().fitContent()"
_NEW = "timeScale().scrollToRealTime()"


def _build_dir() -> Path:
    import streamlit_lightweight_charts as _pkg
    return Path(_pkg.__file__).resolve().parent / "frontend" / "build"


def apply(check_only: bool = False) -> int:
    build = _build_dir()
    js_dir = build / "static" / "js"
    if not js_dir.is_dir():
        print(f"[patch_lwc] build js dir not found: {js_dir}", file=sys.stderr)
        return 2

    # Only the component's own chunks call fitContent; the lightweight-charts
    # library chunk (2.*.chunk.js) *defines* it — never touch that one.
    targets = sorted(js_dir.glob("main.*.chunk.js"))
    if not targets:
        print(f"[patch_lwc] no main.*.chunk.js under {js_dir}", file=sys.stderr)
        return 2

    changed = 0
    already = 0
    for f in targets:
        text = f.read_text(encoding="utf-8", errors="surrogatepass")
        n = text.count(_OLD)
        if n == 0:
            if _NEW in text:
                already += 1
                print(f"[patch_lwc] already patched: {f.name}")
            continue
        if check_only:
            print(f"[patch_lwc] WOULD patch {f.name} ({n} call(s))")
            changed += n
            continue
        f.write_text(text.replace(_OLD, _NEW), encoding="utf-8",
                     errors="surrogatepass")
        changed += n
        print(f"[patch_lwc] patched {f.name}: {n} call(s) {_OLD!r} -> {_NEW!r}")

    if check_only:
        print(f"[patch_lwc] check: {changed} call(s) need patching, "
              f"{already} file(s) already patched.")
        return 1 if changed else 0

    print(f"[patch_lwc] done: {changed} call(s) patched, "
          f"{already} file(s) already up to date.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="report what would change, don't write")
    args = ap.parse_args()
    raise SystemExit(apply(check_only=args.check))


if __name__ == "__main__":
    main()
