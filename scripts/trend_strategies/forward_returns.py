"""trend_chase / trend_pullback 전략의 forward-return 백테스트.

대상:
  - 자산: crypto (Bitget top200 by amount), kr (KOSPI top300 by Marcap), us (NASDAQ top200)
  - 인터벌: 1d (일봉), 1w (주봉)
  - 전략: trend_chase, trend_pullback
  - 기간: 최근 6년
  - 진입: signal 0 → 1 전환 시점
  - forward return: 일봉 5/10/20/40일, 주봉 1/2/4/8주

사용:
  python -m scripts.trend_strategies.forward_returns --strategy trend_chase --interval 1d
  python -m scripts.trend_strategies.forward_returns --strategy trend_pullback --interval 1w
  python -m scripts.trend_strategies.forward_returns --all                 # 4 조합 모두
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import trend_chase, trend_pullback  # noqa: E402

CACHE_DIR = ROOT / "data" / "cache"
CRYPTO_1H_DIR = CACHE_DIR / "crypto" / "1h"
CRYPTO_1D_DIR = CACHE_DIR / "crypto" / "1d"
KR_DIR = CACHE_DIR / "kr"
US_DIR = CACHE_DIR / "us"

OUT_DIR = ROOT / "scripts" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NOW = pd.Timestamp.utcnow().tz_localize(None).normalize()
SINCE = NOW - pd.DateOffset(years=6)

STRATEGIES = {
    "trend_chase": trend_chase,
    "trend_pullback": trend_pullback,
}

UNIVERSE_TOP = {"crypto": 200, "kr": 300, "us": 200}

CRYPTO_AGG_W = {
    "open": "first", "high": "max", "low": "min",
    "close": "last", "volume": "sum", "amount": "sum",
}
STOCK_AGG_W = {"Open": "first", "High": "max", "Low": "min",
               "Close": "last", "Volume": "sum"}


def _norm_stock_cols(df: pd.DataFrame) -> pd.DataFrame:
    rename = {c: c.lower() for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns}
    return df.rename(columns=rename)


# --- 로더 -------------------------------------------------------------

def load_crypto(path: Path, interval: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if "timestamp" not in df.columns:
        return pd.DataFrame()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df = df.set_index("dt").sort_index()
    if interval == "1d":
        cols = [c for c in CRYPTO_AGG_W if c in df.columns]
        agg = {c: CRYPTO_AGG_W[c] for c in cols}
        return df.resample("1D", label="left", closed="left").agg(agg).dropna()
    elif interval == "1w":
        cols = [c for c in CRYPTO_AGG_W if c in df.columns]
        agg = {c: CRYPTO_AGG_W[c] for c in cols}
        return df.resample("W-MON", label="left", closed="left").agg(agg).dropna()
    raise ValueError(interval)


def load_stock(path: Path, interval: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if "Close" not in df.columns:
        return pd.DataFrame()
    df = df.sort_index()
    if interval == "1d":
        out = _norm_stock_cols(df)
    elif interval == "1w":
        w = df.resample("W-FRI").agg(STOCK_AGG_W).dropna()
        out = _norm_stock_cols(w)
    else:
        raise ValueError(interval)
    # FDR stocks have no amount column → 백테스트 안전을 위해 close*volume 추가
    if "amount" not in out.columns:
        out["amount"] = out["close"].astype("float64") * out["volume"].astype("float64")
    return out


# --- universe ---------------------------------------------------------

_UNIVERSE_CACHE_PATH = ROOT / "scripts" / "out" / "optimize" / "_universe_cache.json"


def _cached_universe(asset: str, top_n: int) -> Optional[set]:
    import json
    if not _UNIVERSE_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(_UNIVERSE_CACHE_PATH.read_text(encoding="utf-8"))
        syms = data.get(asset, [])
        if not syms:
            return None
        return set(syms[:top_n])
    except Exception:
        return None


def kr_universe(top_n: int) -> set:
    cached = _cached_universe("kr", top_n)
    if cached is not None:
        return cached
    import FinanceDataReader as fdr
    df = fdr.StockListing("KOSPI").dropna(subset=["Marcap"]).sort_values("Marcap", ascending=False)
    return set(df["Code"].head(top_n).astype(str).tolist())


def us_universe(top_n: int) -> set:
    cached = _cached_universe("us", top_n)
    if cached is not None:
        return cached
    import FinanceDataReader as fdr
    df = fdr.StockListing("NASDAQ")
    return set(df["Symbol"].head(top_n).astype(str).tolist())


def crypto_universe(top_n: int) -> set:
    scores: list[tuple[str, float]] = []
    files = sorted(CRYPTO_1H_DIR.glob("*.parquet"))
    for p in files:
        try:
            amt = pd.read_parquet(p, columns=["amount"])["amount"].sum()
            scores.append((p.stem, float(amt)))
        except Exception:
            continue
    scores.sort(key=lambda x: x[1], reverse=True)
    return {s for s, _ in scores[:top_n]}


# --- forward-return collector ----------------------------------------

def _horizons(interval: str) -> list[int]:
    return [5, 10, 20, 40] if interval == "1d" else [1, 2, 4, 8]


def _h_label(interval: str, h: int) -> str:
    return f"+{h}d" if interval == "1d" else f"+{h}w"


def collect_asset(asset: str, files: list[Path], loader, interval: str,
                  universe: set, strategy_mod, min_bars: int) -> pd.DataFrame:
    rows = []
    n_total = len(files)
    print(f"[{asset}/{interval}] {n_total} files (universe={len(universe)})", flush=True)
    n_done = 0
    n_skip_uni = 0
    n_skip_short = 0
    horizons = _horizons(interval)

    for p in files:
        symbol = p.stem
        if symbol not in universe:
            n_skip_uni += 1
            continue
        try:
            df = loader(p, interval)
        except Exception as e:
            print(f"  ! {symbol}: load fail {type(e).__name__}: {e}", flush=True)
            continue
        if df is None or df.empty or len(df) < min_bars:
            n_skip_short += 1
            continue
        # 룩어헤드 안전을 위해 strategy 는 reset_index 한 raw df 에 적용
        try:
            sig = strategy_mod.signal(df.reset_index(drop=True), {})
            sc = strategy_mod.score(df.reset_index(drop=True), {})
        except Exception as e:
            print(f"  ! {symbol}: signal fail {type(e).__name__}: {e}", flush=True)
            continue
        sig.index = df.index
        sc.index = df.index
        entries = (sig.diff() == 1) & (sig.index >= SINCE)
        if not entries.any():
            continue
        close = df["close"].astype("float64").to_numpy()
        for pos in np.where(entries.to_numpy())[0]:
            ec = float(close[pos])
            if not np.isfinite(ec) or ec <= 0:
                continue
            row = {
                "asset": asset, "symbol": symbol,
                "interval": interval,
                "entry_dt": df.index[pos].date().isoformat(),
                "entry_close": round(ec, 6),
                "score": round(float(sc.iat[pos]), 1),
            }
            for h in horizons:
                fp = pos + h
                row[_h_label(interval, h)] = (
                    round(float(close[fp] / ec - 1.0) * 100, 2)
                    if fp < len(close) else np.nan
                )
            rows.append(row)
        n_done += 1

    print(f"  [{asset}/{interval}] processed={n_done}, skip_universe={n_skip_uni}, "
          f"skip_short={n_skip_short}, entries={len(rows)}", flush=True)
    return pd.DataFrame(rows)


def horizon_stats(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    horizons = _horizons(interval)
    out = []
    for h in horizons:
        col = _h_label(interval, h)
        s = df[col].dropna()
        if len(s) == 0:
            continue
        out.append({
            "h": col, "n": len(s),
            "mean_%": s.mean(), "median_%": s.median(),
            "win_%": (s > 0).mean() * 100,
            "p25_%": s.quantile(0.25), "p75_%": s.quantile(0.75),
            "max_%": s.max(), "min_%": s.min(),
        })
    return pd.DataFrame(out)


def run_one(strategy: str, interval: str) -> pd.DataFrame:
    strat = STRATEGIES[strategy]
    print(f"\n===== {strategy} | {interval} =====")
    min_bars = 80 if interval == "1d" else 30  # 워밍업

    # 자산별 universe
    print("Building universes...")
    cr_uni = crypto_universe(UNIVERSE_TOP["crypto"])
    kr_uni = kr_universe(UNIVERSE_TOP["kr"])
    us_uni = us_universe(UNIVERSE_TOP["us"])
    print(f"  crypto={len(cr_uni)} kr={len(kr_uni)} us={len(us_uni)}")

    # 일봉 캐시 vs 1h 캐시
    if interval == "1d":
        cr_files = sorted(CRYPTO_1D_DIR.glob("*.parquet")) if CRYPTO_1D_DIR.exists() else []
        if not cr_files:
            cr_files = sorted(CRYPTO_1H_DIR.glob("*.parquet"))  # 1h에서 일봉 리샘플
    else:
        cr_files = sorted(CRYPTO_1H_DIR.glob("*.parquet"))

    df_c = collect_asset("crypto", cr_files, load_crypto, interval, cr_uni, strat, min_bars)

    kr_files = [p for p in sorted(KR_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    df_k = collect_asset("kr", kr_files, load_stock, interval, kr_uni, strat, min_bars)

    us_files = [p for p in sorted(US_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    df_u = collect_asset("us", us_files, load_stock, interval, us_uni, strat, min_bars) \
        if us_files else pd.DataFrame()

    all_df = pd.concat([d for d in [df_c, df_k, df_u] if not d.empty], ignore_index=True)

    out_csv = OUT_DIR / f"{strategy}_{interval}_signals.csv"
    all_df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"saved: {out_csv}  (rows={len(all_df)})")

    if all_df.empty:
        print("  (no signals)")
        return all_df

    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", None)

    print(f"\n--- [{strategy}/{interval}] entries per asset ---")
    for asset, sub in all_df.groupby("asset"):
        print(f"  [{asset}] entries={len(sub)}, symbols_with_signal={sub['symbol'].nunique()}, "
              f"score(mean/median/p90)={sub['score'].mean():.1f}/"
              f"{sub['score'].median():.1f}/{sub['score'].quantile(0.9):.1f}")

    for asset, sub in all_df.groupby("asset"):
        print(f"\n--- [{asset}/{strategy}/{interval}] forward-return ---")
        print(horizon_stats(sub, interval).to_string(index=False))

    # 점수 threshold별 forward return (의미 검증)
    print(f"\n--- score threshold sensitivity (interval={interval}) ---")
    h_cols = [_h_label(interval, h) for h in _horizons(interval)]
    long_h = h_cols[-1]
    for asset, sub in all_df.groupby("asset"):
        print(f"  [{asset}]")
        for th in [50, 60, 70, 80]:
            sel = sub[sub["score"] >= th]
            s = sel[long_h].dropna()
            if len(s) == 0:
                continue
            print(f"    score>={th}: n={len(s):4d}  mean={s.mean():+6.2f}%  "
                  f"median={s.median():+6.2f}%  win%={(s>0).mean()*100:5.1f}")

    return all_df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", choices=list(STRATEGIES.keys()))
    ap.add_argument("--interval", choices=["1d", "1w"])
    ap.add_argument("--all", action="store_true", help="run 2 strategies x 2 intervals")
    args = ap.parse_args()

    if args.all:
        for strat in STRATEGIES:
            for itv in ("1d", "1w"):
                run_one(strat, itv)
    else:
        if not args.strategy or not args.interval:
            ap.error("provide --strategy and --interval (or --all)")
        run_one(args.strategy, args.interval)


if __name__ == "__main__":
    main()
