"""크립토 전종목 — 일봉 MA20 이상 + 주봉 MA10 이상 스캔.

조건 (라이브 ticker 로 진행 중 봉 합성 후):
  1. close_1d[t] >= MA20_1d[t]
  2. close_1w[t] >= MA10_1w[t]
  (close 위치만, slope 조건 없음)

출력: 심볼, live_close, MA20d/gap, MA10w/gap, 4주 거래대금(M USDT)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.out.scan_ma10w_uptrend_live import (
    fetch_live_tickers,
    patch_with_live,
    resample_to_weekly,
)

CACHE_1D = ROOT / "data" / "cache" / "crypto" / "1d"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("[1/3] fetching live tickers ...")
    tickers = fetch_live_tickers()
    print(f"      got {len(tickers)} symbols live")

    print("[2/3] scanning ...")
    rows = []
    symbols = sorted(p.stem for p in CACHE_1D.glob("*.parquet"))
    for sym in symbols:
        try:
            df_1d = pd.read_parquet(CACHE_1D / f"{sym}.parquet")
        except Exception:
            continue
        if len(df_1d) < 80:
            continue
        tick = tickers.get(sym)
        if tick is not None:
            df_1d = patch_with_live(df_1d, tick)

        # 일봉 MA20
        df_1d = df_1d.copy()
        df_1d["ma20d"] = df_1d["close"].rolling(20).mean()
        close_d = df_1d["close"].iloc[-1]
        ma20d = df_1d["ma20d"].iloc[-1]
        if pd.isna(ma20d) or ma20d <= 0:
            continue

        # 주봉 MA10
        df_1w = resample_to_weekly(df_1d)
        if len(df_1w) < 11:
            continue
        df_1w["ma10w"] = df_1w["close"].rolling(10).mean()
        close_w = df_1w["close"].iloc[-1]
        ma10w = df_1w["ma10w"].iloc[-1]
        if pd.isna(ma10w) or ma10w <= 0:
            continue

        if close_d >= ma20d and close_w >= ma10w:
            n = len(df_1w)
            start = max(0, n - 4)
            amt_4w = df_1w["amount"].iloc[start:n].sum()
            rows.append(
                {
                    "symbol": sym,
                    "live_close": close_d,
                    "ma20d": ma20d,
                    "d_gap_pct": (close_d / ma20d - 1) * 100,
                    "ma10w": ma10w,
                    "w_gap_pct": (close_w / ma10w - 1) * 100,
                    "amt_4w_M": amt_4w / 1e6,
                }
            )

    df = pd.DataFrame(rows)
    print(f"[3/3] total pass: {len(df)}")
    if df.empty:
        return

    pd.set_option("display.max_rows", 300)
    pd.set_option("display.float_format", lambda x: f"{x:.2f}")

    # Tier 1 — 활성 (amt_4w >= 10M USDT)
    t1 = df[df["amt_4w_M"] >= 10.0].sort_values("amt_4w_M", ascending=False)
    print(f"\nTier 1 — amt_4w >= 10M USDT: {len(t1)} symbols")
    print(t1.to_string(index=False))

    # Tier 2 — 중활성 (1M ~ 10M)
    t2 = df[(df["amt_4w_M"] >= 1.0) & (df["amt_4w_M"] < 10.0)].sort_values(
        "amt_4w_M", ascending=False
    )
    print(f"\nTier 2 — amt_4w 1M ~ 10M USDT: {len(t2)} symbols (skipping detail)")
    print(t2.head(20).to_string(index=False))

    # Tier 3 — 저활성
    t3 = df[df["amt_4w_M"] < 1.0]
    print(f"\nTier 3 — amt_4w < 1M USDT: {len(t3)} symbols (omitted)")


if __name__ == "__main__":
    main()
