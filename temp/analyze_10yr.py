"""10년치 KOSPI + 외인 데이터 정성 분석."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

PATH = Path(__file__).parent / "kospi_10yr_weekly.parquet"
df = pd.read_parquet(PATH)

print(f"기간: {df.index.min().date()} ~ {df.index.max().date()} ({len(df)} 주)")
print()

# ===== (1) 연도별 요약 =====
print("=" * 100)
print("[1] 연도별 KOSPI 등락률 + 외인 누적 + 보유비중 변화")
print("=" * 100)
df["year"] = df.index.year
agg = df.groupby("year").agg(
    KOSPI_시작=("KOSPI_close", "first"),
    KOSPI_종가=("KOSPI_close", "last"),
    외인_연간_조=("외인_주간_순매수_억", lambda x: x.sum() / 10000),
    개인_연간_조=("개인_주간_순매수_억", lambda x: x.sum() / 10000),
    기관_연간_조=("기관_주간_순매수_억", lambda x: x.sum() / 10000),
    삼성외인_시작=("삼성전자_외인비중_%", "first"),
    삼성외인_종가=("삼성전자_외인비중_%", "last"),
)
agg["KOSPI등락%"] = ((agg["KOSPI_종가"] / agg["KOSPI_시작"] - 1) * 100).round(1)
agg["삼성외인_변화%p"] = (agg["삼성외인_종가"] - agg["삼성외인_시작"]).round(2)
agg = agg[["KOSPI_시작", "KOSPI_종가", "KOSPI등락%", "외인_연간_조", "개인_연간_조", "기관_연간_조", "삼성외인_시작", "삼성외인_종가", "삼성외인_변화%p"]]
print(agg.round(1).to_string())
print()

# ===== (2) 외인 매수↔KOSPI 상관 =====
print("=" * 100)
print("[2] 외인 주간 순매수 ↔ KOSPI 주간 수익률 회귀")
print("=" * 100)
df["KOSPI_ret_%"] = df["KOSPI_close"].pct_change() * 100
clean = df.dropna(subset=["외인_주간_순매수_억", "KOSPI_ret_%"])
import numpy as np
corr_w = clean["외인_주간_순매수_억"].corr(clean["KOSPI_ret_%"])
print(f"  주간 외인 순매수 ↔ 주간 KOSPI 수익률 상관: {corr_w:+.3f}  (n={len(clean)})")

# lag 분석
for lag in [-2, -1, 0, 1, 2, 4]:
    if lag >= 0:
        x = clean["외인_주간_순매수_억"]
        y = clean["KOSPI_ret_%"].shift(-lag)
    else:
        x = clean["외인_주간_순매수_억"].shift(-lag)
        y = clean["KOSPI_ret_%"]
    c = x.corr(y)
    direction = f"외인(t) ↔ KOSPI(t+{lag})" if lag >= 0 else f"외인(t{lag}) ↔ KOSPI(t)"
    print(f"  {direction:30s} : {c:+.3f}")

# 4주 누적 vs 4주 후 수익률 (중기)
df["외인_4주누적"] = df["외인_주간_순매수_억"].rolling(4).sum()
df["KOSPI_4주후수익률"] = df["KOSPI_close"].pct_change(4).shift(-4) * 100
clean2 = df.dropna(subset=["외인_4주누적", "KOSPI_4주후수익률"])
c2 = clean2["외인_4주누적"].corr(clean2["KOSPI_4주후수익률"])
print(f"  외인 4주누적 ↔ 4주 후 KOSPI 수익률: {c2:+.3f}")

# ===== (3) 보유비중↔KOSPI =====
print()
print("=" * 100)
print("[3] 삼성전자 외인 비중 ↔ KOSPI 레벨 상관")
print("=" * 100)
c3 = df["삼성전자_외인비중_%"].corr(df["KOSPI_close"])
print(f"  비중(레벨) ↔ KOSPI(레벨) 상관: {c3:+.3f}")
c4 = df["삼성전자_외인비중_%"].diff().corr(df["KOSPI_ret_%"])
print(f"  비중(주간변화) ↔ KOSPI(주간수익률) 상관: {c4:+.3f}")

# ===== (4) 비중 피크/저점 =====
print()
print("=" * 100)
print("[4] 삼성전자 외인 비중 — 10년 피크/저점")
print("=" * 100)
peak_idx = df["삼성전자_외인비중_%"].idxmax()
trough_idx = df["삼성전자_외인비중_%"].idxmin()
print(f"  10년 최고 ({peak_idx.date()}): {df.loc[peak_idx, '삼성전자_외인비중_%']:.2f}%  KOSPI = {df.loc[peak_idx, 'KOSPI_close']:.0f}")
print(f"  10년 최저 ({trough_idx.date()}): {df.loc[trough_idx, '삼성전자_외인비중_%']:.2f}%  KOSPI = {df.loc[trough_idx, 'KOSPI_close']:.0f}")

# ===== (5) 외인 누적 매도 vs 시총 =====
print()
print("=" * 100)
print("[5] 외인 10년 누적 = ?")
print("=" * 100)
print(f"  외인 10년 누적: {df['외인_주간_순매수_억'].sum() / 10000:+.1f} 조")
print(f"  개인 10년 누적: {df['개인_주간_순매수_억'].sum() / 10000:+.1f} 조")
print(f"  기관 10년 누적: {df['기관_주간_순매수_억'].sum() / 10000:+.1f} 조")
print(f"  금융투자 10년 누적: {df['금융투자_주간_순매수_억'].sum() / 10000:+.1f} 조")
