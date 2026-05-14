"""ma_slope_turn_up 전략의 진입 시그널 빈도를 자산별로 카운트.

대상:
  - 크립토 (Bitget USDT-M 1h → 주봉 W-MON 리샘플)
  - KR (FDR 1d → 주봉 W-FRI 리샘플)
  - US (있다면, FDR 1d → 주봉 W-FRI)

기간: 최근 3년. 진입 = signal 0 → 1 전환 횟수.
출력: 콘솔에 자산별 표 + 합계, 그리고 CSV 저장 (scripts/out/slope_turn_counts.csv).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# 한글 깨짐 방지
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import ma_slope_turn_up  # noqa: E402

CACHE_DIR = ROOT / "data" / "cache"
CRYPTO_DIR = CACHE_DIR / "crypto"
CRYPTO_1H_DIR = CRYPTO_DIR / "1h"
CRYPTO_1D_DIR = CRYPTO_DIR / "1d"
KR_DIR = CACHE_DIR / "kr"
US_DIR = CACHE_DIR / "us"

OUT_DIR = ROOT / "scripts" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 분석 기간 (n 늘리기 위해 6년으로 확장)
SINCE_YEARS = 6
NOW = pd.Timestamp.utcnow().tz_localize(None).normalize()
SINCE = NOW - pd.DateOffset(years=SINCE_YEARS)

CRYPTO_AGG = {
    "open": "first", "high": "max", "low": "min",
    "close": "last", "volume": "sum", "amount": "sum",
}
STOCK_AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def load_crypto_weekly(path: Path) -> pd.DataFrame:
    """bitget_{SYMBOL}_1h.parquet 평탄 캐시 → 주봉 (소문자 컬럼, dt 인덱스)."""
    df = pd.read_parquet(path)
    if "timestamp" not in df.columns:
        return pd.DataFrame()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df = df.set_index("dt").sort_index()
    cols = [c for c in CRYPTO_AGG if c in df.columns]
    agg = {c: CRYPTO_AGG[c] for c in cols}
    w = df.resample("W-MON", label="left", closed="left").agg(agg).dropna()
    return w


def load_stock_weekly(path: Path) -> pd.DataFrame:
    """FDR 1d (Open/High/Low/Close/Volume) → 주봉 → 소문자로 리네임."""
    df = pd.read_parquet(path)
    if "Close" not in df.columns:
        return pd.DataFrame()
    df = df.sort_index()
    w = df.resample("W-FRI").agg(STOCK_AGG).dropna()
    w = w.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })
    return w


def count_entries(df_weekly: pd.DataFrame) -> tuple[int, list[pd.Timestamp]]:
    """주봉 df에 전략 signal 적용, 최근 3년간 0→1 전환 개수와 시점 반환."""
    if df_weekly is None or df_weekly.empty:
        return 0, []
    if len(df_weekly) < 120:  # warmup 부족 (long_dd_lookback=100 등)
        return 0, []
    sig = ma_slope_turn_up.signal(df_weekly.reset_index(drop=True), {})
    sig.index = df_weekly.index  # dt 인덱스로 복구
    enters = (sig.diff() == 1)
    enters = enters & (enters.index >= SINCE)
    times = list(enters[enters].index)
    return len(times), times


def crypto_symbol_from_file(p: Path) -> str:
    # 새 구조: data/cache/crypto/1h/{SYMBOL}.parquet
    # 구 평탄 구조: bitget_{SYMBOL}_1h.parquet (호환 유지)
    stem = p.stem
    parts = stem.split("_")
    if len(parts) >= 3 and parts[0] == "bitget" and parts[-1] in ("1h", "1d"):
        return "_".join(parts[1:-1])
    return stem


def run_asset(name: str, files: list[Path], loader) -> pd.DataFrame:
    rows = []
    n = len(files)
    print(f"[{name}] {n} symbols", flush=True)
    for i, p in enumerate(files, 1):
        symbol = crypto_symbol_from_file(p) if name == "crypto" else p.stem
        try:
            df_w = loader(p)
            cnt, times = count_entries(df_w)
        except Exception as e:
            print(f"  ! {symbol}: {type(e).__name__}: {e}", flush=True)
            continue
        rows.append({
            "asset": name,
            "symbol": symbol,
            "n_entries_3y": cnt,
            "first_entry": times[0].date().isoformat() if times else "",
            "last_entry": times[-1].date().isoformat() if times else "",
            "weekly_bars": len(df_w),
        })
        if i % 50 == 0 or i == n:
            print(f"  [{name}] {i}/{n} done", flush=True)
    return pd.DataFrame(rows)


def main():
    print(f"window: {SINCE.date()} ~ {NOW.date()} ({(NOW - SINCE).days} days)")

    # --- 크립토 (1h 서브디렉터리 우선, 없으면 평탄) ---
    crypto_files = sorted(CRYPTO_1H_DIR.glob("*.parquet"))
    if not crypto_files:
        crypto_files = sorted(CRYPTO_DIR.glob("bitget_*_1h.parquet"))
    df_crypto = run_asset("crypto", crypto_files, load_crypto_weekly)

    # --- KR ---
    kr_files = sorted(KR_DIR.glob("*.parquet"))
    kr_files = [p for p in kr_files if not p.stem.startswith("_")]
    df_kr = run_asset("kr", kr_files, load_stock_weekly)

    # --- US ---
    us_files = sorted(US_DIR.glob("*.parquet")) if US_DIR.exists() else []
    us_files = [p for p in us_files if not p.stem.startswith("_")]
    df_us = run_asset("us", us_files, load_stock_weekly) if us_files else pd.DataFrame()

    all_df = pd.concat([d for d in [df_crypto, df_kr, df_us] if not d.empty], ignore_index=True)

    out_csv = OUT_DIR / "slope_turn_counts.csv"
    all_df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nsaved: {out_csv}")

    # 요약
    print("\n=== Summary (entries in last 3y) ===")
    for asset, sub in all_df.groupby("asset"):
        total_sig = int(sub["n_entries_3y"].sum())
        n_sym = len(sub)
        n_hit = int((sub["n_entries_3y"] > 0).sum())
        print(f"  [{asset}] symbols={n_sym}, with_signal={n_hit}, total_entries={total_sig}")

    # 분포
    print("\n=== Entry-count distribution per asset ===")
    for asset, sub in all_df.groupby("asset"):
        dist = sub["n_entries_3y"].value_counts().sort_index()
        line = ", ".join(f"{int(k)}→{int(v)}sym" for k, v in dist.items())
        print(f"  [{asset}] {line}")

    # Top 20 each asset
    print("\n=== Top symbols by entry count (asset별 상위 15) ===")
    for asset, sub in all_df.groupby("asset"):
        top = sub.sort_values("n_entries_3y", ascending=False).head(15)
        print(f"\n  [{asset}]")
        for _, r in top.iterrows():
            if r["n_entries_3y"] == 0:
                continue
            print(f"    {r['symbol']:>18s}  n={int(r['n_entries_3y'])}  "
                  f"first={r['first_entry']}  last={r['last_entry']}")


if __name__ == "__main__":
    main()
