"""Round 3 — Task 3 + Task 4 결합.

Task 3: 그룹 × regime × 전략 best 조합 → IS/OOS Sharpe
  - 각 (tier, regime, strategy) 셀에서 threshold grid 돌려 IS best 선택, OOS 측정
  - 그 다음 "통합 정책": tier 별 best 룰을 합친 전체 OOS

Task 4: pump_continuation / momentum_roc 를 whale + junk 그룹에 적용
  - signal() 은 binary state (0/1), state 0→1 전환을 entry 로
  - 동일 청산룰 (1d EXIT_1D) 적용 후 IS/OOS Sharpe

산출:
  scripts/out/optimize/round3/crypto_regime/task3_group_regime.csv
  scripts/out/optimize/round3/crypto_regime/task3_policy_summary.csv
  scripts/out/optimize/round3/crypto_regime/task4_whale_alt.csv
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

from backtest.strategies import (  # noqa: E402
    trend_chase, trend_pullback, pump_continuation, momentum_roc,
)
from scripts.optimize_grid import ExitRule, simulate  # noqa: E402
from scripts.optimize.crypto_groups import load_1d  # noqa: E402
from scripts.optimize.crypto_regime_adaptive import (  # noqa: E402
    build_btc_regime, load_1w, summarize,
    IS_START, IS_END, OOS_START, OOS_END, IS_YEARS, OOS_YEARS, COST,
    EXIT_1D_CHASE, EXIT_1D_PULL, EXIT_1W_CHASE, EXIT_1W_PULL,
)

CACHE_1D = ROOT / "data" / "cache" / "crypto" / "1d"
OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "round3" / "crypto_regime"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CLS_PARQUET = ROOT / "data" / "cache" / "crypto" / "classification.parquet"


def load_classification() -> pd.DataFrame:
    df = pd.read_parquet(CLS_PARQUET)
    if "tier_final" in df.columns:
        df = df.rename(columns={"tier_final": "tier"})
    return df[["symbol", "tier"]]


# --- Task 3 ----------------------------------------------------------------
def build_per_sym_1d(min_bars: int = 200):
    """Build (close, sc_c, sc_p, idx) per symbol — 1d only."""
    per_sym = {}
    files = sorted(CACHE_1D.glob("*.parquet"))
    t0 = time.time()
    for i, p in enumerate(files):
        try:
            df = load_1d(p)
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
    print(f"  1d total: {len(per_sym)} ({time.time()-t0:.1f}s)", flush=True)
    return per_sym


def trades_for(per_sym, symbols, score_idx, th, rule, regime=None, regime_eq=None):
    """regime_eq: None → no gate, 1 → only when reg==1, 0 → only when reg==0."""
    is_rets, oos_rets = [], []
    for sym in symbols:
        v = per_sym.get(sym)
        if v is None:
            continue
        close, sc_c, sc_p, idx = v
        sc = sc_c if score_idx == 1 else sc_p
        sig01 = (sc >= float(th)).astype("int8")
        diff = np.diff(sig01.astype("int16"), prepend=0)
        entries = np.where(diff == 1)[0]
        if regime is not None and regime_eq is not None:
            try:
                reg = regime.reindex(idx).fillna(method="ffill").fillna(0).to_numpy().astype("int8")
            except Exception:
                continue
            entries = [pos for pos in entries if pos < len(reg) and reg[pos] == regime_eq]
        for pos in entries:
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


def task3():
    print("\n========== TASK 3: group x regime ==========", flush=True)
    cls = load_classification()
    sym_by_tier = (
        cls[cls["tier"].isin(["trend", "follower", "whale", "junk"])]
        .groupby("tier")["symbol"].apply(list).to_dict()
    )
    print(f"[tier] {{k: len(v) for k, v in sym_by_tier.items()}} = "
          f"{ {k: len(v) for k, v in sym_by_tier.items()} }", flush=True)

    btc_above = build_btc_regime(load_1d, span=200)
    per_sym = build_per_sym_1d()

    # 셀: (tier, regime ∈ {above, below}) → 두 전략 × th grid
    rows = []
    STRATS = [("trend_chase", 1, EXIT_1D_CHASE), ("trend_pullback", 2, EXIT_1D_PULL)]
    TH_GRID = [60, 70, 80, 90]

    for tier, syms in sym_by_tier.items():
        for regime_eq, regime_name in [(1, "above"), (0, "below")]:
            for strat_name, idx, rule in STRATS:
                for th in TH_GRID:
                    is_r, oos_r = trades_for(per_sym, syms, idx, th, rule,
                                             regime=btc_above, regime_eq=regime_eq)
                    is_s = summarize(is_r, IS_YEARS)
                    oos_s = summarize(oos_r, OOS_YEARS)
                    rows.append({
                        "tier": tier, "regime": regime_name,
                        "strategy": strat_name, "score_th": th,
                        "IS_n": is_s["n"], "IS_Sharpe": is_s["Sharpe_ann"],
                        "IS_mean%": is_s["mean%"],
                        "OOS_n": oos_s["n"], "OOS_Sharpe": oos_s["Sharpe_ann"],
                        "OOS_mean%": oos_s["mean%"], "OOS_PF": oos_s["PF"],
                    })
                    print(f"  {tier:>9s} {regime_name:>5s} {strat_name:<15s} th={th}  "
                          f"IS n={is_s['n']:>4} S={is_s['Sharpe_ann']:>+5.2f}  "
                          f"OOS n={oos_s['n']:>4} S={oos_s['Sharpe_ann']:>+5.2f}",
                          flush=True)

    grid = pd.DataFrame(rows)
    grid.to_csv(OUT_DIR / "task3_group_regime.csv", index=False, encoding="utf-8-sig")
    print(f"saved: {OUT_DIR / 'task3_group_regime.csv'}", flush=True)

    # 통합 정책: 각 (tier, regime) 의 IS best 룰 선택 → OOS 합산
    # IS_n >= 20 + IS_Sharpe > 0 만 후보
    cand = grid[(grid["IS_n"] >= 20) & (grid["IS_Sharpe"] > 0)].copy()
    policy = (cand.sort_values("IS_Sharpe", ascending=False)
              .groupby(["tier", "regime"]).head(1)
              .sort_values(["tier", "regime"]))
    policy_out = OUT_DIR / "task3_policy_per_cell.csv"
    policy.to_csv(policy_out, index=False, encoding="utf-8-sig")
    print(f"saved: {policy_out}", flush=True)

    # 모든 셀의 OOS rets 모아서 통합 정책 OOS Sharpe
    print("\n=== Aggregate combined policy OOS ===", flush=True)
    all_is, all_oos = [], []
    for _, r in policy.iterrows():
        syms = sym_by_tier[r["tier"]]
        idx = 1 if r["strategy"] == "trend_chase" else 2
        rule = EXIT_1D_CHASE if r["strategy"] == "trend_chase" else EXIT_1D_PULL
        regime_eq = 1 if r["regime"] == "above" else 0
        is_r, oos_r = trades_for(per_sym, syms, idx, r["score_th"], rule,
                                 regime=btc_above, regime_eq=regime_eq)
        all_is.extend(is_r.tolist())
        all_oos.extend(oos_r.tolist())
    is_s = summarize(np.array(all_is), IS_YEARS)
    oos_s = summarize(np.array(all_oos), OOS_YEARS)
    print(f"  COMBINED  IS n={is_s['n']:>5} S={is_s['Sharpe_ann']:+.2f}  "
          f"OOS n={oos_s['n']:>5} S={oos_s['Sharpe_ann']:+.2f} mean={oos_s['mean%']:+.2f}% "
          f"PF={oos_s['PF']:.2f} MDD={oos_s['MDD%']:.1f}%", flush=True)

    pd.DataFrame([{
        "scope": "combined_policy",
        "IS_n": is_s["n"], "IS_Sharpe": is_s["Sharpe_ann"], "IS_mean%": is_s["mean%"],
        "OOS_n": oos_s["n"], "OOS_Sharpe": oos_s["Sharpe_ann"], "OOS_mean%": oos_s["mean%"],
        "OOS_PF": oos_s["PF"], "OOS_MDD%": oos_s["MDD%"],
    }]).to_csv(OUT_DIR / "task3_policy_summary.csv", index=False, encoding="utf-8-sig")


# --- Task 4 ----------------------------------------------------------------
def task4_state_trades(strat_module, params_grid, per_sym_state, symbols, rule, tag: str):
    """state signal (0/1) 의 0→1 전환을 entry 로 잡고 simulate."""
    is_rets, oos_rets = [], []
    for sym in symbols:
        v = per_sym_state.get(sym)
        if v is None:
            continue
        close, state, idx = v
        diff = np.diff(state.astype("int16"), prepend=0)
        entries = np.where(diff == 1)[0]
        for pos in entries:
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


def build_per_sym_state(strat_module, params: dict, min_bars: int = 200):
    """Build (close, state, idx) per symbol with given state-signal strategy."""
    per_sym = {}
    files = sorted(CACHE_1D.glob("*.parquet"))
    t0 = time.time()
    p = {**strat_module.DEFAULT_PARAMS, **params, "btc_filter": False,
         "weekly_filter": False}
    for i, p_file in enumerate(files):
        try:
            df = load_1d(p_file)
        except Exception:
            continue
        if df.empty or len(df) < min_bars:
            continue
        try:
            st = strat_module.signal(df, p).to_numpy().astype("int8")
        except Exception:
            continue
        close = df["close"].astype("float64").to_numpy()
        per_sym[p_file.stem] = (close, st, df.index)
        if (i + 1) % 100 == 0:
            print(f"  [{strat_module.NAME}] scored {i+1}/{len(files)} "
                  f"({time.time()-t0:.1f}s)", flush=True)
    print(f"  [{strat_module.NAME}] total: {len(per_sym)} ({time.time()-t0:.1f}s)", flush=True)
    return per_sym


def task4():
    print("\n========== TASK 4: pump_continuation / momentum_roc on whale+junk ==========",
          flush=True)
    cls = load_classification()
    sym_by_tier = (
        cls[cls["tier"].isin(["trend", "follower", "whale", "junk"])]
        .groupby("tier")["symbol"].apply(list).to_dict()
    )

    # pump_continuation 은 기본 1H 권장이지만 1D 적용 → impulse_bars 등 1D 스케일로 축소
    PC_PARAMS = [
        {"impulse_bars": 5, "impulse_pct": 0.20, "retrace_max": 0.50,
         "cool_max": 5, "trigger_n": 3, "vol_n": 20, "vol_mul": 1.5,
         "exit_ema": 20, "max_hold": 30},
        {"impulse_bars": 7, "impulse_pct": 0.30, "retrace_max": 0.40,
         "cool_max": 7, "trigger_n": 4, "vol_n": 20, "vol_mul": 2.0,
         "exit_ema": 20, "max_hold": 30},
    ]
    MR_PARAMS = [
        {"roc_n": 30, "roc_min": 0.10, "roc_short": 5, "accel_n": 10,
         "trend_ema": 100, "exit_ema": 20, "max_hold": 60, "sl_pct": -0.10},
        {"roc_n": 30, "roc_min": 0.20, "roc_short": 5, "accel_n": 10,
         "trend_ema": 100, "exit_ema": 20, "max_hold": 60, "sl_pct": -0.10},
    ]

    rule = EXIT_1D_CHASE  # 동일 청산룰로 비교

    rows = []
    for strat_mod, param_list, tag in [
        (pump_continuation, PC_PARAMS, "PC"),
        (momentum_roc, MR_PARAMS, "MR"),
    ]:
        for params in param_list:
            per_sym_st = build_per_sym_state(strat_mod, params, min_bars=200)
            for tier in ["whale", "junk", "trend"]:
                syms = sym_by_tier[tier]
                is_r, oos_r = task4_state_trades(
                    strat_mod, params, per_sym_st, syms, rule, tag,
                )
                is_s = summarize(is_r, IS_YEARS)
                oos_s = summarize(oos_r, OOS_YEARS)
                row = {
                    "strategy": strat_mod.NAME,
                    "tier": tier,
                    "params": str({k: params[k] for k in sorted(params)}),
                    "rule": rule.name,
                    "IS_n": is_s["n"], "IS_Sharpe": is_s["Sharpe_ann"],
                    "IS_mean%": is_s["mean%"],
                    "OOS_n": oos_s["n"], "OOS_Sharpe": oos_s["Sharpe_ann"],
                    "OOS_mean%": oos_s["mean%"], "OOS_PF": oos_s["PF"],
                    "OOS_MDD%": oos_s["MDD%"],
                }
                rows.append(row)
                print(f"  {strat_mod.NAME:<18s} {tier:>5s}  "
                      f"IS n={is_s['n']:>5} S={is_s['Sharpe_ann']:>+5.2f}  "
                      f"OOS n={oos_s['n']:>5} S={oos_s['Sharpe_ann']:>+5.2f} "
                      f"mean={oos_s['mean%']:>+5.2f}%", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_DIR / "task4_whale_alt.csv", index=False, encoding="utf-8-sig")
    print(f"saved: {OUT_DIR / 'task4_whale_alt.csv'}", flush=True)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=["3", "4", "both"], default="both")
    args = ap.parse_args()
    if args.task in ("3", "both"):
        task3()
    if args.task in ("4", "both"):
        task4()


if __name__ == "__main__":
    main()
