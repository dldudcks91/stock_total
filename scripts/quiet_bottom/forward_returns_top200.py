"""시총 상위 200 종목에 한정한 ma_slope_turn_up 시그널 분석.

Universe:
  - KR: FDR StockListing(KOSPI) Marcap 상위 200
  - Crypto: 캐시의 amount(USDT 거래대금) 합 상위 200 (시총 정확 데이터 없음 → proxy)

각 시그널 진입의 1~8주 forward return 분포 + 종목별 평균 + Top/Worst.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.strategies import ma_slope_turn_up  # noqa: E402
from scripts.count_slope_turn_signals import (  # noqa: E402
    load_crypto_weekly, load_stock_weekly, crypto_symbol_from_file,
    CRYPTO_DIR, CRYPTO_1H_DIR, KR_DIR, US_DIR, SINCE,
)

OUT_DIR = ROOT / "scripts" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HORIZONS = list(range(1, 9))
RET_COLS = [f"+{h}w_%" for h in HORIZONS]
TOP_N = 300


def kr_top_universe() -> set[str]:
    import FinanceDataReader as fdr
    df = fdr.StockListing("KOSPI")
    df = df.dropna(subset=["Marcap"]).sort_values("Marcap", ascending=False)
    return set(df["Code"].head(TOP_N).astype(str).tolist())


def us_top_universe() -> set[str]:
    """NASDAQ 시총 상위 TOP_N. FDR StockListing이 시총순 정렬."""
    import FinanceDataReader as fdr
    df = fdr.StockListing("NASDAQ")
    return set(df["Symbol"].head(TOP_N).astype(str).tolist())


def crypto_top_universe() -> set[str]:
    """모든 1h 캐시의 amount 총합 상위 TOP_N. (전체 기간 거래대금 합산)"""
    scores: list[tuple[str, float]] = []
    files = sorted(CRYPTO_1H_DIR.glob("*.parquet"))
    if not files:
        files = sorted(CRYPTO_DIR.glob("bitget_*_1h.parquet"))
    for p in files:
        sym = crypto_symbol_from_file(p)
        try:
            df = pd.read_parquet(p, columns=["amount"])
            scores.append((sym, float(df["amount"].sum())))
        except Exception:
            continue
    scores.sort(key=lambda x: x[1], reverse=True)
    return {s for s, _ in scores[:TOP_N]}


def collect(asset: str, files: list[Path], loader, universe: set[str]) -> pd.DataFrame:
    rows = []
    n = len(files)
    skipped = 0
    print(f"[{asset}] {n} symbols  (universe={len(universe)})", flush=True)
    for i, p in enumerate(files, 1):
        symbol = crypto_symbol_from_file(p) if asset == "crypto" else p.stem
        if symbol not in universe:
            skipped += 1
            continue
        try:
            df_w = loader(p)
            if df_w is None or df_w.empty or len(df_w) < 120:
                continue
            sig = ma_slope_turn_up.signal(df_w.reset_index(drop=True), {})
            sig.index = df_w.index
            entries = (sig.diff() == 1) & (df_w.index >= SINCE)
            close = df_w["close"].to_numpy()
            for pos in np.where(entries.to_numpy())[0]:
                ec = float(close[pos])
                row = {"asset": asset, "symbol": symbol,
                       "entry_dt": df_w.index[pos].date().isoformat(),
                       "entry_close": round(ec, 6)}
                for h in HORIZONS:
                    fp = pos + h
                    row[f"+{h}w_%"] = (round(float(close[fp] / ec - 1.0) * 100, 1)
                                       if fp < len(close) else np.nan)
                rows.append(row)
        except Exception as e:
            print(f"  ! {symbol}: {type(e).__name__}: {e}", flush=True)
        if i % 100 == 0 or i == n:
            print(f"  {i}/{n}  (skipped not-in-universe: {skipped})", flush=True)
    return pd.DataFrame(rows)


def horizon_stats(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for h in HORIZONS:
        s = df[f"+{h}w_%"].dropna()
        if len(s) == 0:
            continue
        out.append({
            "h": f"+{h}w", "n": len(s),
            "mean_%": s.mean(), "median_%": s.median(),
            "win_%": (s > 0).mean() * 100,
            "p25_%": s.quantile(0.25), "p75_%": s.quantile(0.75),
            "max_%": s.max(), "min_%": s.min(),
        })
    return pd.DataFrame(out)


def main():
    print("Building universes...")
    kr_uni = kr_top_universe()
    cr_uni = crypto_top_universe()
    us_uni = us_top_universe()
    print(f"  KR top200: {len(kr_uni)} codes")
    print(f"  Crypto top200 (amount-proxy): {len(cr_uni)} symbols")
    print(f"  US top200 (NASDAQ marcap): {len(us_uni)} symbols")

    cr_files = sorted(CRYPTO_1H_DIR.glob("*.parquet"))
    if not cr_files:
        cr_files = sorted(CRYPTO_DIR.glob("bitget_*_1h.parquet"))
    df_c = collect("crypto", cr_files, load_crypto_weekly, cr_uni)

    kr_files = [p for p in sorted(KR_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    df_k = collect("kr", kr_files, load_stock_weekly, kr_uni)

    us_files = [p for p in sorted(US_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    df_u = collect("us", us_files, load_stock_weekly, us_uni) if us_files else pd.DataFrame()

    all_df = pd.concat([d for d in [df_c, df_k, df_u] if not d.empty], ignore_index=True)
    out_csv = OUT_DIR / "forward_2m_top200.csv"
    all_df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nsaved: {out_csv}  (rows={len(all_df)})")

    pd.set_option("display.float_format", "{:.1f}".format)
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", None)

    # 시그널 카운트 요약 (universe 안에서)
    print("\n=== Signal counts (top200 only) ===")
    for asset, sub in all_df.groupby("asset"):
        n_sym = sub["symbol"].nunique()
        print(f"  [{asset}] entries={len(sub)}, symbols_with_signal={n_sym}")

    for asset, sub in all_df.groupby("asset"):
        print(f"\n=== [{asset}] 1~8주 horizon 통계 (n={len(sub)} signals) ===")
        print(horizon_stats(sub).to_string(index=False))
        peak = sub[RET_COLS].max(axis=1)
        trough = sub[RET_COLS].min(axis=1)
        print(f"\n[{asset}] peak8: mean={peak.mean():.1f}%, median={peak.median():.1f}%, "
              f">+20%:{(peak>20).mean()*100:.1f}% >+50%:{(peak>50).mean()*100:.1f}% >+100%:{(peak>100).mean()*100:.1f}%")
        print(f"[{asset}] trough8: mean={trough.mean():.1f}%, median={trough.median():.1f}%, "
              f"<-20%:{(trough<-20).mean()*100:.1f}% <-30%:{(trough<-30).mean()*100:.1f}% <-50%:{(trough<-50).mean()*100:.1f}%")

    # 자산별 종목 평균 (진입 ≥ 2회)
    for asset, sub in all_df.groupby("asset"):
        agg = sub.groupby("symbol").agg(
            n=("entry_dt", "count"),
            m1=("+1w_%", "mean"), m4=("+4w_%", "mean"), m8=("+8w_%", "mean"),
        )
        agg["peak8"] = sub.groupby("symbol").apply(lambda d: d[RET_COLS].max(axis=1).mean())
        agg["trough8"] = sub.groupby("symbol").apply(lambda d: d[RET_COLS].min(axis=1).mean())
        agg = agg[agg["n"] >= 2].sort_values("n", ascending=False).head(25)
        print(f"\n=== [{asset}] 종목별 평균 (진입 ≥2회, 진입수↓ Top 25) ===")
        print(agg.to_string())

    # Top/Worst
    all_df["peak8_%"] = all_df[RET_COLS].max(axis=1)
    all_df["trough8_%"] = all_df[RET_COLS].min(axis=1)
    for asset, sub in all_df.groupby("asset"):
        print(f"\n=== [{asset}] 단일 진입 — 8주 peak Top 10 ===")
        top = sub.sort_values("peak8_%", ascending=False).head(10)
        print(top[["symbol", "entry_dt", "entry_close", "peak8_%"] + RET_COLS].to_string(index=False))
        print(f"\n=== [{asset}] 단일 진입 — 8주 trough Worst 10 ===")
        bad = sub.sort_values("trough8_%").head(10)
        print(bad[["symbol", "entry_dt", "entry_close", "trough8_%"] + RET_COLS].to_string(index=False))


if __name__ == "__main__":
    main()
