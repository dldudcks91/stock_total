"""삼성전자 + SK하이닉스 분기 실적 → TTM PER 시계열 계산.

PER = 시가총액 / 트레일링 4분기 순이익 (TTM)

데이터:
- 분기 순이익: temp/samsung_quarterly.csv / hynix_quarterly.csv (CFS, 억원)
- 시가총액: 네이버 종목 페이지 일별 시계열 (이미 받음? 없으면 FDR 종가 × 발행주식수)

분기 실적 발표 시점 (대략):
- Q1 실적: 5월 중순 발표 → 이후 적용
- Q2 실적: 8월 중순 발표
- Q3 실적: 11월 중순 발표
- Q4 실적: 2월 말 ~ 3월 말 발표

따라서 t 시점에 알 수 있는 TTM 순이익은 보통 t-2~3개월 이전 분기까지.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = Path(__file__).parent

# ===== 분기 실적 로드 =====
sam = pd.read_csv(OUT_DIR / "samsung_quarterly.csv", encoding="utf-8-sig")
hyn = pd.read_csv(OUT_DIR / "hynix_quarterly.csv", encoding="utf-8-sig")

# 분기 종료일 (대략적 발표일 = 분기 종료 + 45일 가정)
def quarter_release_date(year, q):
    """분기 실적 발표일 추정: Q1=5/15, Q2=8/15, Q3=11/15, Q4=다음해 3/15"""
    if q == 1: return pd.Timestamp(year, 5, 15)
    if q == 2: return pd.Timestamp(year, 8, 15)
    if q == 3: return pd.Timestamp(year, 11, 15)
    return pd.Timestamp(year + 1, 3, 15)

for df in [sam, hyn]:
    df["release_date"] = df.apply(lambda r: quarter_release_date(r["year"], r["quarter"]), axis=1)
    df.sort_values("release_date", inplace=True)
    # TTM (트레일링 4분기 합)
    df["ttm_net_profit_eok"] = df["net_profit_eok"].rolling(4).sum()
    df["ttm_op_profit_eok"] = df["op_profit_eok"].rolling(4).sum()
    df["ttm_revenue_eok"] = df["revenue_eok"].rolling(4).sum()

print("=" * 80)
print("[A] 삼성전자 TTM 순이익 시계열 (실적 발표일 기준)")
print("=" * 80)
sam_view = sam[["release_date", "report_period", "revenue_eok", "op_profit_eok",
                "net_profit_eok", "ttm_net_profit_eok"]].copy()
sam_view["TTM순이익_조"] = (sam_view["ttm_net_profit_eok"] / 10000).round(1)
sam_view["분기영업이익_조"] = (sam_view["op_profit_eok"] / 10000).round(2)
sam_view["분기순이익_조"] = (sam_view["net_profit_eok"] / 10000).round(2)
print(sam_view[["release_date", "report_period", "분기영업이익_조", "분기순이익_조", "TTM순이익_조"]].tail(12).to_string(index=False))

print()
print("=" * 80)
print("[B] SK하이닉스 TTM 순이익 시계열")
print("=" * 80)
hyn_view = hyn[["release_date", "report_period", "revenue_eok", "op_profit_eok",
                "net_profit_eok", "ttm_net_profit_eok"]].copy()
hyn_view["TTM순이익_조"] = (hyn_view["ttm_net_profit_eok"] / 10000).round(1)
hyn_view["분기영업이익_조"] = (hyn_view["op_profit_eok"] / 10000).round(2)
hyn_view["분기순이익_조"] = (hyn_view["net_profit_eok"] / 10000).round(2)
print(hyn_view[["release_date", "report_period", "분기영업이익_조", "분기순이익_조", "TTM순이익_조"]].tail(12).to_string(index=False))

# ===== 시가총액 - FDR로 일별 시계열 직접 계산 =====
# 종가 × 발행주식수 (액면분할 조정)
import FinanceDataReader as fdr

# 발행주식수 (액분 조정 후 — FDR 종가도 액분 조정됨)
# 삼성전자: 2018.5.4 액분 50:1, 자사주 매입소각 후 현재 보통주 약 5.97B
# 액분 조정 시계열 가정: 6,419,324,700 (액분 직후) → 5,969,782,550 (현재)
SAM_SHARES_NOW = 5_969_782_550
HYN_SHARES_NOW = 728_002_365  # SK하이닉스 현재

sam_close = fdr.DataReader("005930", "2016-01-01", "2026-05-13")["Close"]
hyn_close = fdr.DataReader("000660", "2016-01-01", "2026-05-13")["Close"]
# 시총 추정 (현재 발행주식수 기준 — 자사주 변동 무시)
sam_cap_series = sam_close * SAM_SHARES_NOW / 1e12  # 조
hyn_cap_series = hyn_close * HYN_SHARES_NOW / 1e12

sam_cap = float(sam_cap_series.iloc[-1])
hyn_cap = float(hyn_cap_series.iloc[-1])
print()
print(f"삼성전자 현재 종가 {sam_close.iloc[-1]:,.0f}원 × 발행주식수 {SAM_SHARES_NOW:,} = 시총 {sam_cap:.1f}조")
print(f"SK하이닉스 현재 종가 {hyn_close.iloc[-1]:,.0f}원 × 발행주식수 {HYN_SHARES_NOW:,} = 시총 {hyn_cap:.1f}조")

# ===== 현재 PER =====
sam_ttm_net = sam["ttm_net_profit_eok"].iloc[-1] / 10000  # 조
hyn_ttm_net = hyn["ttm_net_profit_eok"].iloc[-1] / 10000

print()
print("=" * 80)
print("[C] 현재 PER (시가총액 / 트레일링 4분기 순이익)")
print("=" * 80)
print(f"  삼성전자:  시총 {sam_cap:.0f}조 / TTM 순이익 {sam_ttm_net:.1f}조 = PER {sam_cap/sam_ttm_net:.1f}")
print(f"  SK하이닉스: 시총 {hyn_cap:.0f}조 / TTM 순이익 {hyn_ttm_net:.1f}조 = PER {hyn_cap/hyn_ttm_net:.1f}")

# ===== PER 시계열: 시총 / TTM 순이익 =====
# TTM 순이익을 각 release_date 부터 다음 release_date 전까지 forward-fill
def build_ttm_series(df_q, all_dates):
    s = pd.Series(index=all_dates, dtype=float)
    df_q = df_q.dropna(subset=["ttm_net_profit_eok"]).sort_values("release_date")
    for _, row in df_q.iterrows():
        d = row["release_date"]
        ttm = row["ttm_net_profit_eok"] / 10000  # 조
        s.loc[s.index >= d] = ttm
    return s

sam_ttm = build_ttm_series(sam, sam_close.index)
hyn_ttm = build_ttm_series(hyn, hyn_close.index)

sam_per = sam_cap_series / sam_ttm
hyn_per = hyn_cap_series / hyn_ttm

# 시점별 비교
markers = {
    "2016-12-30 (10년 전)": "2016-12-30",
    "2018-01-29 (2017 슈퍼사이클 정점 직후)": "2018-01-29",
    "2018-11-30 (메모리 하락 시작)": "2018-11-30",
    "2020-03-23 (코로나 저점)": "2020-03-23",
    "2021-01-11 (동학개미 정점 삼성 9.6만)": "2021-01-11",
    "2023-01-02 (메모리 저점)": "2023-01-02",
    "2024-07-11 (AI 1차 정점)": "2024-07-11",
    "2025-04-04 (저점)": "2025-04-04",
    "2026-05-13 (현재)": "2026-05-13",
}

print()
print("=" * 110)
print("[D] 삼성전자 + SK하이닉스 시계열 PER")
print(f"가정: 발행주식수 일정 (삼성 {SAM_SHARES_NOW/1e9:.1f}B, 하이닉스 {HYN_SHARES_NOW/1e6:.0f}M). 액분·자사주 효과는 ±5% 수준.")
print("=" * 110)
print(f"{'시점':<40s} {'삼성주가':>10s} {'삼성시총':>10s} {'삼성TTM':>10s} {'삼성PER':>10s} {'하닉주가':>10s} {'하닉시총':>10s} {'하닉TTM':>10s} {'하닉PER':>10s}")
print("-" * 110)
for label, d in markers.items():
    target = pd.to_datetime(d)
    # nearest
    idx = sam_close.index[sam_close.index.get_indexer([target], method="nearest")[0]]
    sp = sam_close.loc[idx]
    sc = sam_cap_series.loc[idx]
    st = sam_ttm.loc[idx]
    spe = sam_per.loc[idx]
    hp = hyn_close.loc[idx]
    hc = hyn_cap_series.loc[idx]
    ht = hyn_ttm.loc[idx]
    hpe = hyn_per.loc[idx]
    sp_s = f"{sp:,.0f}원"
    hp_s = f"{hp:,.0f}원"
    sc_s = f"{sc:.0f}조"
    hc_s = f"{hc:.0f}조"
    st_s = f"{st:.1f}조" if pd.notna(st) else "-"
    ht_s = f"{ht:.1f}조" if pd.notna(ht) else "-"
    spe_s = f"{spe:.1f}" if pd.notna(spe) and spe > 0 else "n/a"
    hpe_s = f"{hpe:.1f}" if pd.notna(hpe) and hpe > 0 else "n/a"
    print(f"{label:<40s} {sp_s:>10s} {sc_s:>10s} {st_s:>10s} {spe_s:>10s} {hp_s:>10s} {hc_s:>10s} {ht_s:>10s} {hpe_s:>10s}")

# 저장
out = pd.DataFrame({
    "삼성주가": sam_close,
    "삼성시총_조": sam_cap_series,
    "삼성TTM순이익_조": sam_ttm,
    "삼성PER": sam_per,
    "하이닉스주가": hyn_close,
    "하이닉스시총_조": hyn_cap_series,
    "하이닉스TTM순이익_조": hyn_ttm,
    "하이닉스PER": hyn_per,
})
out.to_parquet(OUT_DIR / "per_timeseries.parquet")
out.to_csv(OUT_DIR / "per_timeseries.csv", encoding="utf-8-sig")
print()
print(f"saved: {OUT_DIR / 'per_timeseries.parquet'}")

# ===== 결정적 분석: PER 추세 + 시총 증가 vs 이익 증가 =====
print()
print("=" * 90)
print("[E] 이번 사이클 (2025.4 → 2026.5) — 시총 증가 vs 이익 증가")
print("=" * 90)
t0 = pd.to_datetime("2025-04-04")
t1 = pd.to_datetime("2026-05-13")
for name, cap_s, ttm_s in [("삼성전자", sam_cap_series, sam_ttm), ("SK하이닉스", hyn_cap_series, hyn_ttm)]:
    idx0 = cap_s.index[cap_s.index.get_indexer([t0], method="nearest")[0]]
    idx1 = cap_s.index[cap_s.index.get_indexer([t1], method="nearest")[0]]
    cap_chg = cap_s.loc[idx1] / cap_s.loc[idx0]
    ttm_chg = ttm_s.loc[idx1] / ttm_s.loc[idx0] if pd.notna(ttm_s.loc[idx0]) and ttm_s.loc[idx0] > 0 else None
    print(f"\n  {name}:")
    print(f"    시총   : {cap_s.loc[idx0]:.0f}조 → {cap_s.loc[idx1]:.0f}조  (×{cap_chg:.2f})")
    if ttm_chg is not None:
        print(f"    TTM이익: {ttm_s.loc[idx0]:.1f}조 → {ttm_s.loc[idx1]:.1f}조  (×{ttm_chg:.2f})")
        print(f"    PER 변화: {cap_s.loc[idx0]/ttm_s.loc[idx0]:.1f} → {cap_s.loc[idx1]/ttm_s.loc[idx1]:.1f}  (멀티플 ×{(cap_chg/ttm_chg):.2f})")
    else:
        print(f"    TTM이익: {ttm_s.loc[idx0]} → {ttm_s.loc[idx1]:.1f}조  (이전 적자)")
