"""앞 분석의 후속 — 4종 vs 나머지 누적 수익률 분해.

차이(t) = base_KOSPI × w_4_base × (r_4(t) - r_ex(t))
- w_4_base : 2025-10-01 시점 4종 시총 비중
- r_4(t)   : 4종 합산 시총 누적 배수 (base → t)
- r_ex(t)  : 나머지 합산 시총 누적 배수 (base → t)

비중이 32% → 60% 로 커진 것 자체가 r_4 ≫ r_ex 의 결과.
갭이 -200 → -4000 으로 커진 것도 같은 (r_4 - r_ex) 가 점점 벌어진 결과.
"""
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

EXCLUDE = ["000660", "005930", "402340", "009150"]
START, END = "2025-10-01", "2026-06-30"
CACHE_DIR = Path("data/cache/kr")

snap = pd.read_parquet(CACHE_DIR / "_live_snapshot.parquet")
snap = snap[snap["marketValue"].notna() & (snap["closePrice"] > 0)].copy()
snap["shares"] = snap["marketValue"] / snap["closePrice"]
shares = snap.set_index("itemCode")["shares"]

closes = {}
for p in CACHE_DIR.glob("*.parquet"):
    if p.stem.startswith("_") or p.stem not in shares.index:
        continue
    df = pd.read_parquet(p)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = df[(df.index >= START) & (df.index <= END)]
    if not df.empty:
        closes[p.stem] = df["Close"]

closes_df = pd.DataFrame(closes).sort_index()
mcap = closes_df.mul(shares.reindex(closes_df.columns), axis=1)

total_4 = mcap[EXCLUDE].sum(axis=1)
total_ex = mcap.drop(columns=EXCLUDE).sum(axis=1)
total_all = total_4 + total_ex

base = total_all.index[0]
T0_all, T0_4, T0_ex = total_all.loc[base], total_4.loc[base], total_ex.loc[base]
w4_base = T0_4 / T0_all
BASE_KOSPI = 3455.83

print(f"[base 2025-10-01]")
print(f"  4종 시총 비중 w_4_base = {w4_base*100:.2f}%")
print(f"  나머지 비중            = {(1-w4_base)*100:.2f}%")
print()

# 월말이 거래일이 아닐 수 있으니 각 달의 마지막 거래일로 매핑
month_end_idx = total_all.groupby(total_all.index.to_period("M")).apply(lambda s: s.index[-1])
rows = []
for period, d in month_end_idx.items():
    r4 = total_4.loc[d] / T0_4
    rex = total_ex.loc[d] / T0_ex
    rall = total_all.loc[d] / T0_all
    gap_pct = (r4 - rex) * 100
    diff_pt = BASE_KOSPI * w4_base * (r4 - rex)
    weight_now = total_4.loc[d] / total_all.loc[d] * 100
    rows.append({
        "월": str(period),
        "r_4(누적%)": round((r4 - 1) * 100, 1),
        "r_ex(누적%)": round((rex - 1) * 100, 1),
        "r_all(누적%)": round((rall - 1) * 100, 1),
        "r_4 - r_ex(%p)": round(gap_pct, 1),
        "→ 차이(pt)": round(-diff_pt, 0),  # 부호: ex-4가 실제보다 낮으므로 음수
        "4종 비중(현재)": round(weight_now, 1),
    })

df = pd.DataFrame(rows)
print(df.to_string(index=False))

print()
print("[해석]")
print("- 차이(pt) = 3455.83 × 32.3% × (r_4 - r_ex)")
print("- 즉 차이는 '베이스시점 비중' × '누적수익률 격차' 에 비례.")
print("- 4종 비중이 32% → 60% 로 커진 것은 결과지 원인이 아니다.")
print("  같은 원인(r_4 ≫ r_ex)이 차이도 키우고 비중도 키운 것.")
