"""주별 외인 보유 비중 표 + 매매동향과 결합."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = Path(__file__).parent

# 외인 비중
ratio = pd.read_parquet(OUT_DIR / "kospi_foreign_ratio_proxy.parquet")
# 매매동향
flow = pd.read_parquet(OUT_DIR / "kospi_investor_flow.parquet")

# 주별 (금요일 기준) 마지막 값
ratio_weekly = ratio.resample("W-FRI").last().dropna(how="all")
ratio_weekly.index = ratio_weekly.index.strftime("%Y-%m-%d")

flow_weekly = flow[["외국인", "개인", "기관계", "금융투자"]].groupby(pd.Grouper(freq="W-FRI")).sum()
flow_weekly.index = flow_weekly.index.strftime("%Y-%m-%d")

# 결합 (외인 비중 전 기간 보여주되, 매매동향은 11/13부터)
combined = ratio_weekly.copy()
combined["외인_주간_매도(억)"] = flow_weekly["외국인"]
combined["금융투자_주간_매수(억)"] = flow_weekly["금융투자"]

# 누적 변화
combined["가중평균_시작대비_변화(%p)"] = (combined["가중평균_외인비중_%"] - combined["가중평균_외인비중_%"].iloc[0]).round(2)

print("=" * 110)
print("[주별] 외인 보유 비중 (시총 상위 5종목 가중평균) + 외인 주간 매도 + 금융투자 주간 매수")
print(f"가중치: 삼성전자 53.8% / SK하이닉스 26.4% / LG엔솔 8.2% / 삼바 6.6% / 현대차 4.9%")
print("=" * 110)
print(combined.round(2).to_string())
print()

# 종목별 변화
print("=" * 70)
print("[종목별 외인 비중 8개월 변화]")
print("=" * 70)
chg = pd.DataFrame({
    "시작 (25.09.11)": ratio.iloc[0][["삼성전자","SK하이닉스","LG에너지솔루션","삼성바이오","현대차","가중평균_외인비중_%"]],
    "최근 (26.05.12)": ratio.iloc[-1][["삼성전자","SK하이닉스","LG에너지솔루션","삼성바이오","현대차","가중평균_외인비중_%"]],
})
chg["변화(%p)"] = (chg["최근 (26.05.12)"] - chg["시작 (25.09.11)"]).round(2)
print(chg.round(2).to_string())

combined.to_csv(OUT_DIR / "kospi_foreign_ratio_weekly.csv", encoding="utf-8-sig")
print()
print(f"saved: {OUT_DIR / 'kospi_foreign_ratio_weekly.csv'}")
