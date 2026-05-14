"""Forward PER — 이번 분기 ×4 연환산 기준.

Trailing PER (TTM) 은 과거 4분기 합으로 늦은 신호.
Forward PER = 시총 / (최근 분기 순이익 × 4) 로 현재 실력을 더 잘 반영.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = Path(__file__).parent
sam = pd.read_csv(OUT_DIR / "samsung_quarterly.csv", encoding="utf-8-sig")
hyn = pd.read_csv(OUT_DIR / "hynix_quarterly.csv", encoding="utf-8-sig")

import FinanceDataReader as fdr
SAM_SHARES = 5_969_782_550
HYN_SHARES = 728_002_365
sam_close = fdr.DataReader("005930", "2016-01-01", "2026-05-13")["Close"]
hyn_close = fdr.DataReader("000660", "2016-01-01", "2026-05-13")["Close"]
sam_cap = sam_close * SAM_SHARES / 1e12
hyn_cap = hyn_close * HYN_SHARES / 1e12

# 분기 단독 → ×4 연환산
def quarter_release(year, q):
    if q == 1: return pd.Timestamp(year, 5, 15)
    if q == 2: return pd.Timestamp(year, 8, 15)
    if q == 3: return pd.Timestamp(year, 11, 15)
    return pd.Timestamp(year + 1, 3, 15)

for df in [sam, hyn]:
    df["release_date"] = df.apply(lambda r: quarter_release(r["year"], r["quarter"]), axis=1)
    df.sort_values("release_date", inplace=True)
    df["fwd_op_eok"] = df["op_profit_eok"] * 4   # 연환산 영업이익
    df["fwd_net_eok"] = df["net_profit_eok"] * 4 # 연환산 순이익

# 최근 12분기 view
print("=" * 110)
print("[A] 분기별 Forward 연환산 — 삼성전자")
print("=" * 110)
print(f"{'발표일':<12s} {'분기':<8s} {'분기영업':>10s} {'분기순이익':>10s} {'연환산영업':>10s} {'연환산순이익':>12s}")
for _, r in sam.tail(14).iterrows():
    print(f"{r['release_date'].strftime('%Y-%m-%d'):<12s} {r['report_period']:<8s} {r['op_profit_eok']/10000:>9.2f}조 {r['net_profit_eok']/10000:>9.2f}조 {r['fwd_op_eok']/10000:>9.1f}조 {r['fwd_net_eok']/10000:>11.1f}조")

print()
print("=" * 110)
print("[B] 분기별 Forward 연환산 — SK하이닉스")
print("=" * 110)
print(f"{'발표일':<12s} {'분기':<8s} {'분기영업':>10s} {'분기순이익':>10s} {'연환산영업':>10s} {'연환산순이익':>12s}")
for _, r in hyn.tail(14).iterrows():
    print(f"{r['release_date'].strftime('%Y-%m-%d'):<12s} {r['report_period']:<8s} {r['op_profit_eok']/10000:>9.2f}조 {r['net_profit_eok']/10000:>9.2f}조 {r['fwd_op_eok']/10000:>9.1f}조 {r['fwd_net_eok']/10000:>11.1f}조")

# Forward PER 시계열 (각 release_date 이후 적용)
def build_fwd(df_q, all_dates):
    s = pd.Series(index=all_dates, dtype=float)
    df_q = df_q.sort_values("release_date")
    for _, row in df_q.iterrows():
        d = row["release_date"]
        v = row["fwd_net_eok"] / 10000
        s.loc[s.index >= d] = v
    return s

sam_fwd = build_fwd(sam, sam_close.index)
hyn_fwd = build_fwd(hyn, hyn_close.index)
sam_fwd_per = sam_cap / sam_fwd
hyn_fwd_per = hyn_cap / hyn_fwd

# 시점 비교
markers = {
    "2018-01-29 (슈퍼사이클 정점)": "2018-01-29",
    "2020-03-23 (코로나 저점)": "2020-03-23",
    "2021-01-11 (동학개미 정점)": "2021-01-11",
    "2023-01-02 (메모리 저점)": "2023-01-02",
    "2024-07-11 (AI 1차 정점)": "2024-07-11",
    "2025-04-04 (저점)": "2025-04-04",
    "2026-05-13 (현재)": "2026-05-13",
}

print()
print("=" * 110)
print("[C] Forward PER (시총 / 직전 분기 × 4)")
print("=" * 110)
print(f"{'시점':<32s} {'삼성주가':>10s} {'삼성시총':>10s} {'삼성연환산':>10s} {'삼성fwdPER':>10s} {'하닉주가':>10s} {'하닉시총':>10s} {'하닉연환산':>10s} {'하닉fwdPER':>10s}")
print("-" * 110)
for label, d in markers.items():
    t = pd.to_datetime(d)
    idx = sam_close.index[sam_close.index.get_indexer([t], method="nearest")[0]]
    row = [
        label,
        f"{sam_close.loc[idx]:,.0f}원",
        f"{sam_cap.loc[idx]:.0f}조",
        f"{sam_fwd.loc[idx]:.1f}조" if pd.notna(sam_fwd.loc[idx]) else "-",
        f"{sam_fwd_per.loc[idx]:.1f}" if pd.notna(sam_fwd_per.loc[idx]) and sam_fwd_per.loc[idx] > 0 else "n/a",
        f"{hyn_close.loc[idx]:,.0f}원",
        f"{hyn_cap.loc[idx]:.0f}조",
        f"{hyn_fwd.loc[idx]:.1f}조" if pd.notna(hyn_fwd.loc[idx]) else "-",
        f"{hyn_fwd_per.loc[idx]:.1f}" if pd.notna(hyn_fwd_per.loc[idx]) and hyn_fwd_per.loc[idx] > 0 else "n/a",
    ]
    print(f"{row[0]:<32s} {row[1]:>10s} {row[2]:>10s} {row[3]:>10s} {row[4]:>10s} {row[5]:>10s} {row[6]:>10s} {row[7]:>10s} {row[8]:>10s}")

# === 결정적: 현재 forward PER vs TTM PER 비교 + 시나리오 ===
print()
print("=" * 80)
print("[D] 현재 — TTM PER vs Forward PER 비교")
print("=" * 80)

# 마지막 분기 데이터
sam_q4 = sam.iloc[-1]
hyn_q4 = hyn.iloc[-1]

# TTM
sam_ttm = sam["net_profit_eok"].iloc[-4:].sum() / 10000
hyn_ttm = hyn["net_profit_eok"].iloc[-4:].sum() / 10000
# Forward (Q4 × 4)
sam_fwd_val = sam_q4["fwd_net_eok"] / 10000
hyn_fwd_val = hyn_q4["fwd_net_eok"] / 10000

sam_cap_now = sam_cap.iloc[-1]
hyn_cap_now = hyn_cap.iloc[-1]

print(f"\n  삼성전자 (시총 {sam_cap_now:.0f}조):")
print(f"    TTM 순이익 (2025년 합계): {sam_ttm:.1f}조  →  TTM PER {sam_cap_now/sam_ttm:.1f}")
print(f"    2025Q4 ×4 연환산:        {sam_fwd_val:.1f}조  →  Forward PER {sam_cap_now/sam_fwd_val:.1f}")
print(f"    → 이번 분기 실력 유지하면 PER이 {sam_cap_now/sam_ttm:.1f} → {sam_cap_now/sam_fwd_val:.1f} 로 떨어짐")

print(f"\n  SK하이닉스 (시총 {hyn_cap_now:.0f}조):")
print(f"    TTM 순이익 (2025년 합계): {hyn_ttm:.1f}조  →  TTM PER {hyn_cap_now/hyn_ttm:.1f}")
print(f"    2025Q4 ×4 연환산:        {hyn_fwd_val:.1f}조  →  Forward PER {hyn_cap_now/hyn_fwd_val:.1f}")
print(f"    → 이번 분기 실력 유지하면 PER이 {hyn_cap_now/hyn_ttm:.1f} → {hyn_cap_now/hyn_fwd_val:.1f} 로 떨어짐")

# === 더 공격적: 분기별 성장 가정 ===
print()
print("=" * 80)
print("[E] 시나리오 — HBM 사이클 지속 시")
print("=" * 80)
print("\n[가정 1] 2025Q4 수준이 4분기 유지 (보수적):")
print(f"    삼성 PER {sam_cap_now/sam_fwd_val:.1f}, 하닉 PER {hyn_cap_now/hyn_fwd_val:.1f}")

print("\n[가정 2] 2026 분기 QoQ +15% 성장 (HBM3E 본격 출하):")
# 4분기 합산: Q4 + Q4*1.15 + Q4*1.15^2 + Q4*1.15^3
def compound_sum(base, qoq, n=4):
    return sum(base * (1+qoq)**i for i in range(n))
sam_2026_15 = compound_sum(sam_q4["net_profit_eok"]/10000, 0.15)
hyn_2026_15 = compound_sum(hyn_q4["net_profit_eok"]/10000, 0.15)
print(f"    삼성 2026 예상 순이익 {sam_2026_15:.1f}조 → PER {sam_cap_now/sam_2026_15:.1f}")
print(f"    하닉 2026 예상 순이익 {hyn_2026_15:.1f}조 → PER {hyn_cap_now/hyn_2026_15:.1f}")

print("\n[가정 3] 2026 분기 QoQ +25% 성장 (극강세):")
sam_2026_25 = compound_sum(sam_q4["net_profit_eok"]/10000, 0.25)
hyn_2026_25 = compound_sum(hyn_q4["net_profit_eok"]/10000, 0.25)
print(f"    삼성 2026 예상 순이익 {sam_2026_25:.1f}조 → PER {sam_cap_now/sam_2026_25:.1f}")
print(f"    하닉 2026 예상 순이익 {hyn_2026_25:.1f}조 → PER {hyn_cap_now/hyn_2026_25:.1f}")

print("\n[가정 4] 2026Q1 부터 둔화 (QoQ -10%, 사이클 끝나가는 케이스):")
sam_2026_d = compound_sum(sam_q4["net_profit_eok"]/10000, -0.10)
hyn_2026_d = compound_sum(hyn_q4["net_profit_eok"]/10000, -0.10)
print(f"    삼성 2026 예상 순이익 {sam_2026_d:.1f}조 → PER {sam_cap_now/sam_2026_d:.1f}")
print(f"    하닉 2026 예상 순이익 {hyn_2026_d:.1f}조 → PER {hyn_cap_now/hyn_2026_d:.1f}")
