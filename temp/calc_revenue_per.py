"""매출 기준 분석 — P/S (Price/Sales) + 매출 성장 + AI 동급주 비교.

PER은 마진 변동에 휘둘리고 회계 조정 영향 큼.
P/S는 매출 절대 규모만 보니까 사이클 산업 평가에 더 직관적.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = Path(__file__).parent
sam = pd.read_csv(OUT_DIR / "samsung_quarterly.csv", encoding="utf-8-sig")
hyn = pd.read_csv(OUT_DIR / "hynix_quarterly.csv", encoding="utf-8-sig")

# 분기 매출 시계열 — 사이클 한눈에
print("=" * 90)
print("[A] 삼성전자 분기 매출 (조원)")
print("=" * 90)
sam_view = sam.set_index("report_period")[["revenue_eok", "op_profit_eok"]].copy()
sam_view["매출_조"] = (sam_view["revenue_eok"] / 10000).round(1)
sam_view["영업이익_조"] = (sam_view["op_profit_eok"] / 10000).round(1)
sam_view["영업이익률_%"] = (sam_view["op_profit_eok"] / sam_view["revenue_eok"] * 100).round(1)
sam_view["YoY매출_%"] = (sam_view["revenue_eok"].pct_change(4) * 100).round(1)
print(sam_view[["매출_조","영업이익_조","영업이익률_%","YoY매출_%"]].tail(12).to_string())

print()
print("=" * 90)
print("[B] SK하이닉스 분기 매출 (조원)")
print("=" * 90)
hyn_view = hyn.set_index("report_period")[["revenue_eok", "op_profit_eok"]].copy()
hyn_view["매출_조"] = (hyn_view["revenue_eok"] / 10000).round(1)
hyn_view["영업이익_조"] = (hyn_view["op_profit_eok"] / 10000).round(1)
hyn_view["영업이익률_%"] = (hyn_view["op_profit_eok"] / hyn_view["revenue_eok"] * 100).round(1)
hyn_view["YoY매출_%"] = (hyn_view["revenue_eok"].pct_change(4) * 100).round(1)
print(hyn_view[["매출_조","영업이익_조","영업이익률_%","YoY매출_%"]].tail(12).to_string())

# P/S 계산
# 현재 시총 (위에서 계산)
SAM_CAP = 1691.0  # 조원
HYN_CAP = 1446.0
# 연환산 매출 (Q4 ×4)
sam_q4 = sam.iloc[-1]
hyn_q4 = hyn.iloc[-1]
sam_rev_fwd = sam_q4["revenue_eok"] * 4 / 10000  # 조원
hyn_rev_fwd = hyn_q4["revenue_eok"] * 4 / 10000

# TTM 매출
sam_rev_ttm = sam["revenue_eok"].iloc[-4:].sum() / 10000
hyn_rev_ttm = hyn["revenue_eok"].iloc[-4:].sum() / 10000

print()
print("=" * 90)
print("[C] 한국 메모리주 — P/S (시총/매출)")
print("=" * 90)
print(f"  삼성전자:  시총 {SAM_CAP:.0f}조 / TTM 매출 {sam_rev_ttm:.0f}조 = P/S {SAM_CAP/sam_rev_ttm:.2f}")
print(f"  삼성전자:  시총 {SAM_CAP:.0f}조 / Fwd 매출 {sam_rev_fwd:.0f}조 = P/S {SAM_CAP/sam_rev_fwd:.2f}")
print()
print(f"  SK하이닉스: 시총 {HYN_CAP:.0f}조 / TTM 매출 {hyn_rev_ttm:.0f}조 = P/S {HYN_CAP/hyn_rev_ttm:.2f}")
print(f"  SK하이닉스: 시총 {HYN_CAP:.0f}조 / Fwd 매출 {hyn_rev_fwd:.0f}조 = P/S {HYN_CAP/hyn_rev_fwd:.2f}")

# === 글로벌 비교 ===
print()
print("=" * 100)
print("[D] 글로벌 AI 종목 P/S — 매출 기준 비교")
print("=" * 100)
# 환율 가정 1,400원/USD
KRW_USD = 1400
# 시총 + 연환산 매출 (분기 ×4)
items = [
    # (name, 시총_조원, 연환산매출_조원, 영업이익률, YoY매출%)
    ("삼성전자",     SAM_CAP,  sam_rev_fwd, sam_q4["op_profit_eok"]/sam_q4["revenue_eok"]*100,
     (sam_q4["revenue_eok"] / sam[sam["report_period"]=="2024Q4"]["revenue_eok"].iloc[0] - 1)*100),
    ("SK하이닉스",   HYN_CAP,  hyn_rev_fwd, hyn_q4["op_profit_eok"]/hyn_q4["revenue_eok"]*100,
     (hyn_q4["revenue_eok"] / hyn[hyn["report_period"]=="2024Q4"]["revenue_eok"].iloc[0] - 1)*100),
    # 글로벌 (USD → 조원 환산)
    # NVDA FY26 Q4 매출 $45B → 연환산 $180B = 252조
    ("NVDA",        5409*KRW_USD/1e4, 45*4*KRW_USD/1e4, 60, 78),
    ("TSM",         2062*KRW_USD/1e4, 25*4*KRW_USD/1e4, 47, 32),
    ("AVGO",        1971*KRW_USD/1e4, 15*4*KRW_USD/1e4, 35, 25),
    ("AMD",         726*KRW_USD/1e4,  9*4*KRW_USD/1e4,  10, 35),
    ("INTC",        515*KRW_USD/1e4,  15*4*KRW_USD/1e4, 8, 4),
]
print(f"{'종목':<12s} {'시총(조)':>10s} {'연환산매출(조)':>14s} {'P/S':>8s} {'영업이익률':>10s} {'YoY매출':>10s}")
print("-" * 80)
for name, cap, rev, op_m, yoy in items:
    ps = cap / rev
    print(f"{name:<12s} {cap:>10.0f} {rev:>14.0f} {ps:>8.1f} {op_m:>9.0f}% {yoy:>9.0f}%")

# === 닷컴 비교 ===
print()
print("=" * 90)
print("[E] 닷컴버블 정점 P/S — 매출 기준 비교 (2000.3.10)")
print("=" * 90)
print("  (출처: 시카고 CRSP DB + 회계연도 자료)")
# (name, 시총_$B, 연환산매출_$B)
dotcom = [
    ("Cisco",          550, 16.0),    # FY00 매출 $19B → 절반 시점 ~$16
    ("MSFT",           620, 23.0),    # FY00 매출 $23B
    ("Intel",          500, 34.0),    # 2000 매출 $34B
    ("Oracle",         290, 10.0),
    ("Sun Microsystems", 220, 16.0),
    ("Yahoo",           93, 1.0),
    ("Amazon",          90, 2.8),
]
print(f"{'종목':<22s} {'시총($B)':>10s} {'매출($B)':>10s} {'P/S':>8s}")
print("-" * 55)
for name, cap, rev in dotcom:
    ps = cap / rev
    print(f"{name:<22s} {cap:>10.0f} {rev:>10.1f} {ps:>8.1f}")

# === 매출 성장 시나리오 ===
print()
print("=" * 90)
print("[F] 매출 기준 추가 상승 여지 — 시나리오")
print("=" * 90)

# 메모리주 적정 P/S 가정 (호황기): 2~3 (마진 좋을 때)
# 또는 글로벌 동급 P/S 기준
print("\n[가정 1] 매출 그대로, P/S가 글로벌 동급 수준으로 재평가:")
print(f"  - TSM P/S {2062*KRW_USD/1e4/(25*4*KRW_USD/1e4):.1f} 적용 시:")
sam_tsm = sam_rev_fwd * (2062*KRW_USD/1e4/(25*4*KRW_USD/1e4))
hyn_tsm = hyn_rev_fwd * (2062*KRW_USD/1e4/(25*4*KRW_USD/1e4))
print(f"    삼성 시총 → {sam_tsm:.0f}조 (현재 {SAM_CAP}조의 {sam_tsm/SAM_CAP:.1f}배)")
print(f"    하닉 시총 → {hyn_tsm:.0f}조 (현재 {HYN_CAP}조의 {hyn_tsm/HYN_CAP:.1f}배)")

print(f"\n  - NVDA P/S {5409*KRW_USD/1e4/(45*4*KRW_USD/1e4):.1f} 의 절반(15) 적용 시:")
sam_nvda_half = sam_rev_fwd * 15
hyn_nvda_half = hyn_rev_fwd * 15
print(f"    삼성 시총 → {sam_nvda_half:.0f}조 (현재의 {sam_nvda_half/SAM_CAP:.1f}배)")
print(f"    하닉 시총 → {hyn_nvda_half:.0f}조 (현재의 {hyn_nvda_half/HYN_CAP:.1f}배)")

print(f"\n[가정 2] 현재 P/S 유지 + 매출 2배 (HBM3E/4 본격 출하):")
sam_2x = SAM_CAP * 2
hyn_2x = HYN_CAP * 2
print(f"    삼성 시총 → {sam_2x:.0f}조 (현재의 2배)")
print(f"    하닉 시총 → {hyn_2x:.0f}조 (현재의 2배)")

print(f"\n[가정 3] 매출 +50% + P/S 동급 (NVDA 절반 15) — 합성:")
sam_combo = sam_rev_fwd * 1.5 * 15
hyn_combo = hyn_rev_fwd * 1.5 * 15
print(f"    삼성 시총 → {sam_combo:.0f}조 (현재의 {sam_combo/SAM_CAP:.1f}배)")
print(f"    하닉 시총 → {hyn_combo:.0f}조 (현재의 {hyn_combo/HYN_CAP:.1f}배)")
