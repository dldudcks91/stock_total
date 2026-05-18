"""Round 3 — Crypto regime-adaptive 통합 전략.

BTC 매크로 게이트 (close > EMA200) 기반:
  - 강세 (above): trend_chase 만 진입
  - 약세 (below): trend_pullback 만 진입

평가 모드 3종:
  - baseline_chase   : chase 1d th=60 (BTC 게이트 X)
  - baseline_pullback: pullback 1d th=70 (BTC 게이트 X)
  - regime_adaptive  : 위 정책

각 모드 × (th_chase, th_pullback) grid × {1d, 1w}
IS/OOS Sharpe + 진입 수.

룩어헤드 금지: BTC EMA200 은 t-1 정보만 (실제 코드: EMA(close) 의 t 봉 값은
같은 시각의 close 정보를 일부 포함하나, .shift(1) 으로 한 봉 전 값을 사용).

산출:
  scripts/out/optimize/round3/crypto_regime/task2_regime_grid.csv
  scripts/out/optimize/round3/crypto_regime/task2_regime_best.csv
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
OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "round3" / "crypto_regime"
OUT_DIR.mkdir(parents=True, exist_ok=True)

IS_START = pd.Timestamp("2022-01-01")
IS_END = pd.Timestamp("2024-12-31")
OOS_START = pd.Timestamp("2025-01-01")
OOS_END = pd.Timestamp("2026-05-17")
IS_YEARS = (IS_END - IS_START).days / 365.0
OOS_YEARS = (OOS_END - OOS_START).days / 365.0

COST = 0.002

EXIT_1D_CHASE = ExitRule(
    "hold_60d_trail20_TP30", max_hold=60, trailing_pct=0.20, take_profit_pct=0.30
)
EXIT_1D_PULL = ExitRule(
    "hold_60d_trail15_cut3d", max_hold=60, trailing_pct=0.15,
    cut_short_at=3, cut_short_thr=-5,
)
EXIT_1W_CHASE = ExitRule("hold_8w_trail20", max_hold=8, trailing_pct=0.20, take_profit_pct=0.30)
EXIT_1W_PULL = ExitRule("hold_8w_trail15", max_hold=8, trailing_pct=0.15)


def load_1w(path: Path) -> pd.DataFrame:
    df = load_1d(path)
    if df.empty:
        return df
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    if "amount" in df.columns:
        agg["amount"] = "sum"
    return df.resample("W-MON", label="left", closed="left").agg(agg).dropna()


def build_btc_regime(loader, span: int = 200) -> pd.Series:
    """BTC close 기준 above_ema200 시계열. shift(1) 으로 룩어헤드 방지."""
    btc = loader(CACHE_1D / "BTCUSDT.parquet")
    close = btc["close"].astype("float64")
    ema = close.ewm(span=span, adjust=False).mean()
    above = (close > ema).astype("int8")
    # shift(1): t 시점 시그널 → t 봉 진입 시 t-1 EMA 와 t-1 close 비교
    above = above.shift(1).fillna(0).astype("int8")
    return above


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


def build_per_sym(loader, min_bars: int):
    per_sym = {}
    files = sorted(CACHE_1D.glob("*.parquet"))
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


def run_mode(per_sym, regime_above, mode: str,
             th_c: float, th_p: float,
             exit_c: ExitRule, exit_p: ExitRule):
    """Returns (is_rets, oos_rets) for a (mode, th_c, th_p) config."""
    is_rets, oos_rets = [], []
    for sym, (close, sc_c, sc_p, idx) in per_sym.items():
        try:
            reg = regime_above.reindex(idx).fillna(method="ffill").fillna(0).to_numpy().astype("int8")
        except Exception:
            continue
        sig_c = (sc_c >= float(th_c)).astype("int8")
        sig_p = (sc_p >= float(th_p)).astype("int8")
        d_c = np.diff(sig_c.astype("int16"), prepend=0)
        d_p = np.diff(sig_p.astype("int16"), prepend=0)

        if mode == "baseline_chase":
            entries = [(pos, "c") for pos in np.where(d_c == 1)[0]]
        elif mode == "baseline_pullback":
            entries = [(pos, "p") for pos in np.where(d_p == 1)[0]]
        elif mode == "regime_adaptive":
            # chase 진입은 strict above; pullback 진입은 below
            entries = []
            for pos in np.where(d_c == 1)[0]:
                if pos < len(reg) and reg[pos] == 1:
                    entries.append((pos, "c"))
            for pos in np.where(d_p == 1)[0]:
                if pos < len(reg) and reg[pos] == 0:
                    entries.append((pos, "p"))
        elif mode == "both_always":
            # 둘 다 항상 진입 (게이트 X), 비교용
            entries = [(pos, "c") for pos in np.where(d_c == 1)[0]] + \
                      [(pos, "p") for pos in np.where(d_p == 1)[0]]
        else:
            raise ValueError(f"unknown mode {mode}")

        for pos, kind in entries:
            if pos >= len(close) - 1:
                continue
            rule = exit_c if kind == "c" else exit_p
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
    print("[load 1d btc regime]", flush=True)
    btc_above_1d = build_btc_regime(load_1d, span=200)
    btc_above_1w = build_btc_regime(load_1w, span=40)
    print(f"  1d above share: {btc_above_1d.mean():.2f}", flush=True)
    print(f"  1w above share: {btc_above_1w.mean():.2f}", flush=True)

    INTERVALS = {
        "1d": (load_1d, 200, EXIT_1D_CHASE, EXIT_1D_PULL, btc_above_1d),
        "1w": (load_1w, 60, EXIT_1W_CHASE, EXIT_1W_PULL, btc_above_1w),
    }

    GRID = [
        # (th_chase, th_pullback)
        (60, 60), (60, 70), (60, 80),
        (70, 60), (70, 70), (70, 80),
        (80, 70), (80, 80),
    ]
    MODES = ["baseline_chase", "baseline_pullback", "regime_adaptive", "both_always"]

    rows = []
    for iv, (loader, min_bars, exit_c, exit_p, regime) in INTERVALS.items():
        print(f"\n=== interval={iv} ===", flush=True)
        per_sym = build_per_sym(loader, min_bars)
        for mode in MODES:
            for th_c, th_p in GRID:
                # baseline_chase 는 th_p 미사용, dedupe 위해 th_p 가 60 일 때만
                if mode == "baseline_chase" and th_p != 60:
                    continue
                if mode == "baseline_pullback" and th_c != 60:
                    continue
                is_r, oos_r = run_mode(per_sym, regime, mode, th_c, th_p, exit_c, exit_p)
                is_s = summarize(is_r, IS_YEARS)
                oos_s = summarize(oos_r, OOS_YEARS)
                rows.append({
                    "interval": iv, "mode": mode,
                    "th_chase": th_c, "th_pullback": th_p,
                    "IS_n": is_s["n"], "IS_win%": is_s["win%"],
                    "IS_mean%": is_s["mean%"], "IS_Sharpe": is_s["Sharpe_ann"],
                    "IS_PF": is_s["PF"], "IS_MDD%": is_s["MDD%"],
                    "OOS_n": oos_s["n"], "OOS_win%": oos_s["win%"],
                    "OOS_mean%": oos_s["mean%"], "OOS_Sharpe": oos_s["Sharpe_ann"],
                    "OOS_PF": oos_s["PF"], "OOS_MDD%": oos_s["MDD%"],
                })
                print(f"  {iv} {mode:<18s} thC={th_c} thP={th_p}  "
                      f"IS n={is_s['n']:>5} S={is_s['Sharpe_ann']:>+5.2f}  "
                      f"OOS n={oos_s['n']:>5} S={oos_s['Sharpe_ann']:>+5.2f} "
                      f"mean={oos_s['mean%']:>+5.2f}%", flush=True)

    grid = pd.DataFrame(rows)
    grid_out = OUT_DIR / "task2_regime_grid.csv"
    grid.to_csv(grid_out, index=False, encoding="utf-8-sig")
    print(f"\nsaved: {grid_out}", flush=True)

    # Best per (interval, mode) by OOS Sharpe, IS positive only
    valid = grid[(grid["IS_Sharpe"] > 0) & (grid["OOS_n"] >= 20)].copy()
    if not valid.empty:
        best = (valid.sort_values("OOS_Sharpe", ascending=False)
                .groupby(["interval", "mode"]).head(1)
                .sort_values(["interval", "mode"]))
    else:
        best = grid.sort_values("OOS_Sharpe", ascending=False).groupby(["interval", "mode"]).head(1)
    best_out = OUT_DIR / "task2_regime_best.csv"
    best.to_csv(best_out, index=False, encoding="utf-8-sig")
    print(f"saved: {best_out}", flush=True)
    print("\n=== Best per (interval, mode) by OOS Sharpe ===")
    print(best[["interval", "mode", "th_chase", "th_pullback",
                "IS_Sharpe", "IS_n", "OOS_Sharpe", "OOS_n", "OOS_mean%"]].to_string(index=False))


if __name__ == "__main__":
    main()
