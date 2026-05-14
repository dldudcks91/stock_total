"""KOSPI 과열 지표 — 사이클 비교."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

df = pd.read_parquet(Path(__file__).parent / "kospi_overheating_weekly.parquet")
df["year"] = df.index.year
df["KOSPI_ret_%"] = df["KOSPI"].pct_change() * 100

print("=" * 90)
print("[A] 연도별 평균 — 과열 지표 비교")
print("=" * 90)
agg = df.groupby("year").agg(
    KOSPI_연말=("KOSPI", "last"),
    시총GDP_평균=("시총GDP_%", "mean"),
    시총GDP_최고=("시총GDP_%", "max"),
    거래대금일평균_조=("거래대금_일평균_조", "mean"),
    거래대금일평균_최고_조=("거래대금_일평균_조", "max"),
    신용잔고_평균_조=("신용잔고_조", "mean"),
    신용잔고_최고_조=("신용잔고_조", "max"),
    예탁금_평균_조=("예탁금_조", "mean"),
).round(1)
print(agg.to_string())
print()

print("=" * 90)
print("[B] 역사적 고점 비교 — 10년 vs 현재")
print("=" * 90)

# 주요 고점 후보 시점들
markers = {
    "2018.01 고점 직전": "2018-01-31",
    "2020.03 코로나 저점": "2020-03-23",
    "2021.06 동학개미 고점": "2021-06-25",
    "2022.09 약세장 저점": "2022-09-30",
    "2024.07 직전 고점": "2024-07-12",
    "2025.04 저점": "2025-04-04",
    "현재 (2026.05.15)": "2026-05-15",
}

cols = ["KOSPI", "시총_조", "시총GDP_%", "거래대금_일평균_조", "신용잔고_조", "예탁금_조", "외인비중_%"]
rows = []
for label, d in markers.items():
    target = pd.to_datetime(d)
    nearest = df.index[df.index.get_indexer([target], method="nearest")[0]]
    row = df.loc[nearest, cols].to_dict()
    row["시점"] = label
    row["날짜"] = nearest.strftime("%Y-%m-%d")
    rows.append(row)
hist = pd.DataFrame(rows)[["시점", "날짜"] + cols].round(1)
print(hist.to_string(index=False))
print()

# === 거품 시그널 종합 점수 ===
print("=" * 90)
print("[C] 거품 시그널 — 백분위 (10년 분포 내 위치)")
print("=" * 90)
recent = df.iloc[-1]
indicators = {
    "시총GDP_%": "거시 밸류에이션 (Buffett)",
    "거래대금_일평균_조": "거래 광기",
    "신용잔고_조": "개인 레버리지",
    "예탁금_조": "자금 유입",
}
print(f"{'지표':<20s} {'현재값':>10s} {'10년 최저':>12s} {'10년 최고':>12s} {'백분위':>10s}")
print("-" * 70)
for col, desc in indicators.items():
    cur = recent[col]
    mn = df[col].min()
    mx = df[col].max()
    pct = (df[col] < cur).mean() * 100
    print(f"{desc:<20s} {cur:>10.1f} {mn:>12.1f} {mx:>12.1f} {pct:>9.0f}%")
print()

# === 사이클 단계 식별 ===
print("=" * 90)
print("[D] 2025-26 폭등 vs 2020-21 동학개미 — 동일 시점 비교")
print("=" * 90)

# 2020.3 저점 ~ 2021.6 고점 (15개월간 +108%)
# 2025.4 저점 ~ 현재 (13개월간 +215%)
cycle_a = df.loc["2020-03-27":"2021-06-25"].copy()
cycle_b = df.loc["2025-04-04":"2026-05-15"].copy()

print(f"\n  2020.3.27 ~ 2021.6.25 (15개월, KOSPI {cycle_a['KOSPI'].iloc[0]:.0f} → {cycle_a['KOSPI'].iloc[-1]:.0f}, +{(cycle_a['KOSPI'].iloc[-1]/cycle_a['KOSPI'].iloc[0]-1)*100:.0f}%):")
print(f"    시총/GDP    : {cycle_a['시총GDP_%'].iloc[0]:.0f}% → {cycle_a['시총GDP_%'].iloc[-1]:.0f}% ({cycle_a['시총GDP_%'].max():.0f}% 최고)")
print(f"    거래대금일평 : {cycle_a['거래대금_일평균_조'].iloc[0]:.1f}조 → {cycle_a['거래대금_일평균_조'].iloc[-1]:.1f}조 ({cycle_a['거래대금_일평균_조'].max():.1f}조 최고)")
print(f"    신용잔고    : {cycle_a['신용잔고_조'].iloc[0]:.1f}조 → {cycle_a['신용잔고_조'].iloc[-1]:.1f}조 ({cycle_a['신용잔고_조'].max():.1f}조 최고)")
print(f"    외인비중    : {cycle_a['외인비중_%'].iloc[0]:.1f}% → {cycle_a['외인비중_%'].iloc[-1]:.1f}%")

print(f"\n  2025.4.4 ~ 2026.5.15 (13개월, KOSPI {cycle_b['KOSPI'].iloc[0]:.0f} → {cycle_b['KOSPI'].iloc[-1]:.0f}, +{(cycle_b['KOSPI'].iloc[-1]/cycle_b['KOSPI'].iloc[0]-1)*100:.0f}%):")
print(f"    시총/GDP    : {cycle_b['시총GDP_%'].iloc[0]:.0f}% → {cycle_b['시총GDP_%'].iloc[-1]:.0f}% ({cycle_b['시총GDP_%'].max():.0f}% 최고)")
print(f"    거래대금일평 : {cycle_b['거래대금_일평균_조'].iloc[0]:.1f}조 → {cycle_b['거래대금_일평균_조'].iloc[-1]:.1f}조 ({cycle_b['거래대금_일평균_조'].max():.1f}조 최고)")
print(f"    신용잔고    : {cycle_b['신용잔고_조'].iloc[0]:.1f}조 → {cycle_b['신용잔고_조'].iloc[-1]:.1f}조 ({cycle_b['신용잔고_조'].max():.1f}조 최고)")
print(f"    외인비중    : {cycle_b['외인비중_%'].iloc[0]:.1f}% → {cycle_b['외인비중_%'].iloc[-1]:.1f}%")
