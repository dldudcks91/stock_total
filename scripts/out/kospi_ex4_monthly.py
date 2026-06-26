"""KOSPI 월별 지수 재계산 — SK하이닉스/삼성전자/SK스퀘어/삼성전기 제외.

방법:
1. data/cache/kr/_live_snapshot.parquet 의 marketValue/closePrice 로 implied_shares 계산.
2. data/cache/kr/{code}.parquet 일별 Close × implied_shares = 일별 시총.
3. (a) 전체 합산 vs (b) 4종 제외 합산.
4. 2025-10-01 첫 거래일 기준 실제 KOSPI(KS11) 값으로 rebase.
5. 월말 종가 비교.

주의: 현재 implied_shares 를 8개월 내내 일정하다고 가정 (분할/증자 없을 때만 정확).
대상 4종은 모두 안정적 상장사라 근사 OK.
"""
import sys
from pathlib import Path

import pandas as pd
import FinanceDataReader as fdr

sys.stdout.reconfigure(encoding="utf-8")

EXCLUDE = {
    "000660": "SK하이닉스",
    "005930": "삼성전자",
    "402340": "SK스퀘어",
    "009150": "삼성전기",
}
START = "2025-10-01"
END = "2026-06-30"

CACHE_DIR = Path("data/cache/kr")

# 1) implied_shares
snap = pd.read_parquet(CACHE_DIR / "_live_snapshot.parquet")
snap = snap[snap["marketValue"].notna() & (snap["closePrice"] > 0)].copy()
snap["shares"] = snap["marketValue"] / snap["closePrice"]
shares = snap.set_index("itemCode")["shares"]

# 2) load all daily closes — restrict to KR daily cache universe
codes = sorted([p.stem for p in CACHE_DIR.glob("*.parquet") if not p.stem.startswith("_")])

closes = {}
for code in codes:
    if code not in shares.index:
        continue
    df = pd.read_parquet(CACHE_DIR / f"{code}.parquet")
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = df[(df.index >= START) & (df.index <= END)]
    if df.empty or "Close" not in df.columns:
        continue
    closes[code] = df["Close"]

closes_df = pd.DataFrame(closes).sort_index()
print(f"[info] universe: {len(closes_df.columns)} stocks, {len(closes_df)} trading days")

# 3) market cap matrix (close × shares)
share_vec = shares.reindex(closes_df.columns)
mcap_df = closes_df.mul(share_vec, axis=1)

# 4) total_all vs total_ex4
ex_codes = [c for c in EXCLUDE if c in mcap_df.columns]
print(f"[info] excluding: {ex_codes}")
total_all = mcap_df.sum(axis=1, skipna=True)
total_ex = mcap_df.drop(columns=ex_codes).sum(axis=1, skipna=True)

# 5) actual KOSPI for rebase
kospi = fdr.DataReader("KS11", START, END)
kospi.index = pd.to_datetime(kospi.index).tz_localize(None)

# Align: pick first date that exists in all three series
common = total_ex.index.intersection(kospi.index)
base_date = common[0]
base_kospi = kospi.loc[base_date, "Close"]
print(f"[info] base date {base_date.date()}: actual KOSPI = {base_kospi:.2f}")

idx_all = total_all / total_all.loc[base_date] * base_kospi
idx_ex = total_ex / total_ex.loc[base_date] * base_kospi

# 6) monthly resample — month-end last
monthly_actual = kospi["Close"].resample("ME").last()
monthly_all = idx_all.resample("ME").last()
monthly_ex = idx_ex.resample("ME").last()

# 7) format table
table = pd.DataFrame({
    "월": [d.strftime("%Y-%m") for d in monthly_actual.index],
    "실제 KOSPI": monthly_actual.values.round(2),
    "재구성 전체": monthly_all.reindex(monthly_actual.index).values.round(2),
    "재구성 4종제외": monthly_ex.reindex(monthly_actual.index).values.round(2),
})
table["오차(재구성-실제)"] = (table["재구성 전체"] - table["실제 KOSPI"]).round(2)
table["차이(4종제외-실제)"] = (table["재구성 4종제외"] - table["실제 KOSPI"]).round(2)
table["차이(%)"] = ((table["재구성 4종제외"] / table["실제 KOSPI"] - 1) * 100).round(2)

print()
print(table.to_string(index=False))

# Also show: contribution of 4 stocks to total mcap on each month-end
print()
print("[참고] 4종 합산 시총 비중 (월말 기준)")
weight = (mcap_df[ex_codes].sum(axis=1) / total_all).resample("ME").last() * 100
for d, w in weight.items():
    print(f"  {d.strftime('%Y-%m')}: {w:.2f}%")
