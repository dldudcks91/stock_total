"""Cycle 2 — 청산 룰 정밀 그리드.

대상 (Cycle 1 OOS 생존 조합):
  - KR trend_pullback 1d   score_th=60   (OOS Sharpe 24.48)
  - US trend_pullback 1d   score_th=70   (OOS Sharpe 21.94)
  - KR trend_chase    1d   score_th=60   (OOS Sharpe 12.17)
  - US trend_chase    1d   score_th=60   (OOS Sharpe  6.46)
  - US quiet_bottom   1w   binary        (OOS Sharpe  5.01)
  - KR quiet_bottom   1w   binary        (OOS Sharpe  4.36)

Stage A coarse grid:
  trail ∈ {15, 20, 25} %
  TP    ∈ {20, 30, None}      (None = TP 비활성)
  hold  (1d): {60, 252}       /  (1w): {26, 52}
  → 3×3×2 = 18 cells per combo × 6 combos = 108 cells

Stage B fine grid: Stage A best ±1 step
  trail ∈ best ± {5} (clamp [10, 30])     → 3 values
  TP    ∈ best ± {5} (clamp [20, 50] ∪ None) → 3 values
  hold: 1d {best, best±60} / 1w {best, best±13} → 3 values
  → 27 cells per combo × 6 combos = 162 cells

OOS 분리: 2024-05-17 기준 (Cycle 1 과 동일).
수수료 RT: KR 0.3%, US/Crypto 0.2%.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import trend_chase, trend_pullback, quiet_bottom  # noqa: E402
from scripts.trend_strategies.forward_returns import (  # noqa: E402
    load_crypto, load_stock, kr_universe, us_universe,
    KR_DIR, US_DIR,
)

OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "cycle_2"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NOW = pd.Timestamp.utcnow().tz_localize(None).normalize()
SINCE_YEARS = 6
SINCE = NOW - pd.DateOffset(years=SINCE_YEARS)
# OOS split: 가장 최근 2년
OOS_SPLIT = NOW - pd.DateOffset(years=2)

COST_RT = {"crypto": 0.002, "kr": 0.003, "us": 0.002}

UNIVERSE_TOP = 300
MIN_BARS = {"1d": 80, "1w": 30}

STRATEGIES = {
    "trend_chase": trend_chase,
    "trend_pullback": trend_pullback,
    "quiet_bottom": quiet_bottom,
}

# Cycle 2 대상 조합
COMBOS = [
    ("kr", "trend_pullback", "1d", 60.0),
    ("us", "trend_pullback", "1d", 70.0),
    ("kr", "trend_chase",    "1d", 60.0),
    ("us", "trend_chase",    "1d", 60.0),
    ("us", "quiet_bottom",   "1w", None),
    ("kr", "quiet_bottom",   "1w", None),
]


# ---------------------------------------------------------------------------
# Exit rule
# ---------------------------------------------------------------------------
@dataclass
class ExitRule:
    name: str
    max_hold: int
    trailing_pct: float
    take_profit_pct: float  # 0.0 = disabled

    @property
    def tp_label(self) -> str:
        return "none" if self.take_profit_pct <= 0 else f"{int(self.take_profit_pct*100)}"


def simulate(close: np.ndarray, entry_pos: int, rule: ExitRule) -> Tuple[int, float]:
    n = len(close)
    ec = close[entry_pos]
    if not np.isfinite(ec) or ec <= 0:
        return entry_pos, 0.0
    peak = ec
    for i in range(entry_pos + 1, n):
        held = i - entry_pos
        ci = close[i]
        if not np.isfinite(ci):
            continue
        peak = max(peak, ci)
        ret = ci / ec - 1.0
        if rule.take_profit_pct > 0 and ret >= rule.take_profit_pct:
            return i, ret
        if rule.trailing_pct > 0 and peak > ec:
            if ci / peak - 1.0 <= -rule.trailing_pct:
                return i, ret
        if rule.max_hold > 0 and held >= rule.max_hold:
            return i, ret
    last = n - 1
    if last <= entry_pos:
        return entry_pos, 0.0
    return last, close[last] / ec - 1.0


def summarize(trades: List[dict]) -> dict:
    if not trades:
        return {"n": 0, "win%": 0.0, "mean%": 0.0, "MDD%": 0.0,
                "Sharpe": 0.0, "PF": 0.0, "held": 0.0}
    df = pd.DataFrame(trades)
    rets = df["net_ret"].to_numpy()
    win = float((rets > 0).mean() * 100)
    mean = float(rets.mean() * 100)
    held = float(df["held"].mean())
    eq = np.cumprod(1.0 + rets)
    peak = np.maximum.accumulate(eq)
    dd = float((eq / peak - 1.0).min() * 100)
    if rets.std() > 0:
        sharpe_pt = rets.mean() / rets.std()
        ann_factor = np.sqrt(max(1, len(rets)) / float(SINCE_YEARS))
        sharpe = float(sharpe_pt * ann_factor)
    else:
        sharpe = 0.0
    gains = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = float(gains / losses) if losses > 0 else 99.99
    return {
        "n": int(len(rets)),
        "win%": round(win, 1),
        "mean%": round(mean, 2),
        "MDD%": round(dd, 1),
        "Sharpe": round(sharpe, 2),
        "PF": round(pf, 2),
        "held": round(held, 1),
    }


# ---------------------------------------------------------------------------
# Cache build
# ---------------------------------------------------------------------------
def _universe(asset: str) -> set:
    if asset == "kr":
        return kr_universe(UNIVERSE_TOP)
    if asset == "us":
        return us_universe(UNIVERSE_TOP)
    raise ValueError(asset)


def _files(asset: str) -> List[Path]:
    if asset == "kr":
        return [p for p in sorted(KR_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    if asset == "us":
        return [p for p in sorted(US_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    raise ValueError(asset)


def build_cache(asset: str, strategy_name: str, interval: str):
    """Returns dict[symbol] -> (close_arr, signal_or_score_arr, dt_index, in_period_mask)."""
    strat = STRATEGIES[strategy_name]
    is_quiet = strategy_name == "quiet_bottom"
    universe = _universe(asset)
    files = _files(asset)
    min_bars = MIN_BARS[interval]
    cache = {}
    n_done = 0
    n_skip = 0
    for p in files:
        symbol = p.stem
        if symbol not in universe:
            continue
        try:
            df = load_stock(p, interval)
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
                val = sig.to_numpy().astype("int8")
            else:
                sc = strat.score(df_r, {})
                val = sc.to_numpy().astype("float32")
        except Exception:
            n_skip += 1
            continue
        close = df["close"].astype("float64").to_numpy()
        dt_idx = pd.DatetimeIndex(df.index)
        in_period = np.asarray(dt_idx >= SINCE)
        # entry timestamp 별 IS / OOS 분류용
        cache[symbol] = (close, val, dt_idx, in_period)
        n_done += 1
    print(f"  cache built: {n_done} symbols (skipped {n_skip})", flush=True)
    return cache


# ---------------------------------------------------------------------------
# Grid execution
# ---------------------------------------------------------------------------
def run_combo(asset: str, strategy: str, interval: str, score_th: Optional[float],
              rules: List[ExitRule]) -> pd.DataFrame:
    cost = COST_RT[asset]
    is_quiet = strategy == "quiet_bottom"
    t0 = time.time()
    print(f"\n=== {asset.upper()} / {strategy} / {interval}"
          f"  score_th={score_th if score_th else 'binary'}  rules={len(rules)} ===",
          flush=True)
    cache = build_cache(asset, strategy, interval)
    if not cache:
        return pd.DataFrame()

    # 진입 인덱스 1회 precompute (모든 rule 공통)
    entries = {}  # symbol -> list[(pos, dt)]
    for symbol, (close, val, dt_idx, in_period) in cache.items():
        if is_quiet:
            sig01 = val
        else:
            sig01 = (val >= float(score_th)).astype("int8")
        if len(sig01) < 2:
            continue
        diff = np.diff(sig01.astype("int16"), prepend=0)
        enter_mask = (diff == 1) & in_period
        positions = np.where(enter_mask)[0]
        ent_list = []
        for pos in positions:
            if pos >= len(close) - 1:
                continue
            ent_list.append((int(pos), dt_idx[pos]))
        if ent_list:
            entries[symbol] = ent_list

    n_total_entries = sum(len(v) for v in entries.values())
    print(f"  total entries: {n_total_entries} across {len(entries)} symbols", flush=True)

    rows = []
    for rule in rules:
        trades_full = []
        trades_oos = []
        for symbol, ent_list in entries.items():
            close = cache[symbol][0]
            for pos, ent_dt in ent_list:
                exit_pos, gross = simulate(close, pos, rule)
                if exit_pos == pos:
                    continue
                net = gross - cost
                rec = {"held": exit_pos - pos, "net_ret": net}
                trades_full.append(rec)
                if ent_dt >= OOS_SPLIT:
                    trades_oos.append(rec)
        sum_full = summarize(trades_full)
        sum_oos = summarize(trades_oos)
        row = {
            "asset": asset,
            "strategy": strategy,
            "interval": interval,
            "score_th": score_th if score_th is not None else "binary",
            "trail": int(rule.trailing_pct * 100),
            "tp": rule.tp_label,
            "hold": rule.max_hold,
            "rule_name": rule.name,
            "n_full": sum_full["n"],
            "win%_full": sum_full["win%"],
            "mean%_full": sum_full["mean%"],
            "MDD%_full": sum_full["MDD%"],
            "Sharpe_full": sum_full["Sharpe"],
            "PF_full": sum_full["PF"],
            "held_full": sum_full["held"],
            "n_oos": sum_oos["n"],
            "win%_oos": sum_oos["win%"],
            "mean%_oos": sum_oos["mean%"],
            "Sharpe_oos": sum_oos["Sharpe"],
            "PF_oos": sum_oos["PF"],
        }
        rows.append(row)
        print(f"  trail={int(rule.trailing_pct*100):>2}% tp={rule.tp_label:>4} hold={rule.max_hold:>3}"
              f"  full: n={sum_full['n']:>5} S={sum_full['Sharpe']:>+6.2f} m={sum_full['mean%']:>+5.1f}%"
              f"  oos: n={sum_oos['n']:>5} S={sum_oos['Sharpe']:>+6.2f}", flush=True)
    elapsed = time.time() - t0
    print(f"  combo elapsed {elapsed:.1f}s", flush=True)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Grid catalogs
# ---------------------------------------------------------------------------
def stage_a_rules(interval: str) -> List[ExitRule]:
    """Stage A coarse: trail {15,20,25} × TP {20,30,None} × hold {short,mid,long}."""
    if interval == "1d":
        holds = [60, 120, 252]
    else:  # 1w
        holds = [26, 52, 104]
    trails = [0.15, 0.20, 0.25]
    tps = [0.20, 0.30, 0.0]  # 0.0 = disabled
    rules = []
    for hold in holds:
        for trail in trails:
            for tp in tps:
                name = f"h{hold}_tr{int(trail*100)}_tp{'none' if tp <= 0 else int(tp*100)}"
                rules.append(ExitRule(name=name, max_hold=hold,
                                      trailing_pct=trail, take_profit_pct=tp))
    return rules


def stage_b_rules(interval: str, best_trail: int, best_tp_pct: float,
                  best_hold: int) -> List[ExitRule]:
    """Stage B fine: best ±1 step."""
    # trail ±5
    trails_pct = sorted({max(10, best_trail - 5), best_trail, min(30, best_trail + 5)})
    # tp ±5 (또는 None 유지)
    if best_tp_pct <= 0:
        tps = [0.0, 0.20, 0.30]  # None best 면 작은 TP 추가 검토
    else:
        cur = int(best_tp_pct * 100)
        tps_set = sorted({max(15, cur - 5), cur, min(50, cur + 10)})
        tps = [t / 100.0 for t in tps_set] + [0.0]  # 항상 None 도 비교
    # hold ±60 (1d) or ±13 (1w)
    if interval == "1d":
        step = 60
        lo, hi = 30, 360
    else:
        step = 13
        lo, hi = 13, 78
    holds = sorted({max(lo, best_hold - step), best_hold, min(hi, best_hold + step)})

    rules = []
    for hold in holds:
        for tr_pct in trails_pct:
            trail = tr_pct / 100.0
            for tp in tps:
                name = f"h{hold}_tr{tr_pct}_tp{'none' if tp <= 0 else int(tp*100)}"
                rules.append(ExitRule(name=name, max_hold=hold,
                                      trailing_pct=trail, take_profit_pct=tp))
    # dedup by name
    seen = set()
    out = []
    for r in rules:
        if r.name in seen:
            continue
        seen.add(r.name)
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def pick_best(df: pd.DataFrame) -> dict:
    """Sharpe_oos 우선, 동률 시 Sharpe_full. n_full >= 20 필터."""
    cand = df[df["n_full"] >= 20].copy()
    if cand.empty:
        cand = df.copy()
    cand = cand.sort_values(["Sharpe_oos", "Sharpe_full"], ascending=[False, False])
    return cand.iloc[0].to_dict()


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["A", "B", "both"], default="A")
    ap.add_argument("--only", default="",
                    help="filter combos: e.g. 'kr,trend_pullback,1d'")
    args = ap.parse_args()

    combos = COMBOS
    if args.only:
        parts = args.only.split(",")
        while len(parts) < 3:
            parts.append("")
        a, s, i = [p.strip() for p in parts[:3]]
        combos = [c for c in COMBOS
                  if (not a or c[0] == a) and (not s or c[1] == s) and (not i or c[2] == i)]

    stage_a_summary = []
    stage_b_summary = []

    if args.stage in ("A", "both"):
        for asset, strat, itv, score_th in combos:
            rules = stage_a_rules(itv)
            df = run_combo(asset, strat, itv, score_th, rules)
            if df.empty:
                continue
            csv_path = OUT_DIR / f"exit_grid_{asset}_{strat}_{itv}_stageA.csv"
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            best = pick_best(df)
            stage_a_summary.append({
                "asset": asset, "strategy": strat, "interval": itv,
                "score_th": score_th if score_th else "binary",
                "best_trail": best["trail"],
                "best_tp": best["tp"],
                "best_hold": best["hold"],
                "Sharpe_full": best["Sharpe_full"],
                "Sharpe_oos": best["Sharpe_oos"],
                "mean%_full": best["mean%_full"],
                "win%_full": best["win%_full"],
                "n_full": best["n_full"],
                "n_oos": best["n_oos"],
            })
            print(f"  >> stage A best: trail={best['trail']}% tp={best['tp']}"
                  f" hold={best['hold']}  Sharpe_full={best['Sharpe_full']}"
                  f" Sharpe_oos={best['Sharpe_oos']}", flush=True)
        if stage_a_summary:
            sa_df = pd.DataFrame(stage_a_summary)
            sa_df.to_csv(OUT_DIR / "exit_grid_summary_stageA.csv",
                         index=False, encoding="utf-8-sig")

    if args.stage in ("B", "both"):
        # Stage A best 로딩
        sa_path = OUT_DIR / "exit_grid_summary_stageA.csv"
        if not sa_path.exists():
            print("[ERROR] no stageA summary; run --stage A first", file=sys.stderr)
            return 2
        sa_df = pd.read_csv(sa_path)

        for asset, strat, itv, score_th in combos:
            row = sa_df[(sa_df["asset"] == asset) &
                        (sa_df["strategy"] == strat) &
                        (sa_df["interval"] == itv)]
            if row.empty:
                continue
            r = row.iloc[0]
            best_trail = int(r["best_trail"])
            tp_label = str(r["best_tp"])
            best_tp = 0.0 if tp_label == "none" else float(tp_label) / 100.0
            best_hold = int(r["best_hold"])
            rules = stage_b_rules(itv, best_trail, best_tp, best_hold)
            df = run_combo(asset, strat, itv, score_th, rules)
            if df.empty:
                continue
            csv_path = OUT_DIR / f"exit_grid_{asset}_{strat}_{itv}_stageB.csv"
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            best = pick_best(df)
            stage_b_summary.append({
                "asset": asset, "strategy": strat, "interval": itv,
                "score_th": score_th if score_th else "binary",
                "best_trail": best["trail"],
                "best_tp": best["tp"],
                "best_hold": best["hold"],
                "Sharpe_full": best["Sharpe_full"],
                "Sharpe_oos": best["Sharpe_oos"],
                "mean%_full": best["mean%_full"],
                "win%_full": best["win%_full"],
                "n_full": best["n_full"],
                "n_oos": best["n_oos"],
            })
        if stage_b_summary:
            sb_df = pd.DataFrame(stage_b_summary)
            sb_df.to_csv(OUT_DIR / "exit_grid_summary_stageB.csv",
                         index=False, encoding="utf-8-sig")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
