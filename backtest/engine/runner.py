"""Vectorized backtest engine.

CLI:
    python -m backtest.engine.runner \
        --strategy sma_cross --symbol BTCUSDT --interval 1h \
        --start 2023-01-01 --params '{"fast":10,"slow":30}'

Outputs (under ``backtest/runs/{YYYYMMDD-HHMMSS}_{strategy}_{symbol}/``):
    config.yaml      — parameters used
    equity.parquet   — timestamp, equity, ret, position
    trades.parquet   — round-trip trades (long/short)
    metrics.json     — total_return, cagr, sharpe, mdd, n_bars, n_trades,
                       win_rate, avg_pnl_pct, avg_holding_bars
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import yaml

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = PROJECT_ROOT / "backtest" / "runs"

BARS_PER_YEAR = {
    "1h": 8760,
    "4h": 2190,
    "1d": 365,
    "1w": 52,
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _load_strategy(name: str):
    mod = importlib.import_module(f"backtest.strategies.{name}")
    for attr in ("NAME", "DEFAULT_PARAMS", "signal"):
        if not hasattr(mod, attr):
            raise AttributeError(f"strategy '{name}' missing attribute '{attr}'")
    return mod


def _parse_ts(s: Optional[str]) -> Optional[int]:
    """Parse 'YYYY-MM-DD' (or full ISO) → UTC epoch ms. None → None."""
    if s is None or s == "":
        return None
    ts = pd.Timestamp(s)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return int(ts.value // 10**6)


def _slice_df(df: pd.DataFrame, start_ms: Optional[int], end_ms: Optional[int]) -> pd.DataFrame:
    out = df
    if start_ms is not None:
        out = out[out["timestamp"] >= start_ms]
    if end_ms is not None:
        out = out[out["timestamp"] <= end_ms]
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# core engine
# ---------------------------------------------------------------------------
def run_backtest(
    df: pd.DataFrame,
    sig: pd.Series,
    *,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    init_capital: float = 10_000.0,
    bars_per_year: int = 8760,
) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Run vectorized backtest.

    Returns (equity_df, trades_df, metrics_dict).
    """
    if len(df) < 2:
        raise ValueError("need at least 2 bars to backtest")

    df = df.reset_index(drop=True)
    sig = pd.Series(sig).reset_index(drop=True).astype("int8")
    if len(sig) != len(df):
        raise ValueError(f"signal length {len(sig)} != df length {len(df)}")

    close = df["close"].astype("float64").to_numpy()
    bar_ret = pd.Series(close).pct_change().fillna(0.0).to_numpy()

    # signal at t executed at t+1: shift forward by one
    pos = pd.Series(sig).shift(1).fillna(0).astype("int8").to_numpy()

    # turnover = |Δposition| (includes entry on first bar from 0 -> pos[0])
    pos_prev = np.concatenate([[0], pos[:-1]])
    turnover = np.abs(pos.astype("int32") - pos_prev.astype("int32")).astype("float64")

    cost_per_unit = (fee_bps + slippage_bps) / 10_000.0
    cost = turnover * cost_per_unit

    strat_ret = pos.astype("float64") * bar_ret
    net_ret = strat_ret - cost

    equity = init_capital * np.cumprod(1.0 + net_ret)

    equity_df = pd.DataFrame(
        {
            "timestamp": df["timestamp"].astype("int64").to_numpy(),
            "equity": equity.astype("float64"),
            "ret": net_ret.astype("float64"),
            "position": pos.astype("int8"),
        }
    )

    trades_df = _extract_trades(df, pos, close)
    metrics = _compute_metrics(equity_df, trades_df, bars_per_year)
    return equity_df, trades_df, metrics


