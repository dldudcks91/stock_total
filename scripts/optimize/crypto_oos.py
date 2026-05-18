"""Round 2 — Crypto OOS 검증.

IS  : 2022-01-01 ~ 2024-12-31 (3년)
OOS : 2025-01-01 ~ 2026-05-17 (현재까지, ~1.4년)

평가:
  - chase 1d th=60 (Round 1 best)
  - pullback 1d th=70 (Round 1 best)
  - pullback 1w th=60 (Round 1 best)
  - chase 1h best (Task 1 결과: th=60, hold_168h_trail20)
  - pullback 1h best (Task 1: th=75, hold_336h_trail20_cut5h)

산출:
  scripts/out/optimize/round2/crypto/task4_oos.csv
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
from scripts.optimize_grid import ExitRule, simulate  # noqa: E402
from scripts.optimize.crypto_groups import load_1d, load_4h_from_1h  # noqa: E402
from scripts.optimize.crypto_1h_grid import load_1h  # noqa: E402

CACHE_1H = ROOT / "data" / "cache" / "crypto" / "1h"
CACHE_1D = ROOT / "data" / "cache" / "crypto" / "1d"
OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "round2" / "crypto"
OUT_DIR.mkdir(parents=True, exist_ok=True)

IS_START = pd.Timestamp("2022-01-01")
IS_END   = pd.Timestamp("2024-12-31")
OOS_START = pd.Timestamp("2025-01-01")
OOS_END   = pd.Timestamp("2026-05-17")

IS_YEARS = (IS_END - IS_START).days / 365.0
OOS_YEARS = (OOS_END - OOS_START).days / 365.0

COST = 0.002

# 1w 리샘플
def load_1w(path: Path) -> pd.DataFrame:
    df = load_1d(path)
    if df.empty:
        return df
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    if "amount" in df.columns:
        agg["amount"] = "sum"
    return df.resample("W-MON", label="left", closed="left").agg(agg).dropna()


CONFIGS = [
    # (strategy, interval, th, ExitRule, loader)
    ("trend_chase",    "1d", 60,
     ExitRule("hold_60d_trail20_TP30", max_hold=60, trailing_pct=0.20, take_profit_pct=0.30),
     load_1d, 80),
    ("trend_pullback", "1d", 70,
     ExitRule("hold_60d_trail15_cut3d", max_hold=60, trailing_pct=0.15,
              cut_short_at=3, cut_short_thr=-5),
     load_1d, 80),
    ("trend_pullback", "1w", 60,
     ExitRule("hold_8w_trail15", max_hold=8, trailing_pct=0.15),
     load_1w, 30),
    ("trend_chase",    "1h", 60,
     ExitRule("hold_168h_trail20", max_hold=168, trailing_pct=0.20),
     load_1h, 24 * 90),
    ("trend_pullback", "1h", 75,
     ExitRule("hold_336h_trail20_cut5h", max_hold=336, trailing_pct=0.20,
              cut_short_at=5, cut_short_thr=-3),
     load_1h, 24 * 90),
]

STRATS = {"trend_chase": trend_chase, "trend_pullback": trend_pullback}


def summarize(rets: np.ndarray, years: float) -> dict:
    if len(rets) == 0:
        return {"n": 0, "win%": 0, "mean%": 0, "Sharpe_ann": 0, "PF": 0, "MDD%": 0}
    win = float((rets > 0).mean() * 100)
    mean = float(rets.mean() * 100)
    eq = np.cumprod(1.0 + rets)
    peak = np.maximum.accumulate(eq)
    dd = float((eq / peak - 1.0).min() * 100)
    if rets.std() > 0:
        sharpe = float(rets.mean() / rets.std() * np.sqrt(len(rets) / years))
    else:
        sharpe = 0.0
    gains = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = float(gains / losses) if losses > 0 else 99.99
    return {"n": len(rets), "win%": round(win, 1), "mean%": round(mean, 2),
            "Sharpe_ann": round(sharpe, 2), "PF": round(pf, 2),
            "MDD%": round(dd, 1)}


def run_config(strat_name, iv, th, rule, loader, min_bars):
    strat = STRATS[strat_name]
    cache_dir = CACHE_1H if iv == "1h" else CACHE_1D
    files = sorted(cache_dir.glob("*.parquet"))
    is_rets = []
    oos_rets = []
    t0 = time.time()
    n_proc = 0
    for p in files:
        try:
            df = loader(p)
        except Exception:
            continue
        if df.empty or len(df) < min_bars:
            continue
        df_r = df.reset_index(drop=True)
        try:
            sc = strat.score(df_r, {}).to_numpy().astype("float32")
        except Exception:
            continue
        close = df["close"].astype("float64").to_numpy()
        idx = df.index
        sig01 = (sc >= float(th)).astype("int8")
        diff = np.diff(sig01.astype("int16"), prepend=0)
        enter_mask = (diff == 1)
        positions = np.where(enter_mask)[0]
        for pos in positions:
            if pos >= len(close) - 1:
                continue
            entry_dt = idx[pos]
            exit_pos, gross = simulate(close, int(pos), rule)
            if exit_pos == pos:
                continue
            net = gross - COST
            if IS_START <= entry_dt <= IS_END:
                is_rets.append(net)
            elif OOS_START <= entry_dt <= OOS_END:
                oos_rets.append(net)
        n_proc += 1
    print(f"  [{strat_name}/{iv}/th{th}] processed {n_proc} symbols "
          f"in {time.time()-t0:.1f}s", flush=True)
    return np.array(is_rets), np.array(oos_rets)


def main():
    rows = []
    for cfg in CONFIGS:
        strat_name, iv, th, rule, loader, min_bars = cfg
        print(f"\n=== {strat_name} / {iv} / th={th} ===", flush=True)
        is_r, oos_r = run_config(*cfg)
        is_s = summarize(is_r, IS_YEARS)
        oos_s = summarize(oos_r, OOS_YEARS)
        rows.append({
            "strategy": strat_name, "interval": iv, "score_th": th, "rule": rule.name,
            "IS_n": is_s["n"], "IS_win%": is_s["win%"], "IS_mean%": is_s["mean%"],
            "IS_Sharpe": is_s["Sharpe_ann"], "IS_PF": is_s["PF"], "IS_MDD%": is_s["MDD%"],
            "OOS_n": oos_s["n"], "OOS_win%": oos_s["win%"], "OOS_mean%": oos_s["mean%"],
            "OOS_Sharpe": oos_s["Sharpe_ann"], "OOS_PF": oos_s["PF"], "OOS_MDD%": oos_s["MDD%"],
        })
        print(f"  IS:  n={is_s['n']:>5} win={is_s['win%']:.1f}% mean={is_s['mean%']:+.2f}% "
              f"Sharpe={is_s['Sharpe_ann']:+.2f} PF={is_s['PF']:.2f}", flush=True)
        print(f"  OOS: n={oos_s['n']:>5} win={oos_s['win%']:.1f}% mean={oos_s['mean%']:+.2f}% "
              f"Sharpe={oos_s['Sharpe_ann']:+.2f} PF={oos_s['PF']:.2f}", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_DIR / "task4_oos.csv", index=False, encoding="utf-8-sig")
    print(f"\nsaved: {OUT_DIR / 'task4_oos.csv'}", flush=True)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
