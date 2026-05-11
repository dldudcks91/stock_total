"""Compare two backtest run directories.

Usage:
    python -m backtest.compare RUN_A RUN_B [--csv out.csv]

RUN_A / RUN_B can be:
    - directory name (e.g. ``20260510-120000_sma_cross_BTCUSDT``)
      -> resolved against ``backtest/runs/``
    - absolute or relative path to a run directory
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import yaml

RUNS_ROOT = Path(__file__).resolve().parent / "runs"


# ---------------------------------------------------------------------------
# path / IO
# ---------------------------------------------------------------------------
def resolve_run_dir(spec: str) -> Path:
    """Resolve a run spec into an existing directory.

    Accepts a bare directory name (looked up under ``backtest/runs/``) or any
    absolute/relative path.
    """
    p = Path(spec)
    if p.is_dir():
        return p.resolve()
    candidate = RUNS_ROOT / spec
    if candidate.is_dir():
        return candidate.resolve()
    raise FileNotFoundError(
        f"Run directory not found: {spec!r}. "
        f"Tried as path and under {RUNS_ROOT}."
    )


def _require(path: Path, what: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(
            f"{what} not found at {path}. "
            f"Run directory looks incomplete: {path.parent}"
        )
    return path


def load_metrics(run_dir: Path) -> dict[str, Any]:
    p = _require(run_dir / "metrics.json", "metrics.json")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_config(run_dir: Path) -> dict[str, Any]:
    p = _require(run_dir / "config.yaml", "config.yaml")
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_equity(run_dir: Path) -> pd.DataFrame:
    p = _require(run_dir / "equity.parquet", "equity.parquet")
    return pd.read_parquet(p)


# ---------------------------------------------------------------------------
# math helpers (recomputed equity stats)
# ---------------------------------------------------------------------------
def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return float("nan")
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def _sharpe(returns: pd.Series, periods_per_year: float = 24 * 365) -> float:
    if returns.empty:
        return float("nan")
    std = returns.std(ddof=0)
    if not std or math.isnan(std) or std == 0:
        return float("nan")
    return float(returns.mean() / std * math.sqrt(periods_per_year))


def _periods_per_year(interval: str | None) -> float:
    table = {
        "1h": 24 * 365,
        "4h": 6 * 365,
        "1d": 365,
        "1w": 52,
    }
    if interval is None:
        return 24 * 365
    return table.get(str(interval).lower(), 24 * 365)


# ---------------------------------------------------------------------------
# formatting
# ---------------------------------------------------------------------------
def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if math.isnan(v):
            return "nan"
        return f"{v:.6g}"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (np.floating,)):
        return _fmt(float(v))
    return str(v)


def _delta(a: Any, b: Any) -> str:
    """delta = B - A, only for numeric scalars."""
    try:
        if isinstance(a, bool) or isinstance(b, bool):
            return ""
        af = float(a)
        bf = float(b)
    except (TypeError, ValueError):
        return ""
    if math.isnan(af) or math.isnan(bf):
        return ""
    d = bf - af
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.6g}"


def _print_table(rows: list[tuple[str, str, str, str]], headers: tuple[str, str, str, str]) -> None:
    cols = list(zip(headers, *rows))
    widths = [max(len(str(x)) for x in col) for col in cols]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    for row in rows:
        print(fmt.format(*row))


# ---------------------------------------------------------------------------
# config diff
# ---------------------------------------------------------------------------
def _flatten(d: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(_flatten(v, key))
    else:
        out[prefix] = d
    return out


def diff_configs(cfg_a: dict[str, Any], cfg_b: dict[str, Any]) -> list[tuple[str, str, str]]:
    fa = _flatten(cfg_a)
    fb = _flatten(cfg_b)
    keys = sorted(set(fa) | set(fb))
    rows: list[tuple[str, str, str]] = []
    for k in keys:
        va = fa.get(k, "<missing>")
        vb = fb.get(k, "<missing>")
        if va != vb:
            rows.append((k, _fmt(va), _fmt(vb)))
    return rows


# ---------------------------------------------------------------------------
# equity comparison
# ---------------------------------------------------------------------------
def equity_summary(eq: pd.DataFrame, interval: str | None) -> dict[str, float]:
    if "timestamp" not in eq.columns or "equity" not in eq.columns:
        raise ValueError("equity.parquet missing 'timestamp' or 'equity' column")
    e = eq.sort_values("timestamp").reset_index(drop=True)
    rets = e["equity"].pct_change().dropna()
    return {
        "final_equity": float(e["equity"].iloc[-1]) if len(e) else float("nan"),
        "max_drawdown": _max_drawdown(e["equity"]),
        "sharpe_recalc": _sharpe(rets, _periods_per_year(interval)),
        "n_points": int(len(e)),
    }


def equity_intersection_summary(
    eq_a: pd.DataFrame, eq_b: pd.DataFrame, interval: str | None
) -> tuple[dict[str, float], dict[str, float], int]:
    a = eq_a[["timestamp", "equity"]].sort_values("timestamp")
    b = eq_b[["timestamp", "equity"]].sort_values("timestamp")
    common = pd.Index(a["timestamp"]).intersection(pd.Index(b["timestamp"]))
    a2 = a[a["timestamp"].isin(common)].reset_index(drop=True)
    b2 = b[b["timestamp"].isin(common)].reset_index(drop=True)
    return (
        equity_summary(a2, interval),
        equity_summary(b2, interval),
        len(common),
    )


# ---------------------------------------------------------------------------
# main comparison
# ---------------------------------------------------------------------------
def compare(run_a: Path, run_b: Path) -> dict[str, list]:
    name_a = run_a.name
    name_b = run_b.name

    metrics_a = load_metrics(run_a)
    metrics_b = load_metrics(run_b)
    cfg_a = load_config(run_a)
    cfg_b = load_config(run_b)

    # warn on mismatch
    warnings: list[str] = []
    for key in ("strategy", "symbol", "interval"):
        if cfg_a.get(key) != cfg_b.get(key):
            warnings.append(
                f"WARNING: {key} differs ({cfg_a.get(key)!r} vs {cfg_b.get(key)!r})"
            )

    # metrics table
    keys = list(dict.fromkeys(list(metrics_a.keys()) + list(metrics_b.keys())))
    metric_rows: list[tuple[str, str, str, str]] = []
    for k in keys:
        va = metrics_a.get(k)
        vb = metrics_b.get(k)
        metric_rows.append((k, _fmt(va), _fmt(vb), _delta(va, vb)))

    # config diff
    cfg_rows = diff_configs(cfg_a, cfg_b)

    # equity intersection
    eq_a = load_equity(run_a)
    eq_b = load_equity(run_b)
    interval = cfg_a.get("interval") or cfg_b.get("interval")
    sum_a, sum_b, n_common = equity_intersection_summary(eq_a, eq_b, interval)
    eq_keys = ["final_equity", "max_drawdown", "sharpe_recalc", "n_points"]
    eq_rows: list[tuple[str, str, str, str]] = []
    for k in eq_keys:
        va = sum_a[k]
        vb = sum_b[k]
        eq_rows.append((k, _fmt(va), _fmt(vb), _delta(va, vb)))

    headers_metrics = (
        "metric",
        f"A={name_a}",
        f"B={name_b}",
        "delta",
    )

    # print
    for w in warnings:
        print(w)
    if warnings:
        print()

    print("== metrics.json ==")
    _print_table(metric_rows, headers_metrics)

    print()
    print("== config diff (different keys only) ==")
    if cfg_rows:
        _print_table(
            [(k, a, b, "") for (k, a, b) in cfg_rows],
            ("key", f"A={name_a}", f"B={name_b}", ""),
        )
    else:
        print("(no differences)")

    print()
    print(f"== equity (intersection: {n_common} points) ==")
    _print_table(eq_rows, headers_metrics)

    return {
        "metrics": metric_rows,
        "config_diff": cfg_rows,
        "equity": eq_rows,
        "headers": list(headers_metrics),
        "warnings": warnings,
    }


def write_csv(out_path: Path, result: dict[str, list]) -> None:
    headers = result["headers"]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["section", *headers])
        for row in result["metrics"]:
            w.writerow(["metric", *row])
        for row in result["config_diff"]:
            w.writerow(["config_diff", row[0], row[1], row[2], ""])
        for row in result["equity"]:
            w.writerow(["equity", *row])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backtest.compare",
        description="Compare two backtest run directories.",
    )
    parser.add_argument("run_a", help="run dir name (under backtest/runs/) or path")
    parser.add_argument("run_b", help="run dir name (under backtest/runs/) or path")
    parser.add_argument("--csv", default=None, help="optional CSV output path")
    args = parser.parse_args(list(argv) if argv is not None else None)

    run_a = resolve_run_dir(args.run_a)
    run_b = resolve_run_dir(args.run_b)

    result = compare(run_a, run_b)

    if args.csv:
        out = Path(args.csv)
        write_csv(out, result)
        print(f"\nwrote CSV: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
