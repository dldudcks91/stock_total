"""ma_slope_turn_up 진입 시점들에 대해 청산룰 그리드 백테스트.

진입은 strategy.signal()의 0→1 전환 사용. 청산은 simulator에서 룰 조합으로 결정:
  - max_hold      : 최대 보유 주
  - trailing_pct  : peak 대비 x% 빠지면 청산 (peak는 진입 후 최고 close)
  - take_profit_pct : 진입가 대비 +x% 도달 시 청산
  - cut_1w_neg    : +1w 음수면 즉시 청산
  - cut_2w_below  : +2w 후 +x% 미달이면 청산
  - slope_exit    : slope_fast<0 OR slope_slow<0 시 청산 (전략 기본)

자산별 청산 그리드 매트릭스 비교 → 최적 룰 도출.

per-trade PnL (수수료/슬리피지 차감) 집계:
  - n_trades, win%, mean ret, median ret, total ret (compound), Sharpe, MDD (per-trade 곡선)
"""
from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.strategies import ma_slope_turn_up  # noqa: E402
from scripts.count_slope_turn_signals import (  # noqa: E402
    load_crypto_weekly, load_stock_weekly, crypto_symbol_from_file,
    CRYPTO_DIR, CRYPTO_1H_DIR, KR_DIR, US_DIR, SINCE, SINCE_YEARS,
)
from scripts.forward_returns_top200 import (  # noqa: E402
    kr_top_universe, us_top_universe, crypto_top_universe,
)

OUT_DIR = ROOT / "scripts" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 수수료 + 슬리피지 (왕복) — 보수적
COST_RT = {"crypto": 0.002, "kr": 0.003, "us": 0.002}


@dataclass
class ExitRule:
    name: str
    max_hold: int = 0              # 0 = no limit
    trailing_pct: float = 0.0      # 0 = off, 0.15 = 15% from peak
    take_profit_pct: float = 0.0   # 0 = off, 0.30 = +30% from entry
    cut_1w_neg: bool = False       # +1w close < entry -> exit
    cut_2w_thr: float = -999       # +2w return < thr -> exit (thr 단위: %, -999=off)
    slope_exit: bool = True        # use strategy's slope-flip exit


def simulate(close: np.ndarray, low: np.ndarray, entry_pos: int,
             slope_neg: np.ndarray, rule: ExitRule) -> tuple[int, float]:
    """진입 위치 entry_pos부터 청산 위치/수익률 반환. low는 trailing/stop 검토용 (사용 안 함, close 기준)."""
    n = len(close)
    ec = close[entry_pos]
    peak = ec
    held = 0
    for i in range(entry_pos + 1, n):
        held = i - entry_pos
        ci = close[i]
        peak = max(peak, ci)
        ret = ci / ec - 1.0

        # 1) take profit
        if rule.take_profit_pct > 0 and ret >= rule.take_profit_pct:
            return i, ret
        # 2) trailing from peak
        if rule.trailing_pct > 0 and peak > ec:
            if ci / peak - 1.0 <= -rule.trailing_pct:
                return i, ret
        # 3) +1w 음수 컷
        if rule.cut_1w_neg and held == 1 and ret < 0:
            return i, ret
        # 4) +2w threshold
        if rule.cut_2w_thr > -100 and held == 2 and ret * 100 < rule.cut_2w_thr:
            return i, ret
        # 5) slope flip
        if rule.slope_exit and slope_neg[i]:
            return i, ret
        # 6) max_hold
        if rule.max_hold > 0 and held >= rule.max_hold:
            return i, ret
    # 마지막까지 보유
    last = n - 1
    return last, close[last] / ec - 1.0


def collect_trades(asset: str, files, loader, universe: set[str],
                   rule: ExitRule, cost_rt: float) -> list[dict]:
    trades = []
    for p in files:
        symbol = crypto_symbol_from_file(p) if asset == "crypto" else p.stem
        if symbol not in universe:
            continue
        try:
            df_w = loader(p)
            if df_w is None or df_w.empty or len(df_w) < 120:
                continue
            sig = ma_slope_turn_up.signal(df_w.reset_index(drop=True), {})
            sig.index = df_w.index
            entries = (sig.diff() == 1) & (df_w.index >= SINCE)
            close = df_w["close"].to_numpy()
            low = df_w["low"].to_numpy() if "low" in df_w.columns else close
            # slope_neg 시계열 (전략 청산 신호용)
            ma_f = pd.Series(close).rolling(10).mean()
            ma_s = pd.Series(close).rolling(20).mean()
            slope_neg = ((ma_f.diff() < 0) | (ma_s.diff() < 0)).to_numpy()

            for pos in np.where(entries.to_numpy())[0]:
                exit_pos, gross_ret = simulate(close, low, pos, slope_neg, rule)
                net_ret = gross_ret - cost_rt
                trades.append({
                    "asset": asset,
                    "symbol": symbol,
                    "entry_dt": df_w.index[pos].date().isoformat(),
                    "exit_dt": df_w.index[exit_pos].date().isoformat(),
                    "held_weeks": exit_pos - pos,
                    "gross_ret_%": gross_ret * 100,
                    "net_ret_%": net_ret * 100,
                })
        except Exception:
            continue
    return trades


