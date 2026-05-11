"""Shared helpers for the Streamlit dashboards.

Pure / IO-only code lives here so that pages can `from dashboards._lib import ...`
without re-defining boilerplate. Streamlit & plotly imports stay inside the
page modules (so this file is safe to import in test or CLI contexts).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "backtest" / "runs"

METRIC_KEYS: list[str] = [
    "total_return",
    "cagr",
    "sharpe",
    "mdd",
    "n_bars",
    "n_trades",
    "win_rate",
    "avg_pnl_pct",
    "avg_holding_bars",
]

# Whether a higher value is "better" for that metric. Used by Compare to pick
# the green/red direction. None = neutral (count-style, no good/bad).
METRIC_HIGHER_IS_BETTER: dict[str, bool | None] = {
    "total_return": True,
    "cagr": True,
    "sharpe": True,
    "mdd": True,           # mdd is stored as a negative number; closer to 0 is better -> higher better
    "n_bars": None,
    "n_trades": None,
    "win_rate": True,
    "avg_pnl_pct": True,
    "avg_holding_bars": None,
}

PCT_METRICS = {"total_return", "cagr", "mdd", "win_rate", "avg_pnl_pct"}
INT_METRICS = {"n_bars", "n_trades"}


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def list_runs(runs_dir: Path = RUNS_DIR) -> list[Path]:
    """Return run directories sorted newest first.

    A run directory is any subdir of `runs_dir` containing `metrics.json`.
    """
    if not runs_dir.exists():
        return []
    runs = [
        p for p in runs_dir.iterdir()
        if p.is_dir() and (p / "metrics.json").exists()
    ]
    runs.sort(key=lambda p: p.name, reverse=True)
    return runs


def load_config(run_dir: Path) -> dict[str, Any]:
    cfg_path = run_dir / "config.yaml"
    if not cfg_path.exists():
        return {}
    try:
        import yaml  # type: ignore
        with cfg_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        cfg: dict[str, Any] = {}
        for line in cfg_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k, _, v = line.partition(":")
            cfg[k.strip()] = v.strip()
        return cfg


def load_metrics(run_dir: Path) -> dict[str, Any]:
    p = run_dir / "metrics.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def load_equity(run_dir: Path) -> pd.DataFrame:
    p = run_dir / "equity.parquet"
    if not p.exists():
        return pd.DataFrame(columns=["timestamp", "equity", "ret", "position"])
    return pd.read_parquet(p)


def load_trades(run_dir: Path) -> pd.DataFrame:
    p = run_dir / "trades.parquet"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p)


# ---------------------------------------------------------------------------
# Pure computations
# ---------------------------------------------------------------------------

def compute_drawdown(equity: pd.Series) -> pd.Series:
    """Standard drawdown: dd = equity / equity.cummax() - 1. Values <= 0."""
    eq = pd.Series(equity).astype(float)
    if eq.empty:
        return eq
    return eq / eq.cummax() - 1.0


def to_utc_datetime(ts_ms: pd.Series) -> pd.Series:
    return pd.to_datetime(ts_ms, unit="ms", utc=True)


def to_kst(dt_utc: pd.Series) -> pd.Series:
    return dt_utc.dt.tz_convert("Asia/Seoul")


def position_distribution(position: pd.Series) -> pd.DataFrame:
    """Cumulative bar count per position bucket as a fraction."""
    s = pd.Series(position).fillna(0).astype(int)
    counts = s.value_counts().reindex([-1, 0, 1], fill_value=0)
    total = int(counts.sum()) or 1
    return pd.DataFrame({
        "position": ["-1 (short)", "0 (flat)", "+1 (long)"],
        "bars": counts.values,
        "fraction": counts.values / total,
    })


def annotate_trades(trades: pd.DataFrame) -> pd.DataFrame:
    """Add cum_pnl_pct + datetime cols; return last 100."""
    if trades.empty:
        return trades.copy()
    df = trades.copy()
    if "pnl_pct" in df.columns:
        df["cum_pnl_pct"] = df["pnl_pct"].cumsum()
    for col in ("entry_ts", "exit_ts"):
        if col in df.columns:
            df[col + "_dt"] = to_utc_datetime(df[col])
    return df.tail(100).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Multi-run helpers (used by Compare)
# ---------------------------------------------------------------------------

def flatten_dict(d: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dict to dotted-key map. Non-dict leaves kept as-is."""
    out: dict[str, Any] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(flatten_dict(v, key))
    else:
        out[prefix] = d
    return out


def config_diff_table(configs: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """Given {label: config_dict} for N runs, return a DataFrame whose rows are
    flattened keys that DIFFER across at least two runs, with one column per
    label. Missing keys are filled with the string ``"<missing>"``.
    """
    if not configs:
        return pd.DataFrame()
    flats = {label: flatten_dict(cfg) for label, cfg in configs.items()}
    all_keys = sorted({k for fl in flats.values() for k in fl})
    rows: dict[str, dict[str, Any]] = {}
    for k in all_keys:
        values = [fl.get(k, "<missing>") for fl in flats.values()]
        if len(set(map(repr, values))) > 1:
            rows[k] = {label: fl.get(k, "<missing>") for label, fl in flats.items()}
    return pd.DataFrame.from_dict(rows, orient="index", columns=list(configs.keys()))


def metrics_table(runs_metrics: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """Given {label: metrics_dict}, return a DataFrame with rows=labels and
    columns=METRIC_KEYS. Missing values are NaN.
    """
    if not runs_metrics:
        return pd.DataFrame(columns=METRIC_KEYS)
    rows = []
    index = []
    for label, m in runs_metrics.items():
        index.append(label)
        rows.append({k: m.get(k) for k in METRIC_KEYS})
    return pd.DataFrame(rows, index=index, columns=METRIC_KEYS)


def detect_mismatches(configs: dict[str, dict[str, Any]]) -> list[str]:
    """Return human-readable warning lines if strategy/symbol/interval differ
    across any of the runs (matches the policy in `compare-runs` skill).
    """
    warnings: list[str] = []
    for key in ("strategy", "symbol", "interval"):
        seen = {label: cfg.get(key) for label, cfg in configs.items()}
        unique = set(seen.values())
        if len(unique) > 1:
            parts = ", ".join(f"{label}={v!r}" for label, v in seen.items())
            warnings.append(f"`{key}` differs across runs ({parts})")
    return warnings


# ---------------------------------------------------------------------------
# Formatters (string-only, safe for any scalar)
# ---------------------------------------------------------------------------

def fmt_pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.2f}%"
    except (TypeError, ValueError):
        return "—"


def fmt_float(x: Any, digits: int = 3) -> str:
    try:
        return f"{float(x):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def fmt_int(x: Any) -> str:
    try:
        return f"{int(x):,}"
    except (TypeError, ValueError):
        return "—"


def fmt_metric(key: str, value: Any) -> str:
    """Format a metric value according to its key (pct vs int vs float)."""
    if value is None:
        return "—"
    if key in PCT_METRICS:
        return fmt_pct(value)
    if key in INT_METRICS:
        return fmt_int(value)
    return fmt_float(value, 3)
