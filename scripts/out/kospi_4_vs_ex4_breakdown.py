"""4종 시총 vs ex-4 시총: 일별 trajectory + 피크/현재/드로우다운."""
import sys
from pathlib import Path
import pandas as pd

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

total_4 = mcap[EXCLUDE].sum(axis=1) / 1e12  # 조 KRW
total_ex = mcap.drop(columns=EXCLUDE).sum(axis=1) / 1e12

print("=" * 70)
print("4종 시총 (조 KRW)")
print("=" * 70)
peak_4 = total_4.max()
peak_4_date = total_4.idxmax()
cur_4 = total_4.iloc[-1]
cur_4_date = total_4.index[-1]
print(f"  피크: {peak_4_date.strftime('%Y-%m-%d')}  {peak_4:.0f}조")
print(f"  현재: {cur_4_date.strftime('%Y-%m-%d')}  {cur_4:.0f}조")
print(f"  피크 대비: {(cur_4/peak_4 - 1)*100:+.1f}%")
print(f"  연초 대비: {(cur_4/total_4.iloc[0] - 1)*100:+.1f}%")

print()
print("=" * 70)
print("ex-4 시총 (조 KRW) — 942 종목")
print("=" * 70)
peak_ex = total_ex.max()
peak_ex_date = total_ex.idxmax()
cur_ex = total_ex.iloc[-1]
cur_ex_date = total_ex.index[-1]
print(f"  피크: {peak_ex_date.strftime('%Y-%m-%d')}  {peak_ex:.0f}조")
print(f"  현재: {cur_ex_date.strftime('%Y-%m-%d')}  {cur_ex:.0f}조")
print(f"  피크 대비: {(cur_ex/peak_ex - 1)*100:+.1f}%")
print(f"  연초 대비: {(cur_ex/total_ex.iloc[0] - 1)*100:+.1f}%")

print()
print("=" * 70)
print("최근 60거래일 — 5일 이동평균 시총 trajectory")
print("=" * 70)
ma5_4 = total_4.rolling(5).mean()
ma5_ex = total_ex.rolling(5).mean()
recent = pd.DataFrame({
    "4종 5dMA": ma5_4.tail(60).round(0).astype(int),
    "ex-4 5dMA": ma5_ex.tail(60).round(0).astype(int),
})
# 매 5일마다 샘플링
sampled = recent.iloc[::5]
print(sampled.to_string())

print()
print("=" * 70)
print("개별 4종 — 1월 이후 누적 수익률 + 피크 대비")
print("=" * 70)
for code in EXCLUDE:
    s = closes_df[code]
    base = s.iloc[0]
    cur = s.iloc[-1]
    peak = s.max()
    peak_d = s.idxmax()
    print(f"  {code} {NAMES[code]}:")
    print(f"    연초 대비: {(cur/base - 1)*100:+.1f}%")
    print(f"    피크({peak_d.strftime('%m-%d')}) 대비: {(cur/peak - 1)*100:+.1f}%")
