"""여러 심볼에 대해 동일 전략 일괄 백테스트 + 그룹별 집계.

CLI:
    python -m backtest.batch_runner --strategy weekly_trend --interval 1w \
        --tier trend --top-n 30 --start 2023-01-01 --end 2025-12-31

산출:
    backtest/runs/_batch_{ts}_{strategy}/
        summary.parquet  — 심볼별 메트릭 + tier
        per_tier.csv     — tier별 집계 표
        run_dirs.txt     — 개별 런 디렉터리 목록
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backtest.engine.runner import execute as run_one

ROOT = Path(__file__).resolve().parent.parent
CLASSIFICATION_PATH = ROOT / "data" / "cache" / "classification.parquet"
RUNS_DIR = ROOT / "backtest" / "runs"


def _load_classification() -> pd.DataFrame:
    if not CLASSIFICATION_PATH.exists():
        raise FileNotFoundError(
            f"{CLASSIFICATION_PATH} not found. /classify-coins 먼저 실행."
        )
    return pd.read_parquet(CLASSIFICATION_PATH)


def select_universe(
    tiers: list[str] | None = None,
    exclude_tiers: list[str] | None = None,
    top_n_per_tier: int | None = None,
    explicit_symbols: list[str] | None = None,
) -> pd.DataFrame:
    """분류 결과 기반 유니버스 선택. 컬럼: symbol, tier_final, volume_score_3y."""
    if explicit_symbols:
        df = _load_classification()
        return df[df["symbol"].isin(explicit_symbols)][
            ["symbol", "tier_final", "volume_score_3y"]
        ].reset_index(drop=True)

    df = _load_classification()
    if tiers:
        df = df[df["tier_final"].isin(tiers)]
    if exclude_tiers:
        df = df[~df["tier_final"].isin(exclude_tiers)]
    df = df.sort_values(["tier_final", "volume_score_3y"], ascending=[True, False])

    if top_n_per_tier:
        df = df.groupby("tier_final", group_keys=False).head(top_n_per_tier)

    return df[["symbol", "tier_final", "volume_score_3y"]].reset_index(drop=True)


def batch_run(
    strategy: str,
    universe: pd.DataFrame,
    interval: str = "1w",
    start: str | None = None,
    end: str | None = None,
    params: dict | None = None,
    fee_bps: float = 4.0,
    slippage_bps: float = 1.0,
    init_capital: float = 10_000.0,
    batch_id: str | None = None,
    verbose: bool = True,
) -> tuple[pd.DataFrame, Path]:
    """universe 각 심볼에 strategy 실행, summary 반환."""
    if batch_id is None:
        batch_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = RUNS_DIR / f"_batch_{batch_id}_{strategy}"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    run_dirs: list[str] = []
    for i, ur in enumerate(universe.itertuples(), 1):
        sym = ur.symbol
        tier = ur.tier_final
        try:
            run_dir = run_one(
                strategy=strategy,
                symbol=sym,
                interval=interval,
                start=start,
                end=end,
                params=params,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                init_capital=init_capital,
            )
            with open(run_dir / "metrics.json") as f:
                m = json.load(f)
            row = {"symbol": sym, "tier": tier, **m, "run_dir": str(run_dir)}
            rows.append(row)
            run_dirs.append(str(run_dir))
            if verbose:
                tr = m.get("total_return", 0)
                sh = m.get("sharpe", 0)
                nt = m.get("n_trades", 0)
                print(
                    f"[{i:>3}/{len(universe)}] {tier:<10} {sym:<22} "
                    f"return={tr:+7.2%}  sharpe={sh:+5.2f}  trades={nt:>3}"
                )
        except Exception as e:
            if verbose:
                print(f"[{i:>3}/{len(universe)}] {tier:<10} {sym:<22} ERROR: {e}", file=sys.stderr)

    if not rows:
        raise RuntimeError("No runs produced. 캐시 부족 또는 데이터 범위 오류.")

    summary = pd.DataFrame(rows)
    summary.to_parquet(out_dir / "summary.parquet", index=False)
    (out_dir / "run_dirs.txt").write_text("\n".join(run_dirs))

    # Per-tier aggregation
    per_tier = aggregate_by_tier(summary)
    per_tier.to_csv(out_dir / "per_tier.csv", index=False)

    return summary, out_dir


def aggregate_by_tier(summary: pd.DataFrame) -> pd.DataFrame:
    """tier별 메트릭 집계: 평균/중앙값/분포."""
    agg = summary.groupby("tier").agg(
        n_coins=("symbol", "count"),
        total_return_median=("total_return", "median"),
        total_return_mean=("total_return", "mean"),
        sharpe_median=("sharpe", "median"),
        sharpe_mean=("sharpe", "mean"),
        mdd_median=("mdd", "median"),
        win_rate_median=("win_rate", "median"),
        n_trades_median=("n_trades", "median"),
        positive_returns_pct=("total_return", lambda s: (s > 0).mean()),
    ).reset_index()
    return agg


# ---------------------------------------------------------------------------
def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="여러 심볼 일괄 백테스트")
    p.add_argument("--strategy", required=True)
    p.add_argument("--interval", default="1w")
    p.add_argument("--start", default="2023-01-01")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--tier", action="append", help="포함할 tier_final (반복 가능)")
    p.add_argument("--exclude-tier", action="append", help="제외할 tier_final")
    p.add_argument("--top-n", type=int, help="tier별 거래량 상위 N")
    p.add_argument("--symbol", action="append", help="명시 심볼 (반복). 지정 시 tier 무시")
    p.add_argument("--params", help='JSON. 예: \'{"ma_window":20}\'')
    p.add_argument("--fee-bps", type=float, default=4.0)
    p.add_argument("--slippage-bps", type=float, default=1.0)
    p.add_argument("--init-capital", type=float, default=10000.0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    universe = select_universe(
        tiers=args.tier,
        exclude_tiers=args.exclude_tier,
        top_n_per_tier=args.top_n,
        explicit_symbols=args.symbol,
    )
    if universe.empty:
        print("[error] 빈 유니버스. --tier / --top-n / --symbol 확인.", file=sys.stderr)
        return 2

    print(f"Universe: {len(universe)} symbols ({universe['tier_final'].value_counts().to_dict()})")
    print()

    params = json.loads(args.params) if args.params else None
    summary, out_dir = batch_run(
        strategy=args.strategy,
        universe=universe,
        interval=args.interval,
        start=args.start,
        end=args.end,
        params=params,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        init_capital=args.init_capital,
    )

    print()
    print(f"=== batch saved: {out_dir} ===")
    print()
    print("=== per-tier aggregation ===")
    per_tier = aggregate_by_tier(summary)
    print(per_tier.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
