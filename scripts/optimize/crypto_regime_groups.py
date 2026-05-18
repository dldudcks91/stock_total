"""Round 3 — Crypto: classification 그룹별 IS/OOS Sharpe.

기존 Round 2 의 단순 task2_classification.csv (trend/follower/whale/junk) 또는
정밀 data/cache/crypto/classification.parquet (있으면 우선) 둘 다 지원.

각 그룹 × {1d, 1w} × {chase, pullback} × th{60,70,80,90} 그리드 IS/OOS 평가.

IS  : 2022-01-01 ~ 2024-12-31
OOS : 2025-01-01 ~ 2026-05-17

산출:
  scripts/out/optimize/round3/crypto_regime/task1_group_grid.csv
  scripts/out/optimize/round3/crypto_regime/task1_group_best.csv
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
from scripts.optimize.crypto_groups import load_1d  # noqa: E402

CACHE_1D = ROOT / "data" / "cache" / "crypto" / "1d"
ROUND2_DIR = ROOT / "scripts" / "out" / "optimize" / "round2" / "crypto"
OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "round3" / "crypto_regime"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CLS_PARQUET = ROOT / "data" / "cache" / "crypto" / "classification.parquet"
CLS_CSV_FALLBACK = ROUND2_DIR / "task2_classification.csv"

IS_START = pd.Timestamp("2022-01-01")
IS_END = pd.Timestamp("2024-12-31")
OOS_START = pd.Timestamp("2025-01-01")
OOS_END = pd.Timestamp("2026-05-17")
IS_YEARS = (IS_END - IS_START).days / 365.0
OOS_YEARS = (OOS_END - OOS_START).days / 365.0

COST = 0.002

EXIT_1D = ExitRule(
    "hold_60d_trail20_TP30", max_hold=60, trailing_pct=0.20, take_profit_pct=0.30
)
EXIT_1W = ExitRule("hold_8w_trail15", max_hold=8, trailing_pct=0.15)


def load_1w(path: Path) -> pd.DataFrame:
    df = load_1d(path)
    if df.empty:
        return df
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    if "amount" in df.columns:
        agg["amount"] = "sum"
    return df.resample("W-MON", label="left", closed="left").agg(agg).dropna()


def load_classification() -> pd.DataFrame:
    """Returns DataFrame with at least: symbol, tier4 columns."""
    if CLS_PARQUET.exists():
        df = pd.read_parquet(CLS_PARQUET)
        if "tier_final" in df.columns:
            df = df.rename(columns={"tier_final": "tier"})
        elif "tier_detail" in df.columns:
            from data.classification import GROUP4_MAP
            df["tier"] = df["tier_detail"].map(GROUP4_MAP).fillna("junk")
        print(f"[cls] precise classification from parquet: {len(df)} rows", flush=True)
    else:
        df = pd.read_csv(CLS_CSV_FALLBACK)
        print(f"[cls] FALLBACK CSV: {len(df)} rows", flush=True)
    if "symbol" not in df.columns:
        df = df.reset_index().rename(columns={"index": "symbol"})
    df["tier"] = df["tier"].astype(str)
    print(f"[cls] tier counts: {df['tier'].value_counts().to_dict()}", flush=True)
    return df[["symbol", "tier"]]


def summarize(rets: np.ndarray, years: float) -> dict:
    if len(rets) == 0:
        return {"n": 0, "win%": 0.0, "mean%": 0.0,
                "Sharpe_ann": 0.0, "PF": 0.0, "MDD%": 0.0}
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
    return {"n": int(len(rets)), "win%": round(win, 1), "mean%": round(mean, 2),
            "Sharpe_ann": round(sharpe, 2), "PF": round(pf, 2), "MDD%": round(dd, 1)}


def build_per_sym(loader, min_bars: int, files):
    """단일 패스로 모든 심볼 close + 두 score + index 저장."""
    per_sym = {}
    t0 = time.time()
    for i, p in enumerate(files):
        try:
            df = loader(p)
        except Exception:
            continue
        if df.empty or len(df) < min_bars:
            continue
        df_r = df.reset_index(drop=True)
        try:
            sc_c = trend_chase.score(df_r, {}).to_numpy().astype("float32")
            sc_p = trend_pullback.score(df_r, {}).to_numpy().astype("float32")
        except Exception:
            continue
        close = df["close"].astype("float64").to_numpy()
        per_sym[p.stem] = (close, sc_c, sc_p, df.index)
        if (i + 1) % 100 == 0:
            print(f"  scored {i+1}/{len(files)} ({time.time()-t0:.1f}s)", flush=True)
    print(f"  total scored: {len(per_sym)} ({time.time()-t0:.1f}s)", flush=True)
    return per_sym


def collect_trades(per_sym, symbols, strat_idx: int, th: float, rule: ExitRule):
    """Returns (is_rets, oos_rets) arrays."""
    is_rets, oos_rets = [], []
    for sym in symbols:
        v = per_sym.get(sym)
        if v is None:
            continue
        close, sc_c, sc_p, idx = v
        sc = sc_c if strat_idx == 1 else sc_p
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
    return np.array(is_rets), np.array(oos_rets)


def main():
    cls = load_classification()
    sym_by_tier = (
        cls[cls["tier"].isin(["trend", "follower", "whale", "junk"])]
        .groupby("tier")["symbol"].apply(list).to_dict()
    )
    print(f"[groups] sizes: { {k: len(v) for k, v in sym_by_tier.items()} }", flush=True)

    INTERVALS = {
        "1d": (load_1d, 200, EXIT_1D),
        "1w": (load_1w, 60, EXIT_1W),
    }

    rows = []
    for iv, (loader, min_bars, rule) in INTERVALS.items():
        print(f"\n=== interval={iv} ===", flush=True)
        files = sorted(CACHE_1D.glob("*.parquet"))
        per_sym = build_per_sym(loader, min_bars, files)
        for tier, symbols in sym_by_tier.items():
            for strat_name, strat_idx in (("trend_chase", 1), ("trend_pullback", 2)):
                for th in [60, 70, 80, 90]:
                    is_r, oos_r = collect_trades(per_sym, symbols, strat_idx, th, rule)
                    is_s = summarize(is_r, IS_YEARS)
                    oos_s = summarize(oos_r, OOS_YEARS)
                    row = {
                        "tier": tier, "interval": iv, "strategy": strat_name,
                        "score_th": th, "rule": rule.name,
                        "IS_n": is_s["n"], "IS_win%": is_s["win%"],
                        "IS_mean%": is_s["mean%"], "IS_Sharpe": is_s["Sharpe_ann"],
                        "IS_PF": is_s["PF"], "IS_MDD%": is_s["MDD%"],
                        "OOS_n": oos_s["n"], "OOS_win%": oos_s["win%"],
                        "OOS_mean%": oos_s["mean%"], "OOS_Sharpe": oos_s["Sharpe_ann"],
                        "OOS_PF": oos_s["PF"], "OOS_MDD%": oos_s["MDD%"],
                    }
                    rows.append(row)
                    print(f"  {tier:>9s} {iv} {strat_name:<15s} th={th}  "
                          f"IS n={is_s['n']:>4} S={is_s['Sharpe_ann']:>+5.2f}  "
                          f"OOS n={oos_s['n']:>4} S={oos_s['Sharpe_ann']:>+5.2f}",
                          flush=True)

    grid = pd.DataFrame(rows)
    grid_out = OUT_DIR / "task1_group_grid.csv"
    grid.to_csv(grid_out, index=False, encoding="utf-8-sig")
    print(f"\nsaved: {grid_out}", flush=True)

    # Best per (tier, interval) based on OOS_Sharpe (only if IS positive — overfit guard)
    valid = grid[grid["IS_Sharpe"] > 0].copy()
    if not valid.empty:
        best = (
            valid.sort_values("OOS_Sharpe", ascending=False)
            .groupby(["tier", "interval"]).head(1)
            .sort_values(["tier", "interval"])
        )
    else:
        best = grid.sort_values("OOS_Sharpe", ascending=False).groupby(["tier", "interval"]).head(1)
    best_out = OUT_DIR / "task1_group_best.csv"
    best.to_csv(best_out, index=False, encoding="utf-8-sig")
    print(f"saved: {best_out}", flush=True)
    print("\n=== Best per (tier, interval) by OOS Sharpe ===")
    print(best[["tier", "interval", "strategy", "score_th",
                "IS_Sharpe", "IS_n", "OOS_Sharpe", "OOS_n"]].to_string(index=False))


if __name__ == "__main__":
    main()
