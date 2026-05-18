"""Cycle 2 — 청산 룰 정밀 그리드 (IS/OOS 분리).

Cycle 1 OOS 살아남은 6 조합에 대해 trail × TP × hold 3축 그리드.

대상:
  - KR trend_pullback 1d (th=60)
  - US trend_pullback 1d (th=70)
  - KR trend_chase 1d (th=60)
  - US trend_chase 1d (th=60)
  - KR quiet_bottom 1w (binary)
  - US quiet_bottom 1w (binary)

그리드:
  - trail_pct ∈ {0.10, 0.15, 0.20, 0.25, 0.30}
  - take_profit ∈ {0.20, 0.25, 0.30, 0.40, 0.50, None}
  - hold (1d) ∈ {60, 120, 252} bars
  - hold (1w) ∈ {13, 26, 52} bars

평가: IS 2020-05-01 ~ 2024-05-01, OOS 2024-05-01 ~ 2026-05-01.

산출:
  scripts/out/optimize/cycle_2/exit_grid_{asset}_{strategy}.csv
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.optimize_grid import (  # noqa: E402
    STRATEGIES, COST_RT, MIN_BARS, UNIVERSE_TOP,
    _build_universe, _files_for, load_symbol,
)

OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "cycle_2"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# IS / OOS split
IS_START = pd.Timestamp("2020-05-01")
SPLIT_DATE = pd.Timestamp("2024-05-01")
OOS_END = pd.Timestamp("2026-05-01")
IS_YEARS = (SPLIT_DATE - IS_START).days / 365.25
OOS_YEARS = (OOS_END - SPLIT_DATE).days / 365.25

# 6 조합 + cycle1 OOS-best threshold
TARGETS = [
    ("kr", "trend_pullback", "1d", 60),
    ("us", "trend_pullback", "1d", 70),
    ("kr", "trend_chase", "1d", 60),
    ("us", "trend_chase", "1d", 60),
    ("kr", "quiet_bottom", "1w", "binary"),
    ("us", "quiet_bottom", "1w", "binary"),
]

TRAIL_GRID = [0.10, 0.15, 0.20, 0.25, 0.30]
TP_GRID: List[Optional[float]] = [0.20, 0.25, 0.30, 0.40, 0.50, None]
HOLD_1D = [60, 120, 252]
HOLD_1W = [13, 26, 52]


def hold_grid(interval: str) -> List[int]:
    return HOLD_1D if interval == "1d" else HOLD_1W


@dataclass
class ExitRuleS:
    max_hold: int
    trail: float
    tp: Optional[float]

    @property
    def name(self) -> str:
        tp_s = f"TP{int(self.tp*100)}" if self.tp else "TPoff"
        return f"trail{int(self.trail*100)}_{tp_s}_hold{self.max_hold}"


def simulate_fast(close: np.ndarray, entry_pos: int, rule: ExitRuleS) -> Tuple[int, float]:
    """단순 long simulate. close[entry_pos] 진입, (exit_idx, gross_ret) 반환."""
    n = len(close)
    ec = close[entry_pos]
    if not np.isfinite(ec) or ec <= 0:
        return entry_pos, 0.0
    peak = ec
    tp = rule.tp if rule.tp is not None else -1.0  # disabled
    trail = rule.trail
    mh = rule.max_hold
    for i in range(entry_pos + 1, n):
        held = i - entry_pos
        ci = close[i]
        if not np.isfinite(ci):
            continue
        if ci > peak:
            peak = ci
        ret = ci / ec - 1.0
        if tp > 0 and ret >= tp:
            return i, ret
        if trail > 0 and peak > ec:
            if ci / peak - 1.0 <= -trail:
                return i, ret
        if held >= mh:
            return i, ret
    last = n - 1
    if last <= entry_pos:
        return entry_pos, 0.0
    return last, close[last] / ec - 1.0


def summarize(rets: np.ndarray, period_years: float) -> dict:
    if rets.size == 0:
        return {"n": 0, "win%": 0.0, "mean%": 0.0, "MDD%": 0.0,
                "Sharpe": 0.0, "PF": 0.0}
    win = float((rets > 0).mean() * 100)
    mean = float(rets.mean() * 100)
    eq = np.cumprod(1.0 + rets)
    peak = np.maximum.accumulate(eq)
    mdd = float((eq / peak - 1.0).min() * 100)
    if rets.std() > 0:
        sharpe_pt = rets.mean() / rets.std()
        annual_factor = np.sqrt(max(1, len(rets)) / period_years)
        sharpe = float(sharpe_pt * annual_factor)
    else:
        sharpe = 0.0
    gains = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = float(gains / losses) if losses > 0 else 99.99
    return {"n": int(rets.size),
            "win%": round(win, 1),
            "mean%": round(mean, 2),
            "MDD%": round(mdd, 1),
            "Sharpe": round(sharpe, 2),
            "PF": round(pf, 2)}


def run_target(asset: str, strategy: str, interval: str, th) -> pd.DataFrame:
    strat = STRATEGIES[strategy]
    cost = COST_RT[asset]
    min_bars = MIN_BARS[interval]
    universe = _build_universe(asset)
    files = _files_for(asset, interval)
    is_quiet = (strategy == "quiet_bottom")

    print(f"\n=== {asset.upper()} / {strategy} / {interval} / th={th} "
          f"(universe={len(universe)}, files={len(files)}) ===", flush=True)

    t0 = time.time()
    # 종목별로 (close, enter_is_idx, enter_oos_idx) 캐싱
    cache: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    n_done = 0
    n_skip = 0
    for p in files:
        sym = p.stem
        if sym not in universe:
            continue
        try:
            df = load_symbol(asset, p, interval)
        except Exception:
            n_skip += 1
            continue
        if df is None or df.empty or len(df) < min_bars:
            n_skip += 1
            continue
        df = df.sort_index()
        df_r = df.reset_index(drop=True)
        try:
            if is_quiet:
                sig = strat.signal(df_r, {})
                sig01 = sig.to_numpy().astype("int8")
            else:
                sc = strat.score(df_r, {})
                val = sc.to_numpy().astype("float32")
                sig01 = (val >= float(th)).astype("int8")
        except Exception:
            n_skip += 1
            continue
        if len(sig01) < 2:
            continue
        close = df["close"].astype("float64").to_numpy()
        dt_idx = pd.DatetimeIndex(df.index)
        in_is = np.asarray((dt_idx >= IS_START) & (dt_idx < SPLIT_DATE))
        in_oos = np.asarray((dt_idx >= SPLIT_DATE) & (dt_idx <= OOS_END))
        diff = np.diff(sig01.astype("int16"), prepend=0)
        enter_is = np.where((diff == 1) & in_is)[0]
        enter_oos = np.where((diff == 1) & in_oos)[0]
        # 마지막 봉 진입은 의미 없음
        enter_is = enter_is[enter_is < len(close) - 1]
        enter_oos = enter_oos[enter_oos < len(close) - 1]
        if len(enter_is) == 0 and len(enter_oos) == 0:
            continue
        cache[sym] = (close, enter_is, enter_oos)
        n_done += 1
        if n_done % 100 == 0:
            print(f"  loaded {n_done} (skipped {n_skip})", flush=True)

    print(f"  loaded {n_done} symbols (skipped {n_skip}), elapsed {time.time()-t0:.1f}s",
          flush=True)
    if n_done == 0:
        return pd.DataFrame()

    rows = []
    holds = hold_grid(interval)
    total_cells = len(TRAIL_GRID) * len(TP_GRID) * len(holds)
    print(f"  grid = {len(TRAIL_GRID)} trail × {len(TP_GRID)} TP × {len(holds)} hold = "
          f"{total_cells} cells", flush=True)
    t1 = time.time()
    cell_i = 0
    for hold in holds:
        for trail in TRAIL_GRID:
            for tp in TP_GRID:
                cell_i += 1
                rule = ExitRuleS(max_hold=hold, trail=trail, tp=tp)
                is_rets: List[float] = []
                oos_rets: List[float] = []
                for sym, (close, e_is, e_oos) in cache.items():
                    for pos in e_is:
                        ex, gross = simulate_fast(close, int(pos), rule)
                        if ex == pos:
                            continue
                        is_rets.append(gross - cost)
                    for pos in e_oos:
                        ex, gross = simulate_fast(close, int(pos), rule)
                        if ex == pos:
                            continue
                        oos_rets.append(gross - cost)
                is_s = summarize(np.asarray(is_rets), IS_YEARS)
                oos_s = summarize(np.asarray(oos_rets), OOS_YEARS)
                row = {
                    "asset": asset, "strategy": strategy, "interval": interval,
                    "score_th": th, "trail": trail,
                    "tp": tp if tp is not None else None,
                    "hold": hold,
                    "rule_name": rule.name,
                    "IS_n": is_s["n"], "IS_win%": is_s["win%"],
                    "IS_mean%": is_s["mean%"], "IS_MDD%": is_s["MDD%"],
                    "IS_Sharpe": is_s["Sharpe"], "IS_PF": is_s["PF"],
                    "OOS_n": oos_s["n"], "OOS_win%": oos_s["win%"],
                    "OOS_mean%": oos_s["mean%"], "OOS_MDD%": oos_s["MDD%"],
                    "OOS_Sharpe": oos_s["Sharpe"], "OOS_PF": oos_s["PF"],
                }
                if is_s["Sharpe"] != 0:
                    row["Sharpe_decay"] = round(
                        (oos_s["Sharpe"] - is_s["Sharpe"]) / abs(is_s["Sharpe"]), 3)
                else:
                    row["Sharpe_decay"] = None
                rows.append(row)
                if cell_i % 10 == 0 or cell_i == total_cells:
                    print(f"  cell {cell_i}/{total_cells} "
                          f"hold={hold} trail={trail:.2f} tp={tp} | "
                          f"IS S={is_s['Sharpe']:>+5.2f} n={is_s['n']:>5} | "
                          f"OOS S={oos_s['Sharpe']:>+5.2f} n={oos_s['n']:>5} "
                          f"({time.time()-t1:.0f}s elapsed)", flush=True)
    df = pd.DataFrame(rows)
    out = OUT_DIR / f"exit_grid_{asset}_{strategy}_{interval}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"  saved: {out}", flush=True)
    return df


def main():
    all_rows = []
    for asset, strategy, interval, th in TARGETS:
        try:
            df = run_target(asset, strategy, interval, th)
            if not df.empty:
                all_rows.append(df)
        except Exception as e:
            print(f"FAIL {asset}/{strategy}/{interval}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            import traceback
            traceback.print_exc()
    if not all_rows:
        print("no rows produced", file=sys.stderr)
        return 1
    master = pd.concat(all_rows, ignore_index=True)
    out_all = OUT_DIR / "exit_grid_all.csv"
    master.to_csv(out_all, index=False, encoding="utf-8-sig")
    print(f"\nMaster: {out_all} ({len(master)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