def _extract_trades(df: pd.DataFrame, pos: np.ndarray, close: np.ndarray) -> pd.DataFrame:
    """Round-trip trades from a position array.

    A trade starts when position transitions from 0/-x to a non-zero side, and
    ends when the position changes (either flips or returns to 0). Entry/exit
    prices are the close at the bar where the position is first/last held.
    Reverse (long↔short) yields two trades.
    """
    n = len(pos)
    ts = df["timestamp"].astype("int64").to_numpy()

    trades = []
    cur_side = 0
    entry_i = None

    def close_trade(end_i: int):
        nonlocal cur_side, entry_i
        if cur_side == 0 or entry_i is None:
            return
        entry_price = float(close[entry_i])
        exit_price = float(close[end_i])
        pnl_pct = (exit_price / entry_price - 1.0) * cur_side
        trades.append(
            {
                "side": int(cur_side),
                "entry_ts": int(ts[entry_i]),
                "exit_ts": int(ts[end_i]),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "bars": int(end_i - entry_i),
                "pnl_pct": float(pnl_pct),
            }
        )
        cur_side = 0
        entry_i = None

    for i in range(n):
        side = int(pos[i])
        if side != cur_side:
            if cur_side != 0:
                # close at this bar (inclusive end is i, but exit price uses close[i])
                close_trade(i)
            if side != 0:
                cur_side = side
                entry_i = i
    # close any open trade at the last bar
    if cur_side != 0 and entry_i is not None and entry_i < n - 1:
        close_trade(n - 1)

    if not trades:
        return pd.DataFrame(
            {
                "side": pd.Series(dtype="int8"),
                "entry_ts": pd.Series(dtype="int64"),
                "exit_ts": pd.Series(dtype="int64"),
                "entry_price": pd.Series(dtype="float64"),
                "exit_price": pd.Series(dtype="float64"),
                "bars": pd.Series(dtype="int32"),
                "pnl_pct": pd.Series(dtype="float64"),
            }
        )

    out = pd.DataFrame(trades)
    out["side"] = out["side"].astype("int8")
    out["entry_ts"] = out["entry_ts"].astype("int64")
    out["exit_ts"] = out["exit_ts"].astype("int64")
    out["entry_price"] = out["entry_price"].astype("float64")
    out["exit_price"] = out["exit_price"].astype("float64")
    out["bars"] = out["bars"].astype("int32")
    out["pnl_pct"] = out["pnl_pct"].astype("float64")
    return out


