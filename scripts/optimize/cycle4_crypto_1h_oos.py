"""Cycle 4-A — Crypto 1h grid with proper IS/OOS split.

Built on top of existing round2 1h infrastructure (scripts.optimize.crypto_1h_grid),
but routes entries through cycle2_exit_grid's IS/OOS-tagged simulator.

- Universe: top 100 by 24h amount (memory protection).
- Strategies: trend_chase, trend_pullback (quiet_bottom asset-incompatible).
- score_threshold: {60, 70, 80}.
- Exit rules: hold {24h, 72h, 168h} x trail {0.05, 0.10, 0.15} x TP {0.10, 0.20, None}.
- OOS split: 2024-05-17 (2-year recent), same as Cycle 1/2.

Output:
  scripts/out/optimize/cycle_4/crypto_1h_grid.csv
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import trend_chase, trend_pullback  # noqa: E402
from scripts.optimize.cycle2_exit_grid import (  # noqa: E402
    ExitRule, simulate, summarize, COST_RT, OOS_SPLIT, SINCE_YEARS,
)

CACHE_1H = ROOT / "data" / "cache" / "crypto" / "1h"
OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "cycle_4"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TOP_N = 30  # reduced from 100 per cycle 3+4 spec (1h is heavy)
MIN_BARS_1H = 24 * 30 * 6  # 6 months
SCORE_GRID = [60, 70, 80]

EXIT_RULES = []
for hold in (24, 72, 168):
    for trail in (0.05, 0.10, 0.15):
        for tp in (0.10, 0.20, 0.0):
            tp_lbl = "none" if tp <= 0 else f"{int(tp*100)}"
            EXIT_RULES.append(ExitRule(
                name=f"h{hold}_tr{int(trail*100)}_tp{tp_lbl}",
                max_hold=hold, trailing_pct=trail, take_profit_pct=tp,
            ))

NOW = pd.Timestamp.utcnow().tz_localize(None).normalize()
SINCE = NOW - pd.DateOffset(years=3)  # 3 years of 1h data (memory)
COST = COST_RT["crypto"]
STRATEGIES = {"trend_chase": trend_chase, "trend_pullback": trend_pullback}


def select_universe(top_n: int) -> List[Path]:
    print(f"[universe] scanning amount in {CACHE_1H}", flush=True)
    scores: List[Tuple[Path, float]] = []
    t0 = time.time()
    files = sorted(CACHE_1H.glob("*.parquet"))
    for i, p in enumerate(files):
        try:
            amt = pd.read_parquet(p, columns=["amount"])["amount"]
            if len(amt) == 0:
                continue
            scores.append((p, float(amt.tail(24 * 90).mean())))
        except Exception:
            continue
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
    cols = [c for c in ("open", "high", "low", "close", "volume", "amount") if c in df.columns]
    return df[cols]


def main():
    files = select_universe(TOP_N)
    cache = {}
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
            sc_chase = trend_chase.score(df_r, {}).to_numpy().astype("float32")
            sc_pull = trend_pullback.score(df_r, {}).to_numpy().astype("float32")
        except Exception:
            n_skip += 1
            continue
        close = df["close"].astype("float64").to_numpy()
        dt_idx = pd.DatetimeIndex(df.index)
        in_period = np.asarray(dt_idx >= SINCE)
        cache[symbol] = (close, {"trend_chase": sc_chase, "trend_pullback": sc_pull},
                         dt_idx, in_period)
        if (i + 1) % 10 == 0:
            print(f"  loaded {i+1}/{len(files)} (skipped {n_skip})", flush=True)
    print(f"[load] {len(cache)} symbols cached, {time.time()-t0:.1f}s", flush=True)

    rows = []
    for strat_name in STRATEGIES:
        for th in SCORE_GRID:
            # Precompute entries
            entries = {}
            for symbol, (close, scores, dt_idx, in_period) in cache.items():
                sc = scores[strat_name]
                sig01 = (sc >= float(th)).astype("int8")
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
            n_entries = sum(len(v) for v in entries.values())
            print(f"  {strat_name} th={th}: {n_entries} entries", flush=True)

            for rule in EXIT_RULES:
                t1 = time.time()
                trades_full, trades_oos = [], []
                for symbol, ent_list in entries.items():
                    close = cache[symbol][0]
                    for pos, ent_dt in ent_list:
                        exit_pos, gross = simulate(close, pos, rule)
                        if exit_pos == pos:
                            continue
                        net = gross - COST
                        rec = {"held": exit_pos - pos, "net_ret": net}
                        trades_full.append(rec)
                        if ent_dt >= OOS_SPLIT:
                            trades_oos.append(rec)
                sf = summarize(trades_full)
                so = summarize(trades_oos)
                rows.append({
                    "strategy": strat_name, "interval": "1h",
                    "score_th": th, "rule": rule.name,
                    "trail": int(rule.trailing_pct * 100),
                    "tp": rule.tp_label,
                    "hold": rule.max_hold,
                    "n_full": sf["n"], "win%_full": sf["win%"],
                    "mean%_full": sf["mean%"], "Sharpe_full": sf["Sharpe"],
                    "n_oos": so["n"], "win%_oos": so["win%"],
                    "mean%_oos": so["mean%"], "Sharpe_oos": so["Sharpe"],
                })
                print(f"    {rule.name:<22s} full S={sf['Sharpe']:>+5.2f} n={sf['n']:>5} "
                      f"oos S={so['Sharpe']:>+5.2f} n={so['n']:>5} ({time.time()-t1:.1f}s)",
                      flush=True)

    out = pd.DataFrame(rows)
    csv = OUT_DIR / "crypto_1h_grid.csv"
    out.to_csv(csv, index=False, encoding="utf-8-sig")
    print(f"\nsaved: {csv}  ({len(out)} rows)", flush=True)

    # best per strategy (OOS Sharpe, n>=30)
    cand = out[out["n_oos"] >= 30].copy()
    if not cand.empty:
        best = (cand.sort_values("Sharpe_oos", ascending=False)
                .groupby("strategy", as_index=False)
                .first())
        best.to_csv(OUT_DIR / "crypto_1h_best.csv", index=False, encoding="utf-8-sig")
        print("\n=== best per strategy (n_oos>=30, by OOS Sharpe) ===")
        print(best[["strategy", "score_th", "rule", "n_full", "Sharpe_full",
                    "n_oos", "Sharpe_oos", "mean%_oos", "win%_oos"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