def summarize(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    df = pd.DataFrame(trades)
    rets = df["net_ret_%"].to_numpy() / 100.0
    win = (rets > 0).mean() * 100
    mean = rets.mean() * 100
    median = np.median(rets) * 100
    held = df["held_weeks"].mean()
    # 누적 (균등 비중)
    eq = np.cumprod(1.0 + rets)
    total = (eq[-1] - 1.0) * 100
    # MDD on equity
    peak = np.maximum.accumulate(eq)
    dd = (eq / peak - 1.0).min() * 100
    # Sharpe-like (per-trade, 연환산 위해 sqrt(trades/year) ≈ trades/3 (3년 데이터))
    if rets.std() > 0:
        sharpe_per_trade = rets.mean() / rets.std()
        # 연환산: 시그널/년 ≈ n/SINCE_YEARS
        annual_factor = np.sqrt(max(1, len(rets)) / float(SINCE_YEARS))
        sharpe_ann = sharpe_per_trade * annual_factor
    else:
        sharpe_ann = 0.0
    # profit factor
    gains = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = gains / losses if losses > 0 else float("inf")
    return {
        "n": len(rets), "win%": win, "mean%": mean, "median%": median,
        "held_w": held, "total%": total, "MDD%": dd,
        "Sharpe_ann": sharpe_ann, "PF": pf,
    }


def main():
    kr_uni = kr_top_universe()
    us_uni = us_top_universe()
    cr_uni = crypto_top_universe()

    kr_files = [p for p in sorted(KR_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    us_files = [p for p in sorted(US_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    cr_files = sorted(CRYPTO_1H_DIR.glob("*.parquet"))

    # 청산 룰 그리드 — 자산별로 의미있는 조합
    crypto_rules = [
        ExitRule("baseline_slope",         slope_exit=True),
        ExitRule("hold_8w_slope",          max_hold=8, slope_exit=True),
        ExitRule("hold_8w_trail15",        max_hold=8, trailing_pct=0.15, slope_exit=False),
        ExitRule("hold_8w_trail20",        max_hold=8, trailing_pct=0.20, slope_exit=False),
        ExitRule("hold_8w_trail15_cut1",   max_hold=8, trailing_pct=0.15, cut_1w_neg=True, slope_exit=False),
        ExitRule("hold_13w_trail15_cut1",  max_hold=13, trailing_pct=0.15, cut_1w_neg=True, slope_exit=False),
        ExitRule("hold_8w_TP30_trail15",   max_hold=8, trailing_pct=0.15, take_profit_pct=0.30, slope_exit=False),
        ExitRule("hold_8w_cut2_minus5",    max_hold=8, cut_2w_thr=-5, slope_exit=True),
    ]
    stock_rules = [
        ExitRule("baseline_slope",         slope_exit=True),
        ExitRule("hold_26w_slope",         max_hold=26, slope_exit=True),
        ExitRule("hold_52w_slope",         max_hold=52, slope_exit=True),
        ExitRule("hold_52w_trail20",       max_hold=52, trailing_pct=0.20, slope_exit=False),
        ExitRule("hold_52w_trail15",       max_hold=52, trailing_pct=0.15, slope_exit=False),
        ExitRule("hold_52w_trail25",       max_hold=52, trailing_pct=0.25, slope_exit=False),
        ExitRule("hold_26w_trail15",       max_hold=26, trailing_pct=0.15, slope_exit=False),
        ExitRule("hold_52w_TP30_trail20",  max_hold=52, trailing_pct=0.20, take_profit_pct=0.30, slope_exit=False),
    ]

    all_summaries = []
    for asset, files, loader, uni, rules in [
        ("crypto", cr_files, load_crypto_weekly, cr_uni, crypto_rules),
        ("kr",     kr_files, load_stock_weekly,  kr_uni, stock_rules),
        ("us",     us_files, load_stock_weekly,  us_uni, stock_rules),
    ]:
        print(f"\n=== {asset.upper()} (universe={len(uni)}) ===")
        print(f"{'rule':<26s} {'n':>3s} {'win%':>5s} {'mean%':>6s} {'med%':>6s} {'held':>5s} {'total%':>8s} {'MDD%':>7s} {'Sharpe':>7s} {'PF':>5s}")
        for r in rules:
            trades = collect_trades(asset, files, loader, uni, r, COST_RT[asset])
            s = summarize(trades)
            all_summaries.append({"asset": asset, "rule": r.name, **s, **asdict(r)})
            if s["n"] == 0:
                print(f"{r.name:<26s} 0 trades")
                continue
            print(f"{r.name:<26s} {s['n']:>3d} {s['win%']:>4.1f}% {s['mean%']:>+6.1f} {s['median%']:>+6.1f} "
                  f"{s['held_w']:>5.1f} {s['total%']:>+8.1f} {s['MDD%']:>+7.1f} {s['Sharpe_ann']:>+7.2f} {s['PF']:>5.2f}")

    pd.DataFrame(all_summaries).to_csv(OUT_DIR / "exit_grid_summary.csv", index=False, encoding="utf-8-sig")
    print(f"\nsaved: {OUT_DIR / 'exit_grid_summary.csv'}")


if __name__ == "__main__":
    main()
