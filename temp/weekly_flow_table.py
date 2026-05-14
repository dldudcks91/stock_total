"""KOSPI 9주체 매매동향 — 주별 집계 + 외국인 보유비중 추정.

주별 집계는 정확값.
외국인 보유비중은 KRX 직접 시계열 호출이 환경상 막혀 있어
- 시작 시점(2025-11-13) 외국인 보유율 32.0% 가정 (장기 평균 부근)
- 코스피 시총 ≈ 2,500조원 가정
- 외인 누적 순매도를 시총으로 나눠 **추정 변화** 계산
한 근사값을 표시한다. (정밀값은 KRX 정보데이터시스템의
"투자자별 보유현황" 페이지에서 CSV 다운로드 후 보강 가능.)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

PATH = Path(__file__).parent / "kospi_investor_flow.parquet"
df = pd.read_parquet(PATH)

# 단위: 억원
SUBJECTS_MAIN = ["개인", "외국인", "기관계", "기타법인"]
INSTITUTIONS = ["금융투자", "보험", "투신", "기타금융", "은행", "연기금등"]

# ===== (1) 주별 집계 =====
# 한 주 = 월요일 시작 (anchor='W-MON' → 일요일 끝의 라벨), label 을 주 시작일로 정렬
weekly = df[SUBJECTS_MAIN + INSTITUTIONS].groupby(pd.Grouper(freq="W-FRI")).sum()
# 영업일 수도 같이
weekly["영업일수"] = df[SUBJECTS_MAIN[0]].groupby(pd.Grouper(freq="W-FRI")).count()
weekly = weekly[weekly["영업일수"] > 0]  # 빈 주 제거
weekly.index = weekly.index.strftime("%Y-%m-%d (W%U)")

# ===== (2) 외국인 보유비중 추정 =====
START_RATIO = 0.320   # 가정: 2025-11-13 외국인 보유율 32.0%
MARKET_CAP_TRILLION = 2500.0  # 코스피 시총 가정 (조원)
MARKET_CAP_EOK = MARKET_CAP_TRILLION * 10_000  # 1조원 = 10,000억원

# 일별 누적 외국인 순매수(매도면 음수)
fx_cum = df["외국인"].cumsum()
# 보유 시가총액 변화 = 누적 순매수 (단순 근사: 가격 변화는 무시, 거래만 반영)
# 보유 비중 변화 = 누적 순매수 / 시총
ratio_change_pp = fx_cum / MARKET_CAP_EOK * 100  # 비중 변화(%p)
ratio_est = START_RATIO * 100 + ratio_change_pp  # 추정 비중(%)

ratio_df = pd.DataFrame({
    "외인_일일_억": df["외국인"],
    "외인_누적_억": fx_cum,
    "추정_보유비중_%": ratio_est.round(2),
})

# 주별 비중 (각 주 마지막 영업일 기준)
ratio_weekly = ratio_df.resample("W-FRI").last().dropna()
ratio_weekly["외인_주간_억"] = df["외국인"].resample("W-FRI").sum()
ratio_weekly.index = ratio_weekly.index.strftime("%Y-%m-%d")

# ===== 출력 =====
print("=" * 90)
print("[A] 주별 9주체 매매동향 (억원, 한 주 = 월~금)")
print("=" * 90)
print(weekly.to_string())
print()

print("=" * 90)
print("[B] 주별 외국인 누적 매도 + 추정 보유비중 (KOSPI)")
print(f"    가정: 시작(2025-11-14주) 외국인 보유율 = {START_RATIO*100:.1f}%,  코스피 시총 ≈ {MARKET_CAP_TRILLION:.0f}조원")
print(f"    *추정 방법: 누적 외인 순매수 / 시총 으로 비중 변화(p) 계산 (가격 변화 무시).")
print(f"    *정확한 일별 보유비중은 KRX 정보데이터시스템 CSV로 보강 필요.")
print("=" * 90)
print(ratio_weekly[["외인_주간_억", "외인_누적_억", "추정_보유비중_%"]].to_string())
print()

# 저장
out_dir = Path(__file__).parent
weekly.to_csv(out_dir / "kospi_flow_weekly.csv", encoding="utf-8-sig")
ratio_weekly.to_csv(out_dir / "kospi_foreign_ratio_estimate.csv", encoding="utf-8-sig")
print(f"saved: {out_dir / 'kospi_flow_weekly.csv'}")
print(f"saved: {out_dir / 'kospi_foreign_ratio_estimate.csv'}")
