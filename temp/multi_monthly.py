"""NVDA + MU + 삼성 + 하닉 동기간 비교."""
from __future__ import annotations
import sys
import pandas as pd
import FinanceDataReader as fdr

sys.stdout.reconfigure(encoding="utf-8")

START = "2022-01-01"
END = "2026-05-13"

tickers = {
    "NVDA": ("NVDA", "USD"),
    "MU": ("MU", "USD"),
    "삼성": ("005930", "KRW"),
    "하닉": ("000660", "KRW"),
}

# 연도별 수익률
print("=" * 70)
print("[A] 연도별 수익률 (시작가 → 종료가)")
print("=" * 70)
print(f"{'종목':<10s} {'2022':>15s} {'2023':>15s} {'2024':>15s} {'2025':>15s} {'2026YTD':>15s}")
print("-" * 90)

# 종목별 누적 수익률 (2022.1.1 시작)
cum_data = {}
for label, (code, _) in tickers.items():
    df = fdr.DataReader(code, START, END)
    cum_data[label] = df["Close"]
    yearly = {}
    for y in [2022, 2023, 2024, 2025, 2026]:
        if y == 2026:
            year_df = df.loc[f"{y}-01":END]
        else:
            year_df = df.loc[f"{y}-01":f"{y}-12"]
        if year_df.empty: continue
        start = year_df["Close"].iloc[0]
        end_v = year_df["Close"].iloc[-1]
        yearly[y] = (end_v/start - 1) * 100
    row = f"{label:<10s}"
    for y in [2022, 2023, 2024, 2025, 2026]:
        v = yearly.get(y)
        row += f"{v:>+14.1f}%" if v is not None else f"{'-':>15s}"
    print(row)

print()
print("=" * 70)
print("[B] 누적 (2022.1.1 시작 기준)")
print("=" * 70)
print(f"{'종목':<10s} {'시작가':>12s} {'현재가':>12s} {'배율':>10s} {'누적%':>10s}")
print("-" * 60)
for label, (code, ccy) in tickers.items():
    s = cum_data[label]
    start = s.iloc[0]
    cur = s.iloc[-1]
    ratio = cur / start
    cum = (ratio - 1) * 100
    sym = "$" if ccy == "USD" else ""
    print(f"{label:<10s} {sym}{start:>10,.2f} {sym}{cur:>10,.2f} {ratio:>9.1f}x {cum:>+9.0f}%")

print()
print("=" * 70)
print("[C] 저점 → 현재 (각 종목 2022~현재 저점부터)")
print("=" * 70)
print(f"{'종목':<10s} {'저점':>12s} {'저점월':>12s} {'현재가':>12s} {'배율':>10s}")
print("-" * 60)
for label, (code, ccy) in tickers.items():
    s = cum_data[label]
    low = s.min()
    low_d = s.idxmin().strftime("%Y-%m")
    cur = s.iloc[-1]
    ratio = cur / low
    sym = "$" if ccy == "USD" else ""
    print(f"{label:<10s} {sym}{low:>10,.2f} {low_d:>12s} {sym}{cur:>10,.2f} {ratio:>9.1f}x")

print()
print("=" * 70)
print("[D] 1년 단위 최대 상승 (rolling 252 영업일)")
print("=" * 70)
print(f"{'종목':<10s} {'최대 1년 수익률':>16s} {'시작':>12s} {'종료':>12s}")
print("-" * 60)
for label, (code, ccy) in tickers.items():
    s = cum_data[label]
    rolling = s.pct_change(252) * 100
    max_v = rolling.max()
    max_idx = rolling.idxmax()
    start_idx = max_idx - pd.Timedelta(days=365)
    nearest_start = s.index[s.index.get_indexer([start_idx], method="nearest")[0]]
    print(f"{label:<10s} {max_v:>+15.0f}% {nearest_start.strftime('%Y-%m'):>12s} {max_idx.strftime('%Y-%m'):>12s}")
