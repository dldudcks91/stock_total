"""KOSPI 실제 vs ex-4 — 주단위, 2025-05부터.

KOSPI_ex4(t) = KOSPI(t) × (1 - w_4(t))
주말 = 그 주의 마지막 거래일 (보통 금요일).
"""
import sys
from pathlib import Path
import pandas as pd
import FinanceDataReader as fdr

sys.stdout.reconfigure(encoding="utf-8")

EXCLUDE = ["000660", "005930", "402340", "009150"]
START, END = "2025-05-01", "2026-06-30"
CACHE = Path("data/cache/kr")

snap = pd.read_parquet(CACHE / "_live_snapshot.parquet")
snap = snap[snap["marketValue"].notna() & (snap["closePrice"] > 0)].copy()
snap["shares"] = snap["marketValue"] / snap["closePrice"]
shares = snap.set_index("itemCode")["shares"]

closes = {}
for p in CACHE.glob("*.parquet"):
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
total_all = mcap.sum(axis=1)
w4 = total_4 / total_all

kospi = fdr.DataReader("KS11", START, END)
kospi.index = pd.to_datetime(kospi.index).tz_localize(None)
kospi_close = kospi["Close"]

# 각 주의 마지막 거래일
week_end = total_all.groupby([total_all.index.isocalendar().year,
                              total_all.index.isocalendar().week]).apply(lambda s: s.index[-1])

rows = []
for (y, w), d in week_end.items():
    if d not in kospi_close.index:
        candidates = kospi_close.index[kospi_close.index <= d]
        if len(candidates) == 0:
            continue
        d_k = candidates[-1]
    else:
        d_k = d
    k_actual = kospi_close.loc[d_k]
    weight4 = w4.loc[d]
    k_ex4 = k_actual * (1 - weight4)
    rows.append({
        "주말일": d.strftime("%Y-%m-%d"),
        "KOSPI": round(k_actual, 1),
        "ex-4 KOSPI": round(k_ex4, 1),
        "4종 비중": f"{weight4*100:.1f}%",
    })

df = pd.DataFrame(rows)
# 누적 변화 (첫주 기준)
base_kospi = df.iloc[0]["KOSPI"]
base_ex4 = df.iloc[0]["ex-4 KOSPI"]
df["KOSPI 누적%"] = ((df["KOSPI"] / base_kospi - 1) * 100).round(1)
df["ex-4 누적%"] = ((df["ex-4 KOSPI"] / base_ex4 - 1) * 100).round(1)

print(f"기준: {df.iloc[0]['주말일']}  KOSPI {base_kospi:.1f}, ex-4 {base_ex4:.1f}")
print()
print(df.to_string(index=False))

# 추가: 각 그룹의 피크와 현재 위치
print()
print("[요약]")
print(f"KOSPI 피크주: {df.loc[df['KOSPI'].idxmax(), '주말일']}  값 {df['KOSPI'].max():.1f}")
print(f"KOSPI 현재:   {df.iloc[-1]['주말일']}  값 {df.iloc[-1]['KOSPI']:.1f}  피크 대비 {(df.iloc[-1]['KOSPI']/df['KOSPI'].max()-1)*100:+.1f}%")
print(f"ex-4 피크주:  {df.loc[df['ex-4 KOSPI'].idxmax(), '주말일']}  값 {df['ex-4 KOSPI'].max():.1f}")
print(f"ex-4 현재:    {df.iloc[-1]['주말일']}  값 {df.iloc[-1]['ex-4 KOSPI']:.1f}  피크 대비 {(df.iloc[-1]['ex-4 KOSPI']/df['ex-4 KOSPI'].max()-1)*100:+.1f}%")
