"""5-전략 × 다중 인터벌 × 분류 그룹 백테스트 매트릭스.

각 셀(전략, 인터벌, 그룹, 심볼) 마다 백테스트 실행 후
backtest/runs/matrix_<ts>/<strategy>__<interval>__<group>__<symbol>/ 로 저장.

사용:
    python -m scripts.run_matrix --start 2023-01-01 --end 2025-12-31 --min-obs 0
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backtest.engine.runner import RUNS_DIR, execute
from data.universe import sample_group

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger("matrix")

# Strategy → list of (interval, fee_bps, slippage_bps)
# Plus target groups per strategy.
STRATEGIES = {
    "trend_follow": {
        "intervals": [("1h", 5.0, 5.0), ("4h", 5.0, 5.0), ("1d", 5.0, 5.0)],
        "groups": ["trend", "follower", "whale", "junk"],
    },
    "breakout_start": {
        "intervals": [("1h", 5.0, 5.0), ("4h", 5.0, 5.0), ("1d", 5.0, 5.0)],
        "groups": ["trend", "follower", "whale", "junk"],
    },
    "rsi_pullback": {
        "intervals": [("1h", 5.0, 5.0), ("4h", 5.0, 5.0), ("1d", 5.0, 5.0)],
        "groups": ["trend", "follower", "whale", "junk"],
    },
    "momentum_roc": {
        "intervals": [("1h", 5.0, 5.0), ("4h", 5.0, 5.0), ("1d", 5.0, 5.0)],
        "groups": ["trend", "follower", "whale", "junk"],
    },
    "bb_squeeze": {
        "intervals": [("1h", 5.0, 5.0), ("4h", 5.0, 5.0), ("1d", 5.0, 5.0)],
        "groups": ["trend", "follower", "whale", "junk"],
    },
}

CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache" / "crypto" / "1h"


def _has_cache(symbol: str) -> bool:
    return (CACHE_DIR / f"{symbol}.parquet").exists()


def run_matrix(
    start: str,
    end: str,
    limit: int | None = None,
    min_obs: int = 0,
    out_root: Path | None = None,
) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    matrix_dir = (out_root or RUNS_DIR) / f"matrix_{ts}"
    matrix_dir.mkdir(parents=True, exist_ok=True)
    log.info("matrix dir: %s", matrix_dir)

    rows: list[dict] = []
    err_count = 0

    for strat, cfg in STRATEGIES.items():
        for interval, fee, slip in cfg["intervals"]:
            for group in cfg["groups"]:
                symbols = sample_group(group, limit=limit, min_obs=min_obs)
                symbols = [s for s in symbols if _has_cache(s)]
                log.info("%s/%s/%s: %d symbols", strat, interval, group, len(symbols))

                for sym in symbols:
                    run_name = f"{strat}__{interval}__{group}__{sym}"
                    run_dir = matrix_dir / run_name
                    try:
                        execute(
                            strategy=strat,
                            symbol=sym,
                            interval=interval,
                            start=start,
                            end=end,
                            params=None,
                            fee_bps=fee,
                            slippage_bps=slip,
                            init_capital=10_000.0,
                            out_root=matrix_dir,
                            run_name=run_name,
                        )
                        with (run_dir / "metrics.json").open("r", encoding="utf-8") as fh:
                            m = json.load(fh)
                        rows.append({
                            "strategy": strat, "interval": interval, "group": group, "symbol": sym,
                            **m, "status": "ok",
                        })
                    except Exception as exc:  # noqa: BLE001
                        err_count += 1
                        rows.append({
                            "strategy": strat, "interval": interval, "group": group, "symbol": sym,
                            "status": f"error: {type(exc).__name__}",
                        })

    summary = pd.DataFrame(rows)
    summary.to_csv(matrix_dir / "_summary.csv", index=False)
    log.info("summary written: %d rows, %d errors", len(summary), err_count)

    ok = summary[summary["status"] == "ok"].copy()
    if len(ok):
        agg = ok.groupby(["strategy", "interval", "group"]).agg(
            n=("symbol", "count"),
            mean_total_return=("total_return", "mean"),
            median_total_return=("total_return", "median"),
            mean_sharpe=("sharpe", "mean"),
            median_sharpe=("sharpe", "median"),
            mean_mdd=("mdd", "mean"),
            mean_winrate=("win_rate", "mean"),
            mean_trades=("n_trades", "mean"),
        ).round(4).reset_index()
        agg.to_csv(matrix_dir / "_aggregate.csv", index=False)
        log.info("aggregate written: %s", matrix_dir / "_aggregate.csv")

    return matrix_dir


def _build_parser():
    p = argparse.ArgumentParser(prog="run_matrix")
    p.add_argument("--start", default="2023-01-01")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--limit", type=int, default=None, help="cap symbols per group (None=all)")
    p.add_argument("--min-obs", type=int, default=0, help="min observation days per symbol")
    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)
    matrix_dir = run_matrix(args.start, args.end, args.limit, args.min_obs)
    print(matrix_dir)


if __name__ == "__main__":
    main()
