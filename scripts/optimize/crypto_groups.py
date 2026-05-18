"""Round 2 — Crypto classification 그룹별 Sharpe.

classification.parquet 이 없으므로 1d 캐시에서 직접 4그룹 분류 후
각 그룹별로 trend_chase / trend_pullback × 1d/4h Sharpe 측정.

분류 단순화 (docs/classification.md 룰의 축소판):
  - benchmark: BTCUSDT
  - stable: realized_vol_annual < 0.10
  - junk: listing_days < 365 (1년 미만 신규)
  - whale: kurt_trimmed >= 10 (단발 펌프 빈도)
  - follower: r2_btc >= 0.5 (BTC 동조)
  - trend: 나머지 (자기 추세)

산출:
  scripts/out/optimize/round2/crypto/task2_classification.csv
  scripts/out/optimize/round2/crypto/task2_group_sharpe.csv
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
from data.classification import (  # noqa: E402
    kurtosis_trimmed, hurst_rs, pump_recurrence, max_drawdown,
)
from scripts.optimize_grid import ExitRule, simulate  # noqa: E402

CACHE_1D = ROOT / "data" / "cache" / "crypto" / "1d"
CACHE_1H = ROOT / "data" / "cache" / "crypto" / "1h"
OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "round2" / "crypto"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NOW = pd.Timestamp.utcnow().tz_localize(None).normalize()
SINCE_YEARS = 3
SINCE = NOW - pd.DateOffset(years=SINCE_YEARS)
COST = 0.002


def load_1d(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if "timestamp" not in df.columns:
        return pd.DataFrame()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df = df.set_index("dt").sort_index()
    return df[["open", "high", "low", "close", "volume", "amount"]]


def load_4h_from_1h(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if "timestamp" not in df.columns:
        return pd.DataFrame()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df = df.set_index("dt").sort_index()
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    if "amount" in df.columns:
        agg["amount"] = "sum"
    return df.resample("4H", label="left", closed="left").agg(agg).dropna()


def classify_one(symbol: str, daily: pd.DataFrame, btc_ret: pd.Series) -> dict:
    if daily.empty or "close" not in daily.columns:
        return {"symbol": symbol, "tier": "unknown"}
    close = daily["close"].astype(float)
    ret = close.pct_change().dropna()
    if len(ret) < 30:
        return {"symbol": symbol, "tier": "junk", "listing_days": len(daily),
                "r2_btc": np.nan, "beta_btc": np.nan,
                "realized_vol_annual": np.nan, "kurt_trimmed": np.nan}
    vol = float(ret.std(ddof=0) * np.sqrt(365))
    kurt_t = float(kurtosis_trimmed(ret.values, pct=0.005))
    aligned = pd.concat([ret.rename("c"), btc_ret.rename("b")], axis=1).dropna()
    if aligned.shape[0] >= 10 and aligned["b"].std() > 0:
        corr = float(aligned["c"].corr(aligned["b"]))
        r2 = float(corr ** 2) if np.isfinite(corr) else np.nan
        cov = float(((aligned["c"] - aligned["c"].mean()) *
                     (aligned["b"] - aligned["b"].mean())).mean())
        var_b = float(aligned["b"].var(ddof=0))
        beta = cov / var_b if var_b > 0 else np.nan
    else:
        r2 = beta = np.nan
    listing_days = int(daily.shape[0])

    # Tier 규칙
    if symbol == "BTCUSDT":
        tier = "benchmark"
    elif vol < 0.10:
        tier = "stable"
    elif listing_days < 365:
        tier = "junk"
    elif np.isfinite(kurt_t) and kurt_t >= 10:
        tier = "whale"
    elif np.isfinite(r2) and r2 >= 0.5:
        tier = "follower"
    else:
        tier = "trend"
    return {
        "symbol": symbol, "tier": tier,
        "listing_days": listing_days,
        "r2_btc": r2, "beta_btc": beta,
        "realized_vol_annual": vol,
        "kurt_trimmed": kurt_t,
    }


def build_classification() -> pd.DataFrame:
    btc_path = CACHE_1D / "BTCUSDT.parquet"
    btc = load_1d(btc_path)
    btc_ret = btc["close"].pct_change().dropna()
    btc_ret = btc_ret[btc_ret.index >= SINCE]
    print(f"[btc] {len(btc_ret)} daily returns since {SINCE.date()}", flush=True)

    files = sorted(CACHE_1D.glob("*.parquet"))
    rows = []
    t0 = time.time()
    for i, p in enumerate(files):
        try:
            daily = load_1d(p)
        except Exception:
            continue
        # 분류는 최근 3년 데이터로
        daily = daily[daily.index >= SINCE]
        rows.append(classify_one(p.stem, daily, btc_ret))
        if (i + 1) % 100 == 0:
            print(f"  classified {i+1}/{len(files)} ({time.time()-t0:.1f}s)", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "task2_classification.csv", index=False, encoding="utf-8-sig")
    print(f"classification: {df['tier'].value_counts().to_dict()}", flush=True)
    return df


def summarize_trades(trades: list[dict], years: float) -> dict:
    if not trades:
        return {"n": 0, "win%": 0, "mean%": 0, "Sharpe_ann": 0, "PF": 0}
    rets = np.array([t["net_ret"] for t in trades])
    win = float((rets > 0).mean() * 100)
    mean = float(rets.mean() * 100)
    if rets.std() > 0:
        sharpe_ann = float(rets.mean() / rets.std() * np.sqrt(max(1, len(rets)) / years))
    else:
        sharpe_ann = 0.0
    gains = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = float(gains / losses) if losses > 0 else 99.99
    return {"n": len(rets), "win%": round(win, 1), "mean%": round(mean, 2),
            "Sharpe_ann": round(sharpe_ann, 2), "PF": round(pf, 2)}


def group_sharpe(classification: pd.DataFrame) -> pd.DataFrame:
    """그룹 × 전략 × 인터벌 × 단일 baseline 청산룰 (Round 1 best) 으로 Sharpe."""
    # 데이터 캐시: per-symbol close + scores @ 1d / 4h
    INTERVALS = {
        "1d": (CACHE_1D, load_1d, 80),
        "4h": (CACHE_1H, load_4h_from_1h, 200),
    }
    # Round 1 best 룰 사용
    EXIT_BY_IV = {
        "1d": ExitRule("hold_60d_trail20_TP30", max_hold=60, trailing_pct=0.20, take_profit_pct=0.30),
        "4h": ExitRule("hold_120bars_trail15_cut24h", max_hold=120, trailing_pct=0.15,
                       cut_short_at=6, cut_short_thr=-4),
    }

    sym_by_tier: dict[str, list[str]] = (
        classification[classification["tier"].isin(["trend", "follower", "whale", "junk"])]
        .groupby("tier")["symbol"].apply(list).to_dict()
    )
    print(f"[groups] sizes: { {k: len(v) for k, v in sym_by_tier.items()} }", flush=True)

    out_rows = []
    for iv, (cache_dir, loader, min_bars) in INTERVALS.items():
        print(f"\n=== interval={iv} ===", flush=True)
        # 캐시 단일 패스
        per_sym: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
        all_files = sorted(cache_dir.glob("*.parquet"))
        t0 = time.time()
        for i, p in enumerate(all_files):
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
            in_period = np.asarray(df.index >= SINCE)
            per_sym[p.stem] = (close, sc_c, sc_p, in_period)
            if (i + 1) % 100 == 0:
                print(f"  scored {i+1}/{len(all_files)} ({time.time()-t0:.1f}s)", flush=True)
        print(f"[{iv}] {len(per_sym)} symbols scored", flush=True)

        rule = EXIT_BY_IV[iv]
        for tier, symbols in sym_by_tier.items():
            for strat_name, idx in (("trend_chase", 1), ("trend_pullback", 2)):
                for th in [60, 70, 80]:
                    trades = []
                    for sym in symbols:
                        v = per_sym.get(sym)
                        if v is None:
                            continue
                        close = v[0]
                        sc = v[idx]
                        in_period = v[3]
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
                            trades.append({"net_ret": gross - COST})
                    s = summarize_trades(trades, SINCE_YEARS)
                    out_rows.append({"tier": tier, "interval": iv,
                                     "strategy": strat_name, "score_th": th,
                                     "rule": rule.name, **s})
                    print(f"  {tier:>9s} {iv} {strat_name:<15s} th={th}  "
                          f"n={s['n']:>5} win={s['win%']:>4.1f}% Sharpe={s['Sharpe_ann']:>+5.2f}",
                          flush=True)

    out = pd.DataFrame(out_rows)
    out.to_csv(OUT_DIR / "task2_group_sharpe.csv", index=False, encoding="utf-8-sig")
    print(f"saved: {OUT_DIR / 'task2_group_sharpe.csv'}", flush=True)
    return out


def main():
    cls = build_classification()
    group_sharpe(cls)


if __name__ == "__main__":
    main()
