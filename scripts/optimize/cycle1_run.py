"""Cycle 1 — 진단 + OOS split + 청산 룰 미세 그리드.

3 가지 작업을 한 번의 종목 로드로 모두 수행:
  1) MDD = -100% 진단: per-trade min_ret 분포 (median, p90, p99) 산출
  2) OOS split: 최근 2년 vs 과거 4년 별 Sharpe/n/win%
  3) 청산 룰 미세 그리드: trail × TP × hold (KR/US 1d, trend_pullback)

산출:
  scripts/out/optimize/deep/grids/cycle1_diag_kr.csv
  scripts/out/optimize/deep/grids/cycle1_diag_us.csv
  scripts/out/optimize/deep/grids/cycle1_oos_split.csv
  scripts/out/optimize/deep/grids/cycle1_exit_micro_kr.csv
  scripts/out/optimize/deep/grids/cycle1_exit_micro_us.csv
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import trend_chase, trend_pullback, quiet_bottom  # noqa: E402
from scripts.trend_strategies.forward_returns import (  # noqa: E402
    load_stock, kr_universe, us_universe, KR_DIR, US_DIR,
)

OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "deep" / "grids"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NOW = pd.Timestamp.utcnow().tz_localize(None).normalize()
SINCE_YEARS = 6
SINCE = NOW - pd.DateOffset(years=SINCE_YEARS)
OOS_CUT = NOW - pd.DateOffset(years=2)  # 최근 2 년이 OOS

COST_RT = {"kr": 0.003, "us": 0.002}
UNIVERSE_TOP = 300
MIN_BARS = 80  # 1d


# ---------------------------------------------------------------------------
@dataclass
class ExitRule:
    name: str
    max_hold: int = 0
    trailing_pct: float = 0.0
    take_profit_pct: float = 0.0
    cut_1bar_neg: bool = False
    cut_short_thr: float = -999
    cut_short_at: int = 2


def simulate_with_min(close: np.ndarray, entry_pos: int, rule: ExitRule
                      ) -> Tuple[int, float, float]:
    """Long simulate — 청산 시 (exit_pos, gross_ret, min_ret_during_trade) 반환.

    min_ret_during_trade = 진입 ~ 청산 사이 어떤 봉에서든 (low_or_close/entry - 1) 의 최저.
    """
    n = len(close)
    ec = close[entry_pos]
    if not np.isfinite(ec) or ec <= 0:
        return entry_pos, 0.0, 0.0
    peak = ec
    min_ret = 0.0
    for i in range(entry_pos + 1, n):
        held = i - entry_pos
        ci = close[i]
        if not np.isfinite(ci):
            continue
        peak = max(peak, ci)
        ret = ci / ec - 1.0
        if ret < min_ret:
            min_ret = ret
        # 1) take profit
        if rule.take_profit_pct > 0 and ret >= rule.take_profit_pct:
            return i, ret, min_ret
        # 2) trailing
        if rule.trailing_pct > 0 and peak > ec:
            if ci / peak - 1.0 <= -rule.trailing_pct:
                return i, ret, min_ret
        # 3) cut on first bar negative
        if rule.cut_1bar_neg and held == 1 and ret < 0:
            return i, ret, min_ret
        # 4) cut short threshold
        if rule.cut_short_thr > -100 and held == rule.cut_short_at and ret * 100 < rule.cut_short_thr:
            return i, ret, min_ret
        # 5) max hold
        if rule.max_hold > 0 and held >= rule.max_hold:
            return i, ret, min_ret
    last = n - 1
    if last <= entry_pos:
        return entry_pos, 0.0, 0.0
    return last, close[last] / ec - 1.0, min_ret


def summarize(rets: np.ndarray, period_years: float) -> dict:
    if len(rets) == 0:
        return dict(n=0, **{f"k_{k}": 0 for k in
                            ("win", "mean", "median", "MDD_series", "Sharpe", "PF")})
    win = float((rets > 0).mean() * 100)
    mean = float(rets.mean() * 100)
    median = float(np.median(rets) * 100)
    eq = np.cumprod(1.0 + rets)
    peak = np.maximum.accumulate(eq)
    dd = float((eq / peak - 1.0).min() * 100)
    if rets.std() > 0 and period_years > 0:
        sharpe_pt = rets.mean() / rets.std()
        ann = np.sqrt(max(1, len(rets)) / float(period_years))
        sharpe_ann = float(sharpe_pt * ann)
    else:
        sharpe_ann = 0.0
    gains = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = float(gains / losses) if losses > 0 else 99.99
    return dict(
        n=int(len(rets)),
        win=round(win, 1),
        mean=round(mean, 2),
        median=round(median, 2),
        MDD_series=round(dd, 1),
        Sharpe=round(sharpe_ann, 2),
        PF=round(pf, 2),
    )


# ---------------------------------------------------------------------------
def _files_for(asset: str) -> List[Path]:
    base = KR_DIR if asset == "kr" else US_DIR
    return [p for p in sorted(base.glob("*.parquet")) if not p.stem.startswith("_")]


def load_cache(asset: str) -> Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """종목별 (close, score_chase, score_pullback, dt_array) 캐시."""
    universe = (kr_universe if asset == "kr" else us_universe)(UNIVERSE_TOP)
    files = _files_for(asset)
    cache: Dict[str, Tuple] = {}
    t0 = time.time()
    n_skip = 0
    print(f"[{asset.upper()}] universe={len(universe)} files={len(files)}", flush=True)
    for p in files:
        sym = p.stem
        if sym not in universe:
            continue
        try:
            df = load_stock(p, "1d")
        except Exception:
            n_skip += 1
            continue
        if df is None or df.empty or len(df) < MIN_BARS:
            n_skip += 1
            continue
        df = df.sort_index()
        df_r = df.reset_index(drop=True)
        try:
            sc_chase = trend_chase.score(df_r, {}).to_numpy().astype("float32")
            sc_pull = trend_pullback.score(df_r, {}).to_numpy().astype("float32")
        except Exception:
            n_skip += 1
            continue
        close = df["close"].astype("float64").to_numpy()
        dt = pd.DatetimeIndex(df.index).to_numpy()
        cache[sym] = (close, sc_chase, sc_pull, dt)
        if len(cache) % 50 == 0:
            print(f"  loaded {len(cache)} (skip {n_skip})", flush=True)
    print(f"  done: {len(cache)} symbols, skip {n_skip}, elapsed {time.time()-t0:.1f}s",
          flush=True)
    return cache


def collect_trades(cache, score_key: str, threshold: float,
                   rule: ExitRule, start_dt: pd.Timestamp,
                   end_dt: Optional[pd.Timestamp] = None,
                   cost: float = 0.003) -> List[dict]:
    """진입 인덱스 -> simulate -> per-trade rows.

    score_key: 'chase' or 'pullback'
    """
    start = np.datetime64(start_dt)
    end = None if end_dt is None else np.datetime64(end_dt)
    trades = []
    for sym, (close, sc_chase, sc_pull, dt) in cache.items():
        sc = sc_chase if score_key == "chase" else sc_pull
        if len(sc) < 2:
            continue
        sig01 = (sc >= threshold).astype("int8")
        diff = np.diff(sig01.astype("int16"), prepend=0)
        enter_mask = (diff == 1) & (dt >= start)
        if end is not None:
            enter_mask &= (dt < end)
        positions = np.where(enter_mask)[0]
        for pos in positions:
            if pos >= len(close) - 1:
                continue
            exit_pos, gross_ret, min_ret = simulate_with_min(close, int(pos), rule)
            if exit_pos == pos:
                continue
            net_ret = gross_ret - cost
            trades.append({
                "symbol": sym,
                "entry_dt": pd.Timestamp(dt[pos]).date().isoformat(),
                "held": exit_pos - pos,
                "gross_ret": gross_ret,
                "net_ret": net_ret,
                "min_ret": min_ret,
            })
    return trades


# ---------------------------------------------------------------------------
# Task 1: MDD diagnostic
# ---------------------------------------------------------------------------
def task_diag(asset: str, cache) -> pd.DataFrame:
    """현재 best combo에서 per-trade min_ret 분포 + return 분포."""
    cost = COST_RT[asset]
    rule = ExitRule("hold_252d_trail20_TP30", max_hold=252,
                    trailing_pct=0.20, take_profit_pct=0.30)
    th = 60 if asset == "kr" else 70  # SUMMARY 의 best
    trades = collect_trades(cache, "pullback", th, rule, SINCE, None, cost)
    if not trades:
        return pd.DataFrame()
    df = pd.DataFrame(trades)
    rets = df["net_ret"].to_numpy()
    mins = df["min_ret"].to_numpy()
    helds = df["held"].to_numpy()

    rows = []
    rows.append({"asset": asset, "metric": "n_trades", "value": len(rets)})
    # return 분포
    for q, label in [(0.01, "p01"), (0.05, "p05"), (0.5, "median"), (0.95, "p95"), (0.99, "p99")]:
        rows.append({"asset": asset, "metric": f"net_ret_{label}",
                     "value": round(float(np.quantile(rets, q)) * 100, 2)})
    rows.append({"asset": asset, "metric": "net_ret_min",
                 "value": round(float(rets.min()) * 100, 2)})
    rows.append({"asset": asset, "metric": "net_ret_max",
                 "value": round(float(rets.max()) * 100, 2)})
    # trade 내부 최저점 분포 (drawdown)
    for q, label in [(0.5, "median"), (0.9, "p90"), (0.99, "p99")]:
        rows.append({"asset": asset, "metric": f"trade_min_ret_{label}",
                     "value": round(float(np.quantile(mins, q)) * 100, 2)})
    rows.append({"asset": asset, "metric": "trade_min_ret_worst",
                 "value": round(float(mins.min()) * 100, 2)})
    # series-level cumprod MDD vs equal-weight 비교
    # (a) sequential cumprod (현재 방식)
    eq = np.cumprod(1.0 + rets)
    peak = np.maximum.accumulate(eq)
    mdd_seq = float((eq / peak - 1.0).min() * 100)
    rows.append({"asset": asset, "metric": "MDD_seq_cumprod", "value": round(mdd_seq, 1)})
    rows.append({"asset": asset, "metric": "eq_final_seq", "value": round(float(eq[-1]), 4)})
    # (b) 동시 보유 가능 — 일별 그룹화 후 평균
    df_dt = df.assign(_dt=pd.to_datetime(df["entry_dt"]))
    daily_mean = df_dt.groupby("_dt")["net_ret"].mean()
    # 시간 정렬된 daily mean 의 cumprod
    daily_mean = daily_mean.sort_index()
    eq2 = np.cumprod(1.0 + daily_mean.to_numpy())
    peak2 = np.maximum.accumulate(eq2)
    mdd_ew = float((eq2 / peak2 - 1.0).min() * 100)
    rows.append({"asset": asset, "metric": "MDD_daily_mean_cumprod", "value": round(mdd_ew, 1)})
    rows.append({"asset": asset, "metric": "eq_final_daily_mean", "value": round(float(eq2[-1]), 4)})
    # (c) held 분포
    rows.append({"asset": asset, "metric": "held_median", "value": int(np.median(helds))})
    rows.append({"asset": asset, "metric": "held_p90", "value": int(np.quantile(helds, 0.9))})
    # (d) % of trades that hit -50% intraday
    rows.append({"asset": asset, "metric": "pct_trades_min_ret_lt_-50%",
                 "value": round(float((mins < -0.5).mean() * 100), 2)})
    rows.append({"asset": asset, "metric": "pct_trades_min_ret_lt_-30%",
                 "value": round(float((mins < -0.3).mean() * 100), 2)})

    out = pd.DataFrame(rows)
    return out


# ---------------------------------------------------------------------------
# Task 2: OOS split
# ---------------------------------------------------------------------------
TOP_COMBOS = [
    # (asset, score_key, threshold)
    ("kr", "pullback", 60),
    ("kr", "pullback", 70),
    ("us", "pullback", 60),
    ("us", "pullback", 70),
    ("kr", "chase", 60),
    ("us", "chase", 60),
]

RULE_BASE = ExitRule("hold_252d_trail20_TP30", max_hold=252,
                     trailing_pct=0.20, take_profit_pct=0.30)


def task_oos_split(caches: Dict[str, dict]) -> pd.DataFrame:
    rows = []
    for asset, score_key, th in TOP_COMBOS:
        cache = caches[asset]
        cost = COST_RT[asset]
        # in-sample: 4년 전 ~ 2년 전 (4yrs)
        is_trades = collect_trades(cache, score_key, th, RULE_BASE, SINCE, OOS_CUT, cost)
        # OOS: 최근 2년
        oos_trades = collect_trades(cache, score_key, th, RULE_BASE, OOS_CUT, None, cost)
        for label, trades, yrs in [("IS_4yr", is_trades, 4.0),
                                    ("OOS_2yr", oos_trades, 2.0),
                                    ("ALL_6yr", is_trades + oos_trades, 6.0)]:
            if not trades:
                rows.append(dict(asset=asset, strategy=f"trend_{score_key}",
                                 threshold=th, period=label,
                                 n=0, win=0, mean=0, median=0,
                                 MDD_series=0, Sharpe=0, PF=0))
                continue
            rets = np.asarray([t["net_ret"] for t in trades])
            s = summarize(rets, yrs)
            rows.append(dict(asset=asset, strategy=f"trend_{score_key}",
                             threshold=th, period=label, **s))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Task 3: 청산 룰 미세 그리드 (KR/US 1d trend_pullback)
# ---------------------------------------------------------------------------
TRAILS = [0.15, 0.18, 0.20, 0.22, 0.25]
TPS = [0.20, 0.25, 0.30, 0.35]
HOLDS = [120, 180, 252]


def task_exit_micro(asset: str, cache) -> pd.DataFrame:
    cost = COST_RT[asset]
    th = 60 if asset == "kr" else 70
    rows = []
    total = len(TRAILS) * len(TPS) * len(HOLDS)
    i = 0
    t0 = time.time()
    for hold in HOLDS:
        for trail in TRAILS:
            for tp in TPS:
                i += 1
                rule = ExitRule(
                    f"hold{hold}_trail{int(trail*100)}_TP{int(tp*100)}",
                    max_hold=hold, trailing_pct=trail, take_profit_pct=tp,
                )
                trades = collect_trades(cache, "pullback", th, rule,
                                        SINCE, None, cost)
                rets = np.asarray([t["net_ret"] for t in trades]) if trades \
                    else np.asarray([])
                s = summarize(rets, SINCE_YEARS)
                rows.append(dict(asset=asset, strategy="trend_pullback",
                                 threshold=th, hold=hold, trail=trail, tp=tp,
                                 rule=rule.name, **s))
                if i % 10 == 0 or i == total:
                    print(f"  exit_micro [{asset}] {i}/{total} "
                          f"({time.time()-t0:.0f}s)", flush=True)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
def main():
    print("=== Cycle 1: 진단 + OOS split + 청산 미세 그리드 ===", flush=True)
    t_global = time.time()

    caches = {}
    for asset in ("kr", "us"):
        caches[asset] = load_cache(asset)

    # Task 1
    print("\n[Task 1] MDD diagnostic", flush=True)
    diag_rows = []
    for asset in ("kr", "us"):
        d = task_diag(asset, caches[asset])
        out_p = OUT_DIR / f"cycle1_diag_{asset}.csv"
        d.to_csv(out_p, index=False, encoding="utf-8-sig")
        print(f"  saved {out_p}", flush=True)
        diag_rows.append(d)

    # Task 2
    print("\n[Task 2] OOS split", flush=True)
    oos = task_oos_split(caches)
    out_p = OUT_DIR / "cycle1_oos_split.csv"
    oos.to_csv(out_p, index=False, encoding="utf-8-sig")
    print(f"  saved {out_p}", flush=True)
    print(oos.to_string(index=False), flush=True)

    # Task 3
    print("\n[Task 3] 청산 룰 미세 그리드", flush=True)
    for asset in ("kr", "us"):
        g = task_exit_micro(asset, caches[asset])
        out_p = OUT_DIR / f"cycle1_exit_micro_{asset}.csv"
        g.to_csv(out_p, index=False, encoding="utf-8-sig")
        print(f"  saved {out_p}", flush=True)
        # top 5 by Sharpe (n>=200)
        top = g[g["n"] >= 200].sort_values("Sharpe", ascending=False).head(5)
        print(f"  top 5 by Sharpe (n>=200):\n{top.to_string(index=False)}", flush=True)

    print(f"\n총 소요: {(time.time()-t_global)/60:.1f}분", flush=True)


if __name__ == "__main__":
    main()
