"""NVDA 최근 3년 월간 가격 추이."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import FinanceDataReader as fdr

sys.stdout.reconfigure(encoding="utf-8")

# NVDA 3년치
df = fdr.DataReader("NVDA", "2022-01-01", "2026-05-13")
# 월별 (월말 종가)
m = df.resample("M").last()
m["월간_시가"] = df["Open"].resample("M").first()
m["월간_고가"] = df["High"].resample("M").max()
m["월간_저가"] = df["Low"].resample("M").min()
m["월간_거래량_M"] = (df["Volume"].resample("M").sum() / 1e6).round(0)
# 월간 수익률 (월말 종가 기준)
m["월간_수익률_%"] = (m["Close"].pct_change() * 100).round(1)
# 시작 대비 누적 수익률
m["누적_수익률_%"] = ((m["Close"] / m["Close"].iloc[0] - 1) * 100).round(0)

print(f"NVDA 월별 가격 추이 ({m.index[0].date()} ~ {m.index[-1].date()})\n")
print(f"{'월':<10s} {'종가':>10s} {'시가':>10s} {'고가':>10s} {'저가':>10s} {'월간%':>9s} {'누적%':>9s} {'거래량(M)':>10s}")
print("-" * 90)
for d, r in m.iterrows():
    close = r["Close"]
    open_ = r["월간_시가"]
    high = r["월간_고가"]
    low = r["월간_저가"]
    chg = r["월간_수익률_%"]
    cum = r["누적_수익률_%"]
    vol = r["월간_거래량_M"]
    chg_s = f"{chg:+.1f}%" if pd.notna(chg) else "  -"
    cum_s = f"{cum:+.0f}%" if pd.notna(cum) else "  -"
    print(f"{d.strftime('%Y-%m'):<10s} ${close:>9.2f} ${open_:>9.2f} ${high:>9.2f} ${low:>9.2f} {chg_s:>9s} {cum_s:>9s} {vol:>10.0f}")

# 통계 요약
print()
print("=" * 50)
print(f"기간: {m.index[0].date()} ~ {m.index[-1].date()} (37개월)")
print(f"시작 가격: ${m['Close'].iloc[0]:.2f}")
print(f"종료 가격: ${m['Close'].iloc[-1]:.2f}")
print(f"총 수익률: {((m['Close'].iloc[-1]/m['Close'].iloc[0]-1)*100):+.0f}%")
print(f"역대 최고가: ${m['월간_고가'].max():.2f} ({m['월간_고가'].idxmax().strftime('%Y-%m')})")
print(f"월간 최대 상승: +{m['월간_수익률_%'].max():.1f}% ({m['월간_수익률_%'].idxmax().strftime('%Y-%m')})")
print(f"월간 최대 하락: {m['월간_수익률_%'].min():.1f}% ({m['월간_수익률_%'].idxmin().strftime('%Y-%m')})")
