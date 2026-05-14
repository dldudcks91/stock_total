"""540주 전체 데이터 마크다운 표 출력."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

df = pd.read_parquet(Path(__file__).parent / "kospi_10yr_weekly.parquet")
df["year"] = df.index.year

# 컬럼 이름 짧게
view = pd.DataFrame({
    "주말": df.index.strftime("%Y-%m-%d"),
    "KOSPI": df["KOSPI_close"].round(0).astype(int),
    "시총(조)": df["KOSPI_marcap_조"].round(0).astype(int),
    "외인(억)": df["외인_주간_순매수_억"].round(0).astype("Int64"),
    "개인(억)": df["개인_주간_순매수_억"].round(0).astype("Int64"),
    "기관(억)": df["기관_주간_순매수_억"].round(0).astype("Int64"),
    "금융투자(억)": df["금융투자_주간_순매수_억"].round(0).astype("Int64"),
    "외인누적(조)": df["외인_누적_조"].round(1),
    "삼성외인%": df["삼성전자_외인비중_%"].round(2),
    "year": df["year"],
})

for year, g in view.groupby("year"):
    print(f"\n## {year}년 ({len(g)}주)")
    print()
    print("| 주말 | KOSPI | 시총(조) | 외인(억) | 개인(억) | 기관(억) | 금융투자(억) | 외인누적(조) | 삼성외인% |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in g.iterrows():
        fx = "" if pd.isna(r["외인(억)"]) else f"{int(r['외인(억)']):+,}"
        ind = "" if pd.isna(r["개인(억)"]) else f"{int(r['개인(억)']):+,}"
        inst = "" if pd.isna(r["기관(억)"]) else f"{int(r['기관(억)']):+,}"
        fin = "" if pd.isna(r["금융투자(억)"]) else f"{int(r['금융투자(억)']):+,}"
        cum = "" if pd.isna(r["외인누적(조)"]) else f"{r['외인누적(조)']:+.1f}"
        ratio = "" if pd.isna(r["삼성외인%"]) else f"{r['삼성외인%']:.2f}"
        print(f"| {r['주말']} | {int(r['KOSPI']):,} | {int(r['시총(조)']):,} | {fx} | {ind} | {inst} | {fin} | {cum} | {ratio} |")
