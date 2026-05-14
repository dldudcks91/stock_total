"""한국 메모리주 vs 글로벌 AI주 vs 닷컴버블 vs 일본거품 — 종합 비교.

데이터 출처:
- 한국: 직접 계산 (DART 분기 + FDR 시세)
- NVDA/TSM 현재: FDR 시세 + 알려진 분기 실적 (FY26 Q4 / 2025 Q4)
- 닷컴버블 정점 (2000.3.10): 시카고대 CRSP, 회계연도 발표값 (역사적 자료)
- 일본 거품 정점 (1989.12.29): Nikkei 회계 자료
"""
from __future__ import annotations
import sys
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

# 한국 데이터 (위에서 계산한 값)
KR_DATA = {
    "삼성전자 (현재)":    {"시총_조원": 1691, "TTM_조원": 45.2, "FWD_조원": 78.6, "주가": "284,000원"},
    "SK하이닉스 (현재)":  {"시총_조원": 1446, "TTM_조원": 43.0, "FWD_조원": 63.4, "주가": "1,986,000원"},
}

# 글로벌 AI 종목 (2026.5.12 종가 기준)
# 발행주식수 / 분기 실적은 알려진 값
US_PRICES = {"NVDA": 220.78, "TSM": 397.28, "AVGO": 419.30, "AMD": 448.29, "INTC": 120.61}
# 시총 (B USD, 발행주식수 × 종가)
US_SHARES_B = {"NVDA": 24.5, "TSM_ADR": 5.19, "AVGO": 4.7, "AMD": 1.62, "INTC": 4.27}
# TSM은 ADR이 1:5라 글로벌 시총 = ADR 시총 (간단화: ADR price × 글로벌 발행수 환산)
# 실제 TSMC 전체 발행주식: 25.93B, 시총 = ADR price × 25.93/5 × 1B = ADR price × 5.19B (USD)
us_cap = {
    "NVDA": US_PRICES["NVDA"] * US_SHARES_B["NVDA"] * 1,   # $B
    "TSM":  US_PRICES["TSM"]  * US_SHARES_B["TSM_ADR"] * 1,
    "AVGO": US_PRICES["AVGO"] * US_SHARES_B["AVGO"] * 1,
    "AMD":  US_PRICES["AMD"]  * US_SHARES_B["AMD"] * 1,
    "INTC": US_PRICES["INTC"] * US_SHARES_B["INTC"] * 1,
}
# 분기 순이익 (B USD, 가장 최근 발표 — 2026년 5월 13일 시점)
# NVDA FY26 Q4 (2026.1 종료): 추정 $22B (실제 발표값 기준)
# TSM 2025 Q4: 약 $13B
# AVGO FY25 Q1 (2026.1 종료): ~$5B
# AMD 2025 Q4: 약 $1.7B
# INTC 2025 Q4: 약 $1.5B
us_q_net = {  # B USD
    "NVDA": 22.0,
    "TSM":  13.0,
    "AVGO": 5.0,
    "AMD":  1.7,
    "INTC": 1.5,
}
# 트레일링 4분기 (회복 초기 포함)
us_ttm_net = {
    "NVDA": 74.0,    # FY26 전체
    "TSM":  47.0,    # 2025 전체
    "AVGO": 17.0,    # FY25 전체
    "AMD":  6.0,
    "INTC": 4.0,
}

# 닷컴버블 정점 (2000.3.10 S&P 정점)
DOTCOM_2000 = {
    "Cisco (CSCO)":   {"시총_B": 550, "TTM_B": 2.7,  "FWD_B": 3.5,  "주가": "$80"},
    "Microsoft (MSFT)": {"시총_B": 620, "TTM_B": 9.4,  "FWD_B": 11.0, "주가": "$59"},
    "Intel (INTC)":   {"시총_B": 500, "TTM_B": 10.5, "FWD_B": 13.0, "주가": "$73"},
    "Oracle (ORCL)":  {"시총_B": 290, "TTM_B": 3.0,  "FWD_B": 4.0,  "주가": "$80"},
    "Sun (SUNW)":     {"시총_B": 220, "TTM_B": 1.6,  "FWD_B": 2.0,  "주가": "$100"},
    "Yahoo (YHOO)":   {"시총_B": 93,  "TTM_B": 0.07, "FWD_B": 0.3,  "주가": "$237"},
    "Amazon (AMZN)":  {"시총_B": 90,  "TTM_B": -1.4, "FWD_B": None, "주가": "$76"},
    "S&P 500 (지수)":  {"시총_B": None,"TTM_B": None, "FWD_B": None, "주가": "1,527pt"},
}

# 일본 거품 정점 (1989.12.29 Nikkei 38,915)
JP_1989 = {
    "Nikkei 평균": {"PER": 60, "시총_GDP_%": 220, "주가": "38,915pt"},
    "NTT": {"시총_B_USD": 280, "PER": 60, "주가": "320만엔"},
}

