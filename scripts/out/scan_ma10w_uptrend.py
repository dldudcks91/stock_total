"""주봉 MA10 위 + slope 양수 코인 스캐너.

조건 (현재 봉 기준 — 진행 중 주봉 포함):
  1. close[t] > MA10w[t]
  2. slope_2w(t) = MA10w[t] / MA10w[t-2] - 1 > 0

출력: 심볼, close, MA10w, gap_pct (close/MA10-1), slope_2w_pct
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from data.resample import load

CACHE_1D = ROOT / "data" / "cache" / "crypto" / "1d"


def scan(min_weeks: int = 14):
    rows = []
    symbols = sorted(p.stem for p in CACHE_1D.glob("*.parquet"))
    for sym in symbols:
        try:
            df = load(sym, "1w")
        except Exception:
            continue
        if df is None or len(df) < min_weeks:
            continue
        df = df.copy()
        df["ma10w"] = df["close"].rolling(10).mean()
        # 현재 진행 중 주봉 포함 (iloc[-1])
        if len(df) < 13:  # need t-2 of ma10w
            continue
        last_idx = -1
        close_t = df["close"].iloc[last_idx]
        ma10w_t = df["ma10w"].iloc[last_idx]
        ma10w_tm2 = df["ma10w"].iloc[last_idx - 2]
        if pd.isna(ma10w_t) or pd.isna(ma10w_tm2) or ma10w_tm2 <= 0:
            continue
        slope_2w = ma10w_t / ma10w_tm2 - 1
        gap = close_t / ma10w_t - 1
        if close_t > ma10w_t and slope_2w > 0:
            # 거래대금 (USDT) 최근 4주 합으로 활성도 (양수 인덱스로 변환)
            n = len(df)
            end = n + last_idx + 1  # last_idx=-1 → end=n, last_idx=-2 → end=n-1
            start = max(0, end - 4)
            amt_4w = df["amount"].iloc[start:end].sum()
            rows.append(
                {
                    "symbol": sym,
                    "close": close_t,
                    "ma10w": ma10w_t,
                    "gap_pct": gap * 100,
                    "slope_2w_pct": slope_2w * 100,
                    "amt_4w_M": amt_4w / 1e6,
                }
            )
    return pd.DataFrame(rows)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    df = scan()
    print(f"total: {len(df)} symbols pass (close>MA10w AND slope_2w>0)")
    if df.empty:
        return
    # 활성 코인만 (4주 거래대금 1M USDT 이상)
    active = df[df["amt_4w_M"] >= 1.0].copy()
    print(f"active (amt_4w>=1M USDT): {len(active)}")
    # slope_2w 내림차순
    active = active.sort_values("slope_2w_pct", ascending=False)
    pd.set_option("display.max_rows", 200)
    pd.set_option("display.float_format", lambda x: f"{x:.2f}")
    print()
    print("Top 50 by slope_2w_pct:")
    print(active.head(50).to_string(index=False))


if __name__ == "__main__":
    main()
