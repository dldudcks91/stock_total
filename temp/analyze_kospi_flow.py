"""KOSPI 9주체 매매동향 정량 분석.

temp/kospi_investor_flow.parquet 을 읽어
- 주체별 6개월 누적 / 월별 합계
- 외국인 단독 매도일 등 이상 패턴
- 주체간 상관 (특히 개인↔외국인)
- 단기 시그널 (5/20일 누적, 연속 매도일)
을 콘솔 표로 출력.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

PATH = Path(__file__).parent / "kospi_investor_flow.parquet"
df = pd.read_parquet(PATH)

# 분석 대상 주체
SUBJECTS = ["개인", "외국인", "기관계", "기타법인"]
INSTITUTIONS = ["금융투자", "보험", "투신", "기타금융", "은행", "연기금등"]

print(f"기간: {df.index.min().date()} ~ {df.index.max().date()} ({len(df)}영업일)")
print(f"단위: 억원 (네이버 표시 기준)")
print()

# ----- (1) 6개월 누적 -----
print("=" * 60)
print("[1] 주체별 6개월 누적 순매수")
print("=" * 60)
cum_main = df[SUBJECTS].sum().sort_values()
print(cum_main.to_frame("누적(억원)").to_string())
print()
print("(기관 하위)")
cum_inst = df[INSTITUTIONS].sum().sort_values()
print(cum_inst.to_frame("누적(억원)").to_string())
print()

# ----- (2) 월별 합계 -----
print("=" * 60)
print("[2] 월별 순매수 (억원)")
print("=" * 60)
monthly = df[SUBJECTS + INSTITUTIONS].groupby(pd.Grouper(freq="MS")).sum()
monthly.index = monthly.index.strftime("%Y-%m")
print(monthly.to_string())
print()

# ----- (3) 주체 간 상관 -----
print("=" * 60)
print("[3] 주체별 일일 순매수 상관 (Pearson)")
print("=" * 60)
corr = df[SUBJECTS + INSTITUTIONS].corr().round(2)
print(corr.to_string())
print()

# ----- (4) 외국인 5/20일 누적 (추세 시그널) -----
print("=" * 60)
print("[4] 외국인 N일 누적 (최근 10영업일)")
print("=" * 60)
window = df["외국인"].copy().to_frame("외국인_일일")
window["외국인_5일누적"] = df["외국인"].rolling(5).sum()
window["외국인_20일누적"] = df["외국인"].rolling(20).sum()
print(window.tail(10).round(0).to_string())
print()

# ----- (5) 외국인 vs 개인 다이버전스 -----
print("=" * 60)
print("[5] 단일일 강한 시그널 (외국인 ≤ -3,000억 + 개인 ≥ +3,000억)")
print("=" * 60)
panic = df[(df["외국인"] <= -3000) & (df["개인"] >= 3000)][SUBJECTS]
print(f"{len(panic)} 일 발견:")
print(panic.to_string())
print()

# ----- (6) 외국인 연속 매도일 -----
print("=" * 60)
print("[6] 외국인 연속 순매도 streak (3일 이상)")
print("=" * 60)
sign = (df["외국인"] < 0).astype(int)
# streak 계산
group = (sign != sign.shift()).cumsum()
streaks = (
    pd.DataFrame({"sign": sign, "g": group, "fx": df["외국인"]})
    .groupby("g")
    .agg(start=("fx", lambda s: s.index.min()),
         end=("fx", lambda s: s.index.max()),
         days=("fx", "size"),
         sum_억=("fx", "sum"),
         sign=("sign", "first"))
)
neg_streaks = streaks[(streaks["sign"] == 1) & (streaks["days"] >= 3)].copy()
neg_streaks = neg_streaks.sort_values("sum_억").head(10)
neg_streaks["start"] = neg_streaks["start"].dt.strftime("%Y-%m-%d")
neg_streaks["end"] = neg_streaks["end"].dt.strftime("%Y-%m-%d")
print(neg_streaks[["start", "end", "days", "sum_억"]].to_string(index=False))
print()

# ----- (7) 연기금 (장기 매수 주체) 동향 -----
print("=" * 60)
print("[7] 연기금등 누적 동향 (월별)")
print("=" * 60)
pension = df["연기금등"].groupby(pd.Grouper(freq="MS")).agg(["sum", "count"])
pension.columns = ["월합계_억", "영업일"]
pension.index = pension.index.strftime("%Y-%m")
print(pension.to_string())
print()

# ----- (8) 금융투자 (외국계 증권사 자기매매 포함) 동향 -----
print("=" * 60)
print("[8] 금융투자 (증권사 자기매매·외국계 서울지점 포함) — 외국인 매도 ↔ 금융투자 동향")
print("=" * 60)
print(f"기간 합계 외국인:   {df['외국인'].sum():>10,.0f} 억원")
print(f"기간 합계 금융투자: {df['금융투자'].sum():>10,.0f} 억원")
print(f"  외국인↔금융투자 일일 상관: {df['외국인'].corr(df['금융투자']):+.2f}")
print(f"  외국인↔연기금등 일일 상관: {df['외국인'].corr(df['연기금등']):+.2f}")
print(f"  외국인↔개인       일일 상관: {df['외국인'].corr(df['개인']):+.2f}")
print()

# ----- (9) 마지막 5일 요약 -----
print("=" * 60)
print("[9] 최근 5영업일 풀 테이블")
print("=" * 60)
print(df[SUBJECTS + INSTITUTIONS].tail(5).to_string())
