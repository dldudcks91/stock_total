"""quiet_bottom 검증 — KR/US Sharpe 5.84 / 3.56이 진짜인지.

4가지 검증:
  1) 시기별 분할 — 2020-22 / 2023-24 / 2025-26 각각 Sharpe
  2) Outlier 제거 — Top 5% PnL 제외 후 통계
  3) 종목 분할 — 홀짝 그룹 cross-validation
  4) IS/OOS — train 2020-23 / test 2024-26
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import quiet_bottom  # noqa: E402
from scripts.quiet_bottom.exit_rule_grid import ExitRule, simulate  # noqa: E402
from scripts.quiet_bottom.count_slope_turn_signals import (  # noqa: E402
    load_stock_weekly, KR_DIR, US_DIR,
)
from scripts.quiet_bottom.forward_returns_top200 import (kr_top_universe, us_top_universe)  # noqa: E402

SINCE_YEARS = 6
SINCE = pd.Timestamp.utcnow().tz_localize(None).normalize() - pd.DateOffset(years=SINCE_YEARS)
COST_RT_KR = 0.003
COST_RT_US = 0.002

PARAMS = {  # default
    "ma_fast": 10, "ma_slow": 20, "dd_lookback_104w": 104, "path_window_52w": 52,
    "recent_window_4w": 4, "dd_avg_max": -0.45, "path_r2_max": 0.50, "recent_ret_max": 0.60,
}
RULE = ExitRule("hold_52w_TP30_trail20", max_hold=52, trailing_pct=0.20,
                take_profit_pct=0.30, slope_exit=False)


def collect_trades(files, universe, cost_rt):
    trades = []
    for p in files:
        sym = p.stem
        if sym not in universe:
            continue
        try:
            df_w = load_stock_weekly(p)
            if df_w is None or df_w.empty or len(df_w) < 120:
                continue
            sig = quiet_bottom.signal(df_w.reset_index(drop=True), PARAMS)
            sig.index = df_w.index
            entries = (sig.diff() == 1) & (df_w.index >= SINCE)
            close = df_w["close"].to_numpy()
            low = df_w["low"].to_numpy() if "low" in df_w.columns else close
            ma_f = pd.Series(close).rolling(10).mean()
            ma_s = pd.Series(close).rolling(20).mean()
            slope_neg = ((ma_f.diff() < 0) | (ma_s.diff() < 0)).to_numpy()
            for pos in np.where(entries.to_numpy())[0]:
                ep, gr = simulate(close, low, pos, slope_neg, RULE)
                trades.append({
                    "symbol": sym,
                    "entry_dt": df_w.index[pos],
                    "exit_dt": df_w.index[ep],
                    "held_w": ep - pos,
                    "net_ret_%": (gr - cost_rt) * 100,
                })
        except Exception:
            continue
    return pd.DataFrame(trades)


def stats(df: pd.DataFrame, years: float):
    if df is None or df.empty:
        return {"n": 0}
    rets = df["net_ret_%"].to_numpy() / 100.0
    eq = np.cumprod(1.0 + rets)
    peak = np.maximum.accumulate(eq)
    dd = (eq / peak - 1).min() * 100
    if rets.std() > 0:
        ann = np.sqrt(max(1, len(rets)) / years)
        sharpe = rets.mean() / rets.std() * ann
    else:
        sharpe = 0.0
    gains = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = gains / losses if losses > 0 else float("inf")
    return {
        "n": len(rets),
        "win%": (rets > 0).mean() * 100,
        "mean%": rets.mean() * 100,
        "median%": np.median(rets) * 100,
        "Sharpe": sharpe, "PF": pf, "MDD%": dd,
        "total%": (eq[-1] - 1) * 100,
    }


def print_stats(s, label):
    if s["n"] == 0:
        print(f"  {label}: 0 trades"); return
    print(f"  {label:<32s} n={s['n']:>4d}  win={s['win%']:>4.1f}%  mean={s['mean%']:>+5.1f}%  "
          f"med={s['median%']:>+5.1f}%  Sharpe={s['Sharpe']:>+5.2f}  PF={s['PF']:>5.2f}  MDD={s['MDD%']:>+6.1f}%")


def main():
    print(f"quiet_bottom validation — 6y data (since {SINCE.date()})\n")
    kr_uni = kr_top_universe()
    us_uni = us_top_universe()
    kr_files = [p for p in sorted(KR_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    us_files = [p for p in sorted(US_DIR.glob("*.parquet")) if not p.stem.startswith("_")]

    for name, files, uni, cost in [("KR", kr_files, kr_uni, COST_RT_KR),
                                    ("US", us_files, us_uni, COST_RT_US)]:
        print(f"\n=== {name} ===")
        df = collect_trades(files, uni, cost)
        print_stats(stats(df, SINCE_YEARS), "baseline (full 6y)")

        if df.empty:
            continue

        # 1) 시기별 분할 — 진입일 기준
        print(f"\n  --- (1) Time periods (by entry date) ---")
        periods = [
            ("2020-2022 (3y)", "2020-01-01", "2022-12-31", 3),
            ("2023-2024 (2y)", "2023-01-01", "2024-12-31", 2),
            ("2025-2026 (1.5y)", "2025-01-01", "2026-12-31", 1.5),
        ]
        for plabel, start, end, yrs in periods:
            sub = df[(df["entry_dt"] >= start) & (df["entry_dt"] <= end)]
            print_stats(stats(sub, yrs), plabel)

        # 2) Outlier 제거
        print(f"\n  --- (2) Outlier impact (PnL trimmed) ---")
        sorted_rets = df["net_ret_%"].sort_values(ascending=False)
        top1 = int(len(df) * 0.01)
        top5 = int(len(df) * 0.05)
        df_trim1 = df.drop(sorted_rets.head(top1).index)
        df_trim5 = df.drop(sorted_rets.head(top5).index)
        df_trim_both5 = df.drop(sorted_rets.head(top5).index).drop(sorted_rets.tail(top5).index)
        print_stats(stats(df_trim1, SINCE_YEARS), f"top 1% removed (n_removed={top1})")
        print_stats(stats(df_trim5, SINCE_YEARS), f"top 5% removed (n_removed={top5})")
        print_stats(stats(df_trim_both5, SINCE_YEARS), f"top 5% & bot 5% removed")

        # 3) 종목 분할 — 홀짝
        print(f"\n  --- (3) Symbol split (cross-validation) ---")
        syms = sorted(df["symbol"].unique())
        odd = [s for i, s in enumerate(syms) if i % 2 == 0]
        even = [s for i, s in enumerate(syms) if i % 2 == 1]
        df_odd = df[df["symbol"].isin(odd)]
        df_even = df[df["symbol"].isin(even)]
        print_stats(stats(df_odd, SINCE_YEARS), f"group A ({len(odd)} syms)")
        print_stats(stats(df_even, SINCE_YEARS), f"group B ({len(even)} syms)")

        # 4) IS/OOS
        print(f"\n  --- (4) IS/OOS (Train vs Test) ---")
        df_train = df[df["entry_dt"] < "2024-01-01"]
        df_test = df[df["entry_dt"] >= "2024-01-01"]
        train_years = 4
        test_years = 2.5
        print_stats(stats(df_train, train_years), "Train (2020-2023)")
        print_stats(stats(df_test, test_years), "Test (2024-2026)")


if __name__ == "__main__":
    main()
