"""Cycle 2~4 압축본 — 청산 미세 그리드 확장 + 보조 게이트 진단 + Crypto 1h 프로브.

원칙:
  - 라이브 fetch 절대 금지. universe = 캐시 stem 기반.
  - cycle1_oos_micro.py 의 패턴/모듈 재사용.
  - 룩어헤드 금지 (signal t -> 체결 t+1; simulate 가 entry_pos+1 부터 평가).

산출:
  A. 청산 미세 그리드 (40 combos × 3):
       deep/grids/cycle2_exit_micro_us_pullback.csv
       deep/grids/cycle2_exit_micro_kr_chase.csv
       deep/grids/cycle2_exit_micro_us_chase.csv
  B. 보조 게이트 진단 (KR/US trend_pullback 1d):
       deep/grids/cycle3_gates_kr_pullback.csv
       deep/grids/cycle3_gates_us_pullback.csv
  C. Crypto 1h 프로브:
       deep/grids/cycle4_crypto_1h_probe.csv
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import trend_chase, trend_pullback, quiet_bottom  # noqa: E402
from scripts.optimize_grid import ExitRule, simulate, COST_RT  # noqa: E402
from scripts.trend_strategies.forward_returns import (  # noqa: E402
    load_stock, load_crypto,
    KR_DIR, US_DIR, CRYPTO_1H_DIR, CRYPTO_1D_DIR,
)

OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "deep" / "grids"
OUT_DIR.mkdir(parents=True, exist_ok=True)

STRATEGIES = {
    "trend_chase": trend_chase,
    "trend_pullback": trend_pullback,
    "quiet_bottom": quiet_bottom,
}

UNIVERSE_TOP = 300
MIN_BARS = {"1h": 500, "1d": 80, "1w": 30}

TRAIN_START = pd.Timestamp("2020-05-17")
TEST_END    = pd.Timestamp("2026-05-17")


# ---------------------------------------------------------------------------
# Universe — cache-only (mirror cycle1_oos_micro)
# ---------------------------------------------------------------------------
def kr_universe_cached(top_n: int) -> set:
    cache_stems = {p.stem for p in KR_DIR.glob("*.parquet") if not p.stem.startswith("_")}
    snap_path = KR_DIR / "_live_snapshot.parquet"
    if snap_path.exists():
        try:
            snap = pd.read_parquet(snap_path)
            snap = snap.dropna(subset=["marketValue"]).sort_values("marketValue", ascending=False)
            ranked = snap["itemCode"].astype(str).tolist()
            picked = [c for c in ranked if c in cache_stems][:top_n]
            if picked:
                return set(picked)
        except Exception:
            pass
    return set(sorted(cache_stems)[:top_n])


def us_universe_cached(top_n: int) -> set:
    cache_stems = {p.stem for p in US_DIR.glob("*.parquet") if not p.stem.startswith("_")}
    snap_path = US_DIR / "_live_snapshot.parquet"
    if snap_path.exists():
        try:
            snap = pd.read_parquet(snap_path)
            rank_col = None
            for c in ("marketValueRaw", "marketValue", "accumulatedTradingValue", "accumulatedTradingVolume"):
                if c in snap.columns and snap[c].notna().any():
                    rank_col = c
                    break
            if rank_col is not None:
                snap = snap.dropna(subset=[rank_col]).sort_values(rank_col, ascending=False)
                code_col = "symbolCode" if "symbolCode" in snap.columns else "itemCode"
                ranked = snap[code_col].astype(str).str.upper().tolist()
                picked = [c for c in ranked if c in cache_stems][:top_n]
                if picked:
                    return set(picked)
        except Exception:
            pass
    return set(sorted(cache_stems)[:top_n])


def crypto_1h_universe_top(top_n: int) -> List[str]:
    """캐시 stem 만 + amount-sum top N (1h)."""
    scores: List[Tuple[str, float]] = []
    files = sorted(CRYPTO_1H_DIR.glob("*.parquet"))
    for p in files:
        try:
            amt = pd.read_parquet(p, columns=["amount"])["amount"].sum()
            scores.append((p.stem, float(amt)))
        except Exception:
            continue
    scores.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in scores[:top_n]]


# ---------------------------------------------------------------------------
# Build cache — for A and B (stocks). Returns symbol -> (close, score, dt, df_full)
# For B we also need amount & weekly close → keep DataFrame too.
# ---------------------------------------------------------------------------
def build_stock_cache(
    asset: str, strategy_name: str, interval: str, keep_df: bool = False,
) -> Dict[str, dict]:
    strat = STRATEGIES[strategy_name]
    is_quiet = strategy_name == "quiet_bottom"
    min_bars = MIN_BARS[interval]

    if asset == "kr":
        universe = kr_universe_cached(UNIVERSE_TOP)
        files = [p for p in sorted(KR_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    elif asset == "us":
        universe = us_universe_cached(UNIVERSE_TOP)
        files = [p for p in sorted(US_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    else:
        raise ValueError(asset)

    cache: Dict[str, dict] = {}
    n_done = n_skip = 0
    t0 = time.time()
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
                v = strat.signal(df_r, {}).to_numpy().astype("int8")
            else:
                v = strat.score(df_r, {}).to_numpy().astype("float32")
        except Exception:
            n_skip += 1
            continue
        close = df["close"].astype("float64").to_numpy()
        dt_arr = pd.DatetimeIndex(df.index).to_numpy()  # datetime64[ns]
        item = {"close": close, "val": v, "dt": dt_arr}
        if keep_df:
            # also stash amount + weekly resample close (forward-safe SMA10w)
            amt = df["amount"].astype("float64").to_numpy() if "amount" in df.columns else None
            item["amount"] = amt
            # weekly SMA10 — compute on 1d data: rolling(50d).mean is rough; use proper W-FRI resample then re-index
            try:
                w_close = df["close"].resample("W-FRI").last().dropna()
                sma10w = w_close.rolling(10, min_periods=10).mean()
                # forward-fill to daily; shift by 1 week to ensure no lookahead (use prior-week SMA)
                sma10w_shift = sma10w.shift(1)
                # align to daily index using merge_asof-like ffill: reindex daily then ffill
                daily_idx = df.index
                sma10w_daily = sma10w_shift.reindex(daily_idx, method="ffill")
                item["sma10w"] = sma10w_daily.to_numpy()
                item["close_for_w"] = df["close"].astype("float64").to_numpy()
            except Exception:
                item["sma10w"] = None
                item["close_for_w"] = None
        cache[symbol] = item
        n_done += 1
        if n_done % 100 == 0:
            print(f"    [{asset}/{strategy_name}/{interval}] loaded {n_done} (skip {n_skip})", flush=True)
    print(f"    [{asset}/{strategy_name}/{interval}] cache done: {n_done} symbols, skip {n_skip}, {time.time()-t0:.1f}s", flush=True)
    return cache


def build_crypto_1h_cache(
    strategy_name: str, top_n: int = 30,
) -> Dict[str, dict]:
    strat = STRATEGIES[strategy_name]
    is_quiet = strategy_name == "quiet_bottom"
    min_bars = MIN_BARS["1h"]
    syms = crypto_1h_universe_top(top_n)
    cache: Dict[str, dict] = {}
    n_done = n_skip = 0
    t0 = time.time()
    for sym in syms:
        p = CRYPTO_1H_DIR / f"{sym}.parquet"
        if not p.exists():
            continue
        try:
            df = load_crypto(p, "1d")  # NB: load_crypto only knows 1d/1w; we need raw 1h
        except Exception:
            n_skip += 1
            continue
        # Actually use raw 1h — read parquet directly to preserve 1h bars
        try:
            df = pd.read_parquet(p)
            if "timestamp" not in df.columns:
                n_skip += 1
                continue
            df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
            df = df.set_index("dt").sort_index()
            df = df.drop(columns=["timestamp"])
        except Exception:
            n_skip += 1
            continue
        if df is None or df.empty or len(df) < min_bars:
            n_skip += 1
            continue
        df_r = df.reset_index(drop=True)
        try:
            if is_quiet:
                v = strat.signal(df_r, {}).to_numpy().astype("int8")
            else:
                v = strat.score(df_r, {}).to_numpy().astype("float32")
        except Exception:
            n_skip += 1
            continue
        close = df["close"].astype("float64").to_numpy()
        dt_arr = pd.DatetimeIndex(df.index).to_numpy()
        cache[sym] = {"close": close, "val": v, "dt": dt_arr}
        n_done += 1
    print(f"    [crypto/{strategy_name}/1h] cache done: {n_done} symbols, skip {n_skip}, {time.time()-t0:.1f}s", flush=True)
    return cache


# ---------------------------------------------------------------------------
# Window runner (mirror cycle1_oos_micro.run_window) + optional gate
# ---------------------------------------------------------------------------
def run_window_with_gate(
    cache: Dict[str, dict],
    asset: str,
    strategy_name: str,
    interval: str,
    score_th,
    rule: ExitRule,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    gate_weekly: bool = False,
    gate_amount: bool = False,
    amount_mult: float = 2.0,
    amount_lookback: int = 20,
    annual_factor_years: Optional[float] = None,
) -> dict:
    is_quiet = strategy_name == "quiet_bottom"
    cost = COST_RT[asset]
    start64 = np.datetime64(window_start, "ns")
    end64 = np.datetime64(window_end, "ns")
    trades: List[dict] = []
    for symbol, blob in cache.items():
        close = blob["close"]
        val = blob["val"]
        dt_arr = blob["dt"]
        if len(val) < 2:
            continue
        if is_quiet:
            sig01 = val
        else:
            sig01 = (val >= float(score_th)).astype("int8")
        diff = np.diff(sig01.astype("int16"), prepend=0)
        in_period = (dt_arr >= start64) & (dt_arr <= end64)
        enter_mask = (diff == 1) & in_period

        # Gate: weekly trend filter — close > SMA10w (prior-week SMA, no lookahead)
        if gate_weekly:
            sma10w = blob.get("sma10w")
            if sma10w is not None:
                enter_mask = enter_mask & (close > sma10w)
            else:
                enter_mask = enter_mask & False

        # Gate: amount filter — amount[t] >= amount_mult * rolling_mean(amount, amount_lookback) shifted by 1
        if gate_amount:
            amt = blob.get("amount")
            if amt is not None:
                amt_s = pd.Series(amt)
                ma = amt_s.shift(1).rolling(amount_lookback, min_periods=amount_lookback).mean().to_numpy()
                cond = amt > (ma * amount_mult)
                cond = np.nan_to_num(cond, nan=False)
                enter_mask = enter_mask & cond
            else:
                enter_mask = enter_mask & False

        positions = np.where(enter_mask)[0]
        for pos in positions:
            if pos >= len(close) - 1:
                continue
            exit_pos, gross_ret = simulate(close, int(pos), rule)
            if exit_pos == pos:
                continue
            trades.append({
                "symbol": symbol,
                "held": exit_pos - pos,
                "gross_ret": gross_ret,
                "net_ret": gross_ret - cost,
            })
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
    years = annual_factor_years if annual_factor_years else max(1e-9, (window_end - window_start).days / 365.25)
    if rets.std() > 0:
        sharpe_pt = rets.mean() / rets.std()
        annual_factor = np.sqrt(max(1, len(rets)) / years)
        sharpe_ann = float(sharpe_pt * annual_factor)
    else:
        sharpe_ann = 0.0
    gains = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = float(gains / losses) if losses > 0 else float("inf")
    return {
        "n": int(len(rets)), "win%": round(win, 1),
        "mean%": round(mean, 2), "median%": round(median, 2),
        "held": round(held, 1), "total%": round(total, 1),
        "MDD%": round(dd, 1), "Sharpe_ann": round(sharpe_ann, 2),
        "PF": round(pf, 2) if pf != float("inf") else 99.99,
    }


# ---------------------------------------------------------------------------
# A. Exit micro grid expansion (3 combos × 40 rules)
# ---------------------------------------------------------------------------
A_COMBOS = [
    # (asset, strategy, interval, score_th, out_csv)
    ("us", "trend_pullback", "1d", 70, "cycle2_exit_micro_us_pullback.csv"),
    ("kr", "trend_chase",    "1d", 60, "cycle2_exit_micro_kr_chase.csv"),
    ("us", "trend_chase",    "1d", 60, "cycle2_exit_micro_us_chase.csv"),
]


def run_micro_grid(asset: str, strategy: str, interval: str, th: int, out_name: str) -> pd.DataFrame:
    print(f"\n=== A. micro grid for {asset}/{strategy}/{interval} th={th} ===", flush=True)
    cache = build_stock_cache(asset, strategy, interval, keep_df=False)
    if not cache:
        print("  empty cache — skipping", flush=True)
        return pd.DataFrame()
    trails = [0.15, 0.18, 0.20, 0.22, 0.25]
    tps    = [0.20, 0.25, 0.30, 0.35]
    holds  = [180, 252]
    ws, we = TRAIN_START, TEST_END
    rows = []
    total = len(trails) * len(tps) * len(holds)
    i = 0
    for h in holds:
        for tr in trails:
            for tp in tps:
                i += 1
                rule = ExitRule(
                    name=f"hold_{h}d_trail{int(tr*100)}_TP{int(tp*100)}",
                    max_hold=h, trailing_pct=tr, take_profit_pct=tp,
                )
                try:
                    s = run_window_with_gate(cache, asset, strategy, interval, th, rule, ws, we)
                except Exception as e:
                    print(f"  FAIL {rule.name}: {type(e).__name__}: {e}", flush=True)
                    s = {"n": 0, "win%": 0, "mean%": 0, "median%": 0, "held": 0,
                         "total%": 0, "MDD%": 0, "Sharpe_ann": 0, "PF": 0}
                rows.append({
                    "asset": asset, "strategy": strategy, "interval": interval,
                    "score_th": th, "rule": rule.name,
                    "hold": h, "trail_pct": tr, "take_profit_pct": tp,
                    **s,
                })
                print(f"  [{i}/{total}] {rule.name}: n={s['n']} mean={s['mean%']}% "
                      f"Sharpe={s['Sharpe_ann']} PF={s['PF']}", flush=True)
    df = pd.DataFrame(rows)
    out_csv = OUT_DIR / out_name
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"saved: {out_csv}", flush=True)
    return df


# ---------------------------------------------------------------------------
# B. Gate diagnostics (cycle 3 compressed)
# ---------------------------------------------------------------------------
B_COMBOS = [
    ("kr", "trend_pullback", "1d", 60, "cycle3_gates_kr_pullback.csv"),
    ("us", "trend_pullback", "1d", 70, "cycle3_gates_us_pullback.csv"),
]


def run_gate_diag(asset: str, strategy: str, interval: str, th: int, exit_rule: ExitRule, out_name: str) -> pd.DataFrame:
    print(f"\n=== B. gate diag for {asset}/{strategy}/{interval} th={th} rule={exit_rule.name} ===", flush=True)
    cache = build_stock_cache(asset, strategy, interval, keep_df=True)
    if not cache:
        print("  empty cache — skipping", flush=True)
        return pd.DataFrame()
    ws, we = TRAIN_START, TEST_END
    variants = [
        ("baseline",     False, False),
        ("+weekly",      True,  False),
        ("+amount",      False, True),
        ("+weekly+amount", True, True),
    ]
    rows = []
    for name, gw, ga in variants:
        try:
            s = run_window_with_gate(cache, asset, strategy, interval, th, exit_rule, ws, we,
                                     gate_weekly=gw, gate_amount=ga)
        except Exception as e:
            print(f"  FAIL {name}: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            s = {"n": 0, "win%": 0, "mean%": 0, "median%": 0, "held": 0,
                 "total%": 0, "MDD%": 0, "Sharpe_ann": 0, "PF": 0}
        rows.append({
            "asset": asset, "strategy": strategy, "interval": interval,
            "score_th": th, "rule": exit_rule.name, "variant": name,
            "gate_weekly": gw, "gate_amount": ga,
            **s,
        })
        print(f"  {name}: n={s['n']} mean={s['mean%']}% Sharpe={s['Sharpe_ann']} PF={s['PF']}", flush=True)
    df = pd.DataFrame(rows)
    out_csv = OUT_DIR / out_name
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"saved: {out_csv}", flush=True)
    return df


# ---------------------------------------------------------------------------
# C. Crypto 1h probe (cycle 4 compressed)
# ---------------------------------------------------------------------------
def run_crypto_1h_probe() -> pd.DataFrame:
    print(f"\n=== C. crypto 1h probe ===", flush=True)
    cache = build_crypto_1h_cache("trend_chase", top_n=30)
    if not cache:
        print("  empty cache — skipping", flush=True)
        return pd.DataFrame()
    # rule: hold 240 bars, trail 0.15, cut after 24 bars if down (cut_short_at=24)
    rule = ExitRule(
        name="hold_240bars_trail15_cut24h",
        max_hold=240, trailing_pct=0.15, take_profit_pct=0.0,
        cut_short_thr=-3.0, cut_short_at=24,
    )
    th = 70
    # Use last 6 years window (1h goes back further than that for liquid alts)
    ws = pd.Timestamp("2020-05-17")
    we = pd.Timestamp("2026-05-17")
    s = run_window_with_gate(cache, "crypto", "trend_chase", "1h", th, rule, ws, we)
    row = {
        "asset": "crypto", "strategy": "trend_chase", "interval": "1h",
        "score_th": th, "rule": rule.name, "universe": "top30 by amount-sum",
        **s,
    }
    df = pd.DataFrame([row])
    out_csv = OUT_DIR / "cycle4_crypto_1h_probe.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"saved: {out_csv}", flush=True)
    print(f"  probe: n={s['n']} mean={s['mean%']}% Sharpe={s['Sharpe_ann']} PF={s['PF']}", flush=True)
    return df


# ---------------------------------------------------------------------------
# Best rule extraction helper
# ---------------------------------------------------------------------------
def best_of(df: pd.DataFrame) -> Optional[dict]:
    if df is None or df.empty:
        return None
    valid = df[df["n"] > 0].copy()
    if valid.empty:
        return None
    return valid.sort_values("Sharpe_ann", ascending=False).iloc[0].to_dict()


def main():
    t0 = time.time()
    results = {"A": {}, "B": {}, "C": None, "best_A": {}}

    # ---- A ----
    for asset, strategy, interval, th, out_name in A_COMBOS:
        key = f"{asset}_{strategy}"
        try:
            df = run_micro_grid(asset, strategy, interval, th, out_name)
            results["A"][key] = df
            b = best_of(df)
            results["best_A"][key] = b
            if b is not None:
                print(f"  >> best {key}: {b['rule']} Sharpe={b['Sharpe_ann']} mean={b['mean%']}% win={b['win%']}%", flush=True)
        except Exception as e:
            print(f"A. {key} FAIL: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            results["A"][key] = pd.DataFrame()

    # ---- B ----
    # Use best exit rule from A (US pullback) for US, KR pullback from cycle1 best for KR.
    # KR pullback best from cycle1: trail0.25 / TP0.35 / hold252
    kr_pull_best = ExitRule("hold_252d_trail25_TP35", max_hold=252, trailing_pct=0.25, take_profit_pct=0.35)
    us_pull_best = kr_pull_best  # default same; will override if A produced a different best
    b_us = results["best_A"].get("us_trend_pullback")
    if b_us is not None:
        us_pull_best = ExitRule(
            name=b_us["rule"], max_hold=int(b_us["hold"]),
            trailing_pct=float(b_us["trail_pct"]), take_profit_pct=float(b_us["take_profit_pct"]),
        )
    B_RULES = {
        "kr": (60, kr_pull_best),
        "us": (70, us_pull_best),
    }
    for asset, strategy, interval, th_default, out_name in B_COMBOS:
        th, rule = B_RULES[asset]
        try:
            df = run_gate_diag(asset, strategy, interval, th, rule, out_name)
            results["B"][asset] = df
        except Exception as e:
            print(f"B. {asset} FAIL: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            results["B"][asset] = pd.DataFrame()

    # ---- C ----
    try:
        df_c = run_crypto_1h_probe()
        results["C"] = df_c
    except Exception as e:
        print(f"C. probe FAIL: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        results["C"] = pd.DataFrame()

    elapsed = time.time() - t0
    print(f"\nTotal elapsed: {elapsed:.1f}s", flush=True)
    return results


if __name__ == "__main__":
    main()
