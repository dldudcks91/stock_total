"""Streamlit-cached IO wrappers around `dashboards._lib`.

`_lib` itself stays streamlit-free so it can be imported from CLI/tests. This
module is the page-side adapter that adds `@st.cache_data` around the raw IO
helpers, keyed on (path, mtime) so re-running a backtest invalidates the cache
automatically.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from dashboards import _lib


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0


@st.cache_data(ttl=300, show_spinner=False)
def _config_cached(path_str: str, mtime: float) -> dict[str, Any]:
    return _lib.load_config(Path(path_str))


@st.cache_data(ttl=300, show_spinner=False)
def _metrics_cached(path_str: str, mtime: float) -> dict[str, Any]:
    return _lib.load_metrics(Path(path_str))


@st.cache_data(ttl=300, show_spinner=False)
def _equity_cached(path_str: str, mtime: float) -> pd.DataFrame:
    return _lib.load_equity(Path(path_str))


@st.cache_data(ttl=300, show_spinner=False)
def _trades_cached(path_str: str, mtime: float) -> pd.DataFrame:
    return _lib.load_trades(Path(path_str))


def load_config(run_dir: Path) -> dict[str, Any]:
    p = run_dir / "config.yaml"
    return _config_cached(str(run_dir), _mtime(p))


def load_metrics(run_dir: Path) -> dict[str, Any]:
    p = run_dir / "metrics.json"
    return _metrics_cached(str(run_dir), _mtime(p))


def load_equity(run_dir: Path) -> pd.DataFrame:
    p = run_dir / "equity.parquet"
    return _equity_cached(str(run_dir), _mtime(p))


def load_trades(run_dir: Path) -> pd.DataFrame:
    p = run_dir / "trades.parquet"
    return _trades_cached(str(run_dir), _mtime(p))
