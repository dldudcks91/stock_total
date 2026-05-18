"""Round 2 — Crypto 1h grid (trend_chase + trend_pullback).

Round 1 에서 4h 가 Sharpe ~0.62 / -0.31 로 무용이었음. 1h 도 비슷할 가능성이
높지만 BTC 같은 대형주는 다를 수 있어 별도 검증.

- Universe: top 100 by 24h amount 평균 (메모리 보호)
- 그리드: th {60,70,75,80,85,90} × rules ~6개 × strategy 2개
- 청산룰: hold_24h/72h/168h/336h × trail_10/15/20 × TP_20/30/None 중 6개

산출:
  scripts/out/optimize/round2/crypto/task1_1h_grid.csv  (전체)
  scripts/out/optimize/round2/crypto/task1_1h_best.csv  (그룹별 best)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import trend_chase, trend_pullback  # noqa: E402
from scripts.optimize_grid import ExitRule, simulate, summarize_trades, COST_RT  # noqa: E402

CACHE_1H = ROOT / "data" / "cache" / "crypto" / "1h"
OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "round2" / "crypto"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TOP_N = 100
MIN_BARS_1H = 24 * 30 * 6  # 6 개월
SCORE_GRID = [60, 70, 75, 80, 85, 90]

# 6 청산 규칙 (간략)
EXIT_RULES_1H = [
    ExitRule("hold_24h_trail10",            max_hold=24,  trailing_pct=0.10),
    ExitRule("hold_72h_trail10_TP20",       max_hold=72,  trailing_pct=0.10, take_profit_pct=0.20),
    ExitRule("hold_168h_trail15_TP30",      max_hold=168, trailing_pct=0.15, take_profit_pct=0.30),
    ExitRule("hold_168h_trail20",           max_hold=168, trailing_pct=0.20),
    ExitRule("hold_336h_trail15_TP30",      max_hold=336, trailing_pct=0.15, take_profit_pct=0.30),
    ExitRule("hold_336h_trail20_cut5h",     max_hold=336, trailing_pct=0.20,
             cut_short_at=5, cut_short_thr=-3),
]

STRATEGIES = {"trend_chase": trend_chase, "trend_pullback": trend_pullback}

NOW = pd.Timestamp.utcnow().tz_localize(None).normalize()
SINCE = NOW - pd.DateOffset(years=3)  # 1h 라 3년만 (메모리)
SINCE_YEARS = 3
COST = COST_RT["crypto"]


def select_universe(top_n: int) -> list[Path]:
    """24h amount 평균이 큰 top_n. amount 컬럼 read-only로 빠르게."""
    print(f"[universe] scanning amount in {CACHE_1H}", flush=True)
    scores: list[tuple[Path, float]] = []
    t0 = time.time()
    files = sorted(CACHE_1H.glob("*.parquet"))
    for i, p in enumerate(files):
        try:
            amt = pd.read_parquet(p, columns=["amount"])["amount"]
            if len(amt) == 0:
                continue
            scores.append((p, float(amt.tail(24 * 90).mean())))  # 최근 90일 평균 (시간당)
        except Exception:
            continue
        if (i + 1) % 100 == 0:
            print(f"  scanned {i+1}/{len(files)}", flush=True)
    scores.sort(key=lambda x: x[1], reverse=True)
    sel = [p for p, _ in scores[:top_n]]
    print(f"[universe] selected {len(sel)} (scan {time.time()-t0:.1f}s)", flush=True)
    return sel


def load_1h(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if "timestamp" not in df.columns:
        return pd.DataFrame()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df = df.set_index("dt").sort_index()
    cols = ["open", "high", "low", "close", "volume"]
    if "amount" in df.columns:
        cols.append("amount")
    return df[cols]


def summarize_with_years(trades: list[dict], years: float) -> dict:
    """summarize_trades 와 동일하나 annualization 을 외부에서 제공."""
    if not trades:
        return {"n": 0, "win%": 0, "mean%": 0, "median%": 0, "held": 0,
                "total%": 0, "MDD%": 0, "Sharpe_ann": 0, "PF": 0}
    df = pd.DataFrame(trades)
    rets = df["net_ret"].to_numpy()
    win = float((rets > 0).mean() * 100)
    mean = float(rets.mean() * 100)
    median = float(np.median(rets) * 100)
    held = float(df["held"].mean())
    eq = np.cumprod(1.0 + rets)
    total = float((eq[-1] - 1.0) * 100)
    peak = np.maximum.accumulate(eq)
    dd = float((eq / peak - 1.0).min() * 100)
    if rets.std() > 0:
        sharpe_pt = rets.mean() / rets.std()
        sharpe_ann = float(sharpe_pt * np.sqrt(max(1, len(rets)) / years))
    else:
        sharpe_ann = 0.0
    gains = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = float(gains / losses) if losses > 0 else 99.99
    return {
        "n": int(len(rets)), "win%": round(win, 1),
        "mean%": round(mean, 2), "median%": round(median, 2),
        "held": round(held, 1), "total%": round(total, 1),
        "MDD%": round(dd, 1), "Sharpe_ann": round(sharpe_ann, 2),
        "PF": round(pf, 2),
    }


def run() -> pd.DataFrame:
    files = select_universe(TOP_N)
    # 시그널 & close 캐시
    cache: dict[str, tuple[np.ndarray, dict[str, np.ndarray], np.ndarray]] = {}
    t0 = time.time()
    n_skip = 0
    for i, p in enumerate(files):
        symbol = p.stem
        try:
            df = load_1h(p)
        except Exception:
            n_skip += 1
            continue
        if df.empty or len(df) < MIN_BARS_1H:
            n_skip += 1
            continue
        df_r = df.reset_index(drop=True)
        try:
            score_chase = trend_chase.score(df_r, {}).to_numpy().astype("float32")
            score_pull  = trend_pullback.score(df_r, {}).to_numpy().astype("float32")
        except Exception as e:
            n_skip += 1
            continue
        close = df["close"].astype("float64").to_numpy()
        in_period = np.asarray(df.index >= SINCE)
        cache[symbol] = (close, {"trend_chase": score_chase, "trend_pullback": score_pull}, in_period)
        if (i + 1) % 20 == 0:
            print(f"  loaded {i+1}/{len(files)} (skipped {n_skip}, "
                  f"elapsed {time.time()-t0:.1f}s)", flush=True)
    print(f"[load] {len(cache)} symbols cached, skipped {n_skip}, {time.time()-t0:.1f}s", flush=True)

    rows = []
    for strat_name in STRATEGIES:
        for th in SCORE_GRID:
            for rule in EXIT_RULES_1H:
                trades = []
                for symbol, (close, scores, in_period) in cache.items():
                    sc = scores[strat_name]
                    sig01 = (sc >= float(th)).astype("int8")
                    diff = np.diff(sig01.astype("int16"), prepend=0)
                    enter_mask = (diff == 1) & in_period
                    positions = np.where(enter_mask)[0]
                    for pos in positions:
                        if pos >= len(close) - 1:
                            continue
                        exit_pos, gross = simulate(close, int(pos), rule)
                        if exit_pos == pos:
                            continue
                        trades.append({
                            "symbol": symbol,
                            "held": exit_pos - pos,
                            "gross_ret": gross,
                            "net_ret": gross - COST,
                        })
                summary = summarize_with_years(trades, SINCE_YEARS)
                rows.append({
                    "strategy": strat_name, "interval": "1h",
                    "score_th": th, "rule": rule.name,
                    **summary,
                })
                print(f"  {strat_name:<15s} th={th:>3} rule={rule.name:<32s} "
                      f"n={summary['n']:>6} win={summary['win%']:>5.1f}% "
                      f"mean={summary['mean%']:>+6.2f}% Sharpe={summary['Sharpe_ann']:>+6.2f} "
                      f"PF={summary['PF']:>5.2f}", flush=True)

    out = pd.DataFrame(rows)
    csv = OUT_DIR / "task1_1h_grid.csv"
    out.to_csv(csv, index=False, encoding="utf-8-sig")
    print(f"saved: {csv}", flush=True)

    # best per strategy
    best = (out[out["n"] >= 30]
            .sort_values("Sharpe_ann", ascending=False)
            .groupby("strategy", as_index=False)
            .first())
    best.to_csv(OUT_DIR / "task1_1h_best.csv", index=False, encoding="utf-8-sig")
    print("\n=== best per strategy (n>=30) ===")
    print(best[["strategy", "score_th", "rule", "n", "win%", "mean%", "Sharpe_ann", "PF"]].to_string(index=False))
    return out


if __name__ == "__main__":
    run()