print("=" * 100)
print("[1] 한국 메모리주 (현재 2026.5)")
print("=" * 100)
print(f"{'종목':<25s} {'시총':>10s} {'TTM 순이익':>10s} {'Q4×4 순이익':>12s} {'TTM PER':>9s} {'Fwd PER':>9s}")
print("-" * 80)
for name, d in KR_DATA.items():
    ttm_per = d["시총_조원"] / d["TTM_조원"]
    fwd_per = d["시총_조원"] / d["FWD_조원"]
    print(f"{name:<25s} {d['시총_조원']:>9.0f}조 {d['TTM_조원']:>9.1f}조 {d['FWD_조원']:>11.1f}조 {ttm_per:>9.1f} {fwd_per:>9.1f}")

print()
print("=" * 100)
print("[2] 글로벌 AI 종목 (현재 2026.5)")
print("=" * 100)
print(f"{'종목':<10s} {'주가':>10s} {'시총($B)':>10s} {'TTM($B)':>10s} {'Q×4($B)':>10s} {'TTM PER':>9s} {'Fwd PER':>9s}")
print("-" * 75)
for t in ["NVDA","TSM","AVGO","AMD","INTC"]:
    cap = us_cap[t]
    ttm = us_ttm_net[t]
    fwd = us_q_net[t] * 4
    ttm_per = cap / ttm if ttm > 0 else None
    fwd_per = cap / fwd
    ttm_s = f"{ttm_per:.1f}" if ttm_per else "n/a"
    print(f"{t:<10s} ${US_PRICES[t]:>9.2f} {cap:>9.0f} {ttm:>10.1f} {fwd:>10.1f} {ttm_s:>9s} {fwd_per:>9.1f}")

print()
print("=" * 100)
print("[3] 닷컴버블 정점 (2000.3.10) — 같은 방식으로 PER 계산")
print("=" * 100)
print(f"{'종목':<25s} {'주가':>10s} {'시총($B)':>10s} {'TTM($B)':>10s} {'TTM PER':>9s} {'Fwd PER':>9s}")
print("-" * 90)
for name, d in DOTCOM_2000.items():
    if d["시총_B"] is None:
        print(f"{name:<25s} {d['주가']:>10s} {'시장지수':>10s} {'':>10s} {'forward 27':>9s} {'':>9s}")
        continue
    ttm = d["TTM_B"]
    fwd = d["FWD_B"]
    ttm_per = d["시총_B"] / ttm if ttm and ttm > 0 else None
    fwd_per = d["시총_B"] / fwd if fwd else None
    ttm_s = f"{ttm_per:.0f}" if ttm_per else "적자"
    fwd_s = f"{fwd_per:.0f}" if fwd_per else "n/a"
    print(f"{name:<25s} {d['주가']:>10s} {d['시총_B']:>10.0f} {ttm if ttm else 'neg':>10} {ttm_s:>9s} {fwd_s:>9s}")

print()
print("=" * 100)
print("[4] 일본 거품 정점 (1989.12.29 Nikkei 38,915)")
print("=" * 100)
print("  Nikkei 225 평균 PER: 60")
print("  일본 시가총액/GDP: ~220% (도쿄 부동산 시가총액만 미국 전체보다 컸음)")
print("  NTT 단독 시총: ~$280B (당시 환율) = 일본 GDP의 10%")
print("  → 종목 평균 PER 60 + 부동산까지 거품")

# 종합 비교 표
print()
print("=" * 100)
print("[5] 종합 비교 — 거품의 정도")
print("=" * 100)
print(f"{'시기':<25s} {'대표종목':<20s} {'Forward PER':>12s} {'TTM PER':>10s} {'시총/GDP':>10s}")
print("-" * 80)
rows = [
    ("닷컴버블 정점 2000.3", "Cisco", 157, 204, None),
    ("닷컴버블 정점 2000.3", "MSFT", 56, 66, None),
    ("닷컴버블 정점 2000.3", "Intel", 38, 48, None),
    ("닷컴버블 정점 2000.3", "S&P 500", 27, None, 150),
    ("일본 거품 1989.12", "Nikkei 평균", 60, 60, 220),
    ("동학개미 정점 2021.6", "삼성전자", 14.7, 22, 112),
    ("동학개미 정점 2021.6", "SK하이닉스", 22.5, 33.7, 112),
    ("현재 2026.5", "NVDA", us_cap["NVDA"]/(us_q_net["NVDA"]*4), us_cap["NVDA"]/us_ttm_net["NVDA"], None),
    ("현재 2026.5", "TSM", us_cap["TSM"]/(us_q_net["TSM"]*4), us_cap["TSM"]/us_ttm_net["TSM"], None),
    ("현재 2026.5", "삼성전자", 21.5, 37.4, 258),
    ("현재 2026.5", "SK하이닉스", 22.8, 33.6, 258),
]
for row in rows:
    label, ticker, fwd, ttm, gdpr = row
    fwd_s = f"{fwd:.1f}"
    ttm_s = f"{ttm:.0f}" if ttm else "-"
    gdp_s = f"{gdpr}%" if gdpr else "-"
    print(f"{label:<25s} {ticker:<20s} {fwd_s:>12s} {ttm_s:>10s} {gdp_s:>10s}")