def _compute_metrics(equity_df: pd.DataFrame, trades_df: pd.DataFrame, bars_per_year: int) -> dict:
    eq = equity_df["equity"].to_numpy()
    ret = equity_df["ret"].to_numpy()
    n_bars = int(len(eq))

    if n_bars == 0 or eq[0] <= 0:
        total_return = 0.0
        cagr = 0.0
    else:
        total_return = float(eq[-1] / eq[0] - 1.0)
        years = n_bars / bars_per_year
        if years > 0 and (1.0 + total_return) > 0:
            cagr = float((1.0 + total_return) ** (1.0 / years) - 1.0)
        else:
            cagr = 0.0

    if ret.size > 1 and ret.std(ddof=0) > 0:
        sharpe = float(ret.mean() / ret.std(ddof=0) * math.sqrt(bars_per_year))
    else:
        sharpe = 0.0

    if eq.size > 0:
        peak = np.maximum.accumulate(eq)
        dd = eq / peak - 1.0
        mdd = float(dd.min()) if dd.size else 0.0
    else:
        mdd = 0.0

    n_trades = int(len(trades_df))
    if n_trades > 0:
        win_rate = float((trades_df["pnl_pct"] > 0).mean())
        avg_pnl_pct = float(trades_df["pnl_pct"].mean())
        avg_holding_bars = float(trades_df["bars"].mean())
    else:
        win_rate = 0.0
        avg_pnl_pct = 0.0
        avg_holding_bars = 0.0

    return {
        "total_return": float(total_return),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "n_bars": int(n_bars),
        "n_trades": int(n_trades),
        "win_rate": float(win_rate),
        "avg_pnl_pct": float(avg_pnl_pct),
        "avg_holding_bars": float(avg_holding_bars),
    }


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
def execute(
    *,
    strategy: str,
    symbol: str,
    interval: str = "1h",
    start: Optional[str] = None,
    end: Optional[str] = None,
    params: Optional[dict] = None,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    init_capital: float = 10_000.0,
    df: Optional[pd.DataFrame] = None,
    out_root: Optional[Path] = None,
    run_name: Optional[str] = None,
) -> Path:
    """Top-level runner. Loads data (unless ``df`` supplied), runs backtest,
    writes artifacts. Returns the run directory path.
    """
    if interval not in BARS_PER_YEAR:
        raise ValueError(f"interval must be one of {list(BARS_PER_YEAR)}, got {interval}")

    strat = _load_strategy(strategy)
    use_params = dict(strat.DEFAULT_PARAMS)
    if params:
        use_params.update(params)
    # 전략이 주봉 필터 등 심볼 기반 외부 데이터를 쓸 수 있도록 자동 주입
    use_params.setdefault("_symbol", symbol)

    if df is None:
        from data.resample import load as _load
        df = _load(symbol, interval)
    df = df.copy()

    start_ms = _parse_ts(start)
    end_ms = _parse_ts(end)
    df = _slice_df(df, start_ms, end_ms)
    if len(df) < 2:
        raise ValueError("not enough bars after start/end filtering")

    sig = strat.signal(df, use_params)

    equity_df, trades_df, metrics = run_backtest(
        df,
        sig,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        init_capital=init_capital,
        bars_per_year=BARS_PER_YEAR[interval],
    )

    # write artifacts
    root = Path(out_root) if out_root is not None else RUNS_DIR
    root.mkdir(parents=True, exist_ok=True)
    if run_name is None:
        ts_label = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run_name = f"{ts_label}_{strategy}_{symbol}"
    run_dir = root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    cfg = {
        "strategy": strategy,
        "symbol": symbol,
        "interval": interval,
        "start": start,
        "end": end,
        "params": use_params,
        "fee_bps": float(fee_bps),
        "slippage_bps": float(slippage_bps),
        "init_capital": float(init_capital),
    }
    with (run_dir / "config.yaml").open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False, allow_unicode=True)

    equity_df.to_parquet(run_dir / "equity.parquet", index=False)
    trades_df.to_parquet(run_dir / "trades.parquet", index=False)
    with (run_dir / "metrics.json").open("w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2)

    return run_dir


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backtest.engine.runner",
                                description="Run a vectorized crypto backtest.")
    p.add_argument("--strategy", required=True, help="strategy module name under backtest.strategies")
    p.add_argument("--symbol", required=True, help="e.g. BTCUSDT")
    p.add_argument("--interval", default="1h", choices=list(BARS_PER_YEAR.keys()))
    p.add_argument("--start", default=None, help="UTC start (YYYY-MM-DD or ISO)")
    p.add_argument("--end", default=None, help="UTC end (YYYY-MM-DD or ISO)")
    p.add_argument("--params", default="{}", help="JSON dict of strategy params")
    p.add_argument("--fee-bps", type=float, default=5.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument("--init-capital", type=float, default=10_000.0)
    p.add_argument("--out-root", default=None, help="override runs directory (testing)")
    p.add_argument("--run-name", default=None, help="override run dir name (testing)")
    return p


def main(argv: Optional[list] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        params = json.loads(args.params) if args.params else {}
    except json.JSONDecodeError as e:
        raise SystemExit(f"--params is not valid JSON: {e}")

    run_dir = execute(
        strategy=args.strategy,
        symbol=args.symbol,
        interval=args.interval,
        start=args.start,
        end=args.end,
        params=params,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        init_capital=args.init_capital,
        out_root=Path(args.out_root) if args.out_root else None,
        run_name=args.run_name,
    )
    print(str(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
