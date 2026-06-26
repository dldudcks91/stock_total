"""KOSPI ex-4 — 사용자 정의가 맞는 방식.

KOSPI(t) = T_all(t) / T_base_1980 × 100   (분모 1980 고정)
KOSPI_ex4(t) = (T_all(t) - T_4(t)) / T_base_1980 × 100
             = KOSPI(t) × (1 - w_4(t))

w_4(t) = T_4(t) / T_all(t) = 그 시점 4종 시총 비중
"""
import sys
from pathlib import Path
import pandas as pd
import FinanceDataReader as fdr

sys.stdout.reconfigure(encoding="utf-8")

EXCLUDE = ["000660", "005930", "402340", "009150"]
NAMES = {"000660": "SK하이닉스", "005930": "삼성전자", "402340": "SK스퀘어", "009150": "삼성전기"}
START, END = "2025-01-01", "2026-06-30"
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

# 각 달 마지막 거래일
me_dates = total_all.groupby(total_all.index.to_period("M")).apply(lambda s: s.index[-1])

rows = []
for period, d in me_dates.items():
    if d not in kospi_close.index:
        # 가장 가까운 전일
        d_k = kospi_close.index[kospi_close.index <= d][-1]
    else:
        d_k = d
    k_actual = kospi_close.loc[d_k]
    weight4 = w4.loc[d]
    k_ex4 = k_actual * (1 - weight4)
    rows.append({
        "월": str(period),
        "실제 KOSPI": round(k_actual, 2),
        "4종 비중": f"{weight4*100:.1f}%",
        "KOSPI(4종제외)": round(k_ex4, 2),
        "차이(pt)": round(k_ex4 - k_actual, 1),
        "차이(%)": f"{(k_ex4/k_actual - 1)*100:.1f}%",
    })

df = pd.DataFrame(rows)
print(df.to_string(index=False))

# 검증: 누적 변화
print()
print("[참고] ex-4 지수 자체의 누적 변화율 (2025-10 기준)")
base_ex = rows[0]["KOSPI(4종제외)"]
base_actual = rows[0]["실제 KOSPI"]
for r in rows:
    actual_chg = (r["실제 KOSPI"] / base_actual - 1) * 100
    ex_chg = (r["KOSPI(4종제외)"] / base_ex - 1) * 100
    print(f"  {r['월']}: 실제 {actual_chg:+.1f}%  vs  ex-4 {ex_chg:+.1f}%")
