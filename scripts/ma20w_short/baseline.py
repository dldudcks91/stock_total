"""ma20w_short Layer 0 — baseline.

진입: 주봉 slope_4w(t) < 0  →  t+1 주 시가 숏
청산: 주봉 slope_4w(t) ≥ 0  →  t+1 주 시가

전 553 심볼 루프, 트레이드 단위 short return 집계.
4-group (tier_final) 별 분해.

사용:
    .venv/Scripts/python.exe -m scripts.ma20w_short.baseline \
        --config scripts/ma20w_short/runs/20260518-2140_crypto_baseline/config.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

# UTF-8 stdout (Windows cp949 한글 깨짐 방지)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._common.run_helper import parse_args, update_config, resolve_config_path  # noqa: E402
from scripts.ma20w_short._common import (  # noqa: E402
    load_weekly, add_ma_slope, extract_trades,
    load_classification, summarize_trades,
)


CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"
CLS_PATH = ROOT / "data" / "cache" / "crypto" / "classification.parquet"


def list_symbols() -> list:
    return sorted(p.stem for p in CACHE_DIR.glob("*.parquet"))


def main():
    def add_args(ap):
        ap.add_argument("--ma-window", type=int, default=None)
        ap.add_argument("--slope-window", type=int, default=None)
        ap.add_argument("--fees-bps-roundtrip", type=float, default=None)
        ap.add_argument("--funding-bps-per-week", type=float, default=None)
        ap.add_argument("--min-symbol-weeks", type=int, default=None)
        ap.add_argument("--limit-symbols", type=int, default=None,
                        help="Debug: process only N symbols")

    out_dir, params, args = parse_args(
        add_args,
        defaults={
            "ma_window": 20,
            "slope_window": 4,
            "fees_bps_roundtrip": 15.0,
            "funding_bps_per_week": None,
            "min_symbol_weeks": 30,
        },
        description="ma20w_short Layer 0 baseline: short when MA20w slope_4w < 0",
    )
    ma_window = int(params["ma_window"])
    slope_window = int(params["slope_window"])
    fees = float(params["fees_bps_roundtrip"])
    funding = params.get("funding_bps_per_week")
    funding = float(funding) if funding is not None else None
    min_weeks = int(params["min_symbol_weeks"])

    symbols = list_symbols()
    if args.limit_symbols:
        symbols = symbols[: args.limit_symbols]
    print(f"[baseline] symbols={len(symbols)} ma={ma_window} slope_w={slope_window} "
          f"fees_bps={fees} funding_bps/w={funding}")

    cls_map = load_classification(CLS_PATH).set_index("symbol")["tier_final"].to_dict()

    all_trades = []
    skipped = 0
    for i, sym in enumerate(symbols, 1):
        try:
            w = load_weekly(sym)
        except Exception as e:
            print(f"  [skip] {sym}: load error {e}")
            skipped += 1
            continue
        if len(w) < max(min_weeks, ma_window + slope_window + 2):
            skipped += 1
            continue
        w = add_ma_slope(w, ma_window=ma_window, slope_window=slope_window)
        tr = extract_trades(w, fees_bps_roundtrip=fees, funding_bps_per_week=funding)
        if tr.empty:
            continue
        tr.insert(0, "symbol", sym)
        tr["tier"] = cls_map.get(sym, "unknown")
        all_trades.append(tr)
        if i % 50 == 0:
            print(f"  ...{i}/{len(symbols)}  trades={sum(len(t) for t in all_trades)}")

    if not all_trades:
        print("[baseline] no trades — abort")
        return
    trades = pd.concat(all_trades, ignore_index=True)
    print(f"[baseline] total trades={len(trades)} skipped_symbols={skipped}")

    # 미청산(오픈) vs 청산 트레이드 분리: hold_weeks==0 또는 exit_idx == last index 식별은 표본 외 → flag
    # 단순화: exit_dt == last bar 인 경우만 open 으로 가정. 여기서는 모두 포함하되 별도 컬럼으로 표기 가능.
    # (현 구현에선 마지막 미청산도 포함 — Layer 0 분포 확인이 목적)

    # 저장
    trades_path = out_dir / "trades.parquet"
    trades.to_parquet(trades_path, index=False)
    print(f"[baseline] wrote {trades_path.relative_to(ROOT)}  ({len(trades)} rows)")

    # 전체 summary
    overall = summarize_trades(trades)
    overall["n_symbols"] = int(trades["symbol"].nunique())

    # tier 별 summary
    by_tier_rows = []
    for tier, g in trades.groupby("tier"):
        s = summarize_trades(g)
        s["tier"] = tier
        s["n_symbols"] = int(g["symbol"].nunique())
        by_tier_rows.append(s)
    by_tier = pd.DataFrame(by_tier_rows).set_index("tier").sort_index()
    by_tier_path = out_dir / "summary_by_tier.csv"
    by_tier.to_csv(by_tier_path)
    print(f"[baseline] wrote {by_tier_path.relative_to(ROOT)}")

    # 전체 summary JSON
    summary = {
        "overall": overall,
        "by_tier": by_tier.reset_index().to_dict(orient="records"),
        "params": {
            "ma_window": ma_window,
            "slope_window": slope_window,
            "fees_bps_roundtrip": fees,
            "funding_bps_per_week": funding,
            "min_symbol_weeks": min_weeks,
        },
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str),
                            encoding="utf-8")
    print(f"[baseline] wrote {summary_path.relative_to(ROOT)}")

    # 콘솔 표
    print("\n=== Overall ===")
    for k in ("n_trades", "n_symbols", "mean", "median", "std", "win_rate",
              "payoff", "var95", "var99", "max_loss", "max_gain",
              "var_adj_expectancy", "avg_hold_weeks", "total_pnl"):
        v = overall.get(k)
        if isinstance(v, float):
            print(f"  {k:22s} {v:+.4f}")
        else:
            print(f"  {k:22s} {v}")

    print("\n=== By tier ===")
    cols = ["n_trades", "n_symbols", "mean", "win_rate", "payoff", "var95",
            "var_adj_expectancy", "avg_hold_weeks"]
    fmt = by_tier[cols].copy()
    for c in ("mean", "win_rate", "payoff", "var95", "var_adj_expectancy"):
        fmt[c] = fmt[c].map(lambda x: f"{x:+.4f}" if pd.notna(x) else "—")
    fmt["avg_hold_weeks"] = fmt["avg_hold_weeks"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "—")
    print(fmt.to_string())

    # config.json 업데이트
    cfg_path = resolve_config_path(args)
    if cfg_path:
        # JSON 호환성을 위해 NaN/inf 제거
        def _clean(d):
            from math import isnan, isinf
            out = {}
            for k, v in d.items():
                if isinstance(v, float):
                    if isnan(v) or isinf(v):
                        out[k] = None
                        continue
                out[k] = v
            return out
        update_config(
            cfg_path,
            data={"symbol_count_processed": int(trades["symbol"].nunique()),
                  "symbols_skipped": skipped},
            results_summary={
                "n_trades": overall["n_trades"],
                "mean_short_return": overall["mean"],
                "median_short_return": overall["median"],
                "win_rate": overall["win_rate"],
                "payoff": overall["payoff"],
                "var95": overall["var95"],
                "var_adj_expectancy": overall["var_adj_expectancy"],
                "avg_hold_weeks": overall["avg_hold_weeks"],
                "total_pnl": overall["total_pnl"],
                "by_tier_mean": {r["tier"]: r["mean"] for r in summary["by_tier"]},
                "by_tier_win_rate": {r["tier"]: r["win_rate"] for r in summary["by_tier"]},
                "by_tier_n_trades": {r["tier"]: r["n_trades"] for r in summary["by_tier"]},
            },
        )
        print(f"\n[baseline] updated {cfg_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
