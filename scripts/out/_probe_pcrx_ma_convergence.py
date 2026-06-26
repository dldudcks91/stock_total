"""PCRX 자체 — MA10/MA20 수렴 자리(공통점) 가 얼마나 드문가 + 직후 가격 흐름."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import numpy as np
import pandas as pd
from pathlib import Path

df = pd.read_parquet("data/cache/us/PCRX.parquet")
df.columns = [c.lower() for c in df.columns]
df = df.sort_index()

def resample(d, rule):
    o = d["open"].resample(rule).first()
    h = d["high"].resample(rule).max()
    l = d["low"].resample(rule).min()
    c = d["close"].resample(rule).last()
    v = d["volume"].resample(rule).sum()
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}).dropna()

frames = {
    "1D": df[["open","high","low","close","volume"]].copy(),
    "1W": resample(df, "W-FRI"),
    "1M": resample(df, "ME"),
}

def analyze(name, d):
    d = d.copy()
    d["ma10"] = d["close"].rolling(10).mean()
    d["ma20"] = d["close"].rolling(20).mean()
    d = d.dropna(subset=["ma10","ma20"])
    # 수렴 정도 = |ma10-ma20| / ma20 (%)
    d["conv_pct"] = (d["ma10"] - d["ma20"]).abs() / d["ma20"] * 100
    # 가격이 MA10 또는 MA20 에 닿았는가 (low <= max(ma10,ma20)+ε)
    d["touched_ma"] = (d["low"] <= d[["ma10","ma20"]].max(axis=1)) & (d["high"] >= d[["ma10","ma20"]].min(axis=1))
    # 전일 가격 vs 전일 MA20
    d["close_vs_ma20"] = d["close"] / d["ma20"] - 1

    today = d.iloc[-1]
    print(f"\n=== {name} 최근 자리 ===")
    print(f"  date         {d.index[-1].date()}")
    print(f"  close        {today['close']:.2f}")
    print(f"  ma10         {today['ma10']:.3f}")
    print(f"  ma20         {today['ma20']:.3f}")
    print(f"  |ma10-ma20|  {abs(today['ma10']-today['ma20']):.3f}")
    print(f"  수렴도(%)    {today['conv_pct']:.3f}  (작을수록 수렴)")

    # 분포: 이 정도 수렴은 얼마나 드문가?
    pct_rank = (d["conv_pct"].rank(pct=True).iloc[-1]) * 100
    print(f"  수렴도 백분위 = {pct_rank:.1f}%  (전체 기간 중 하위 X% — 0=가장 수렴)")

    # 수렴 임계 (전체 중 하위 10%) 자리 표시
    th_conv = d["conv_pct"].quantile(0.10)
    print(f"  하위 10% 수렴 임계 = {th_conv:.3f}%")

    # 수렴 + 가격이 MA 부근 닿은 자리 → 직후 fwd-return
    d["near_ma"] = d["low"] <= d["ma10"] * 1.02  # low가 ma10 +2% 이내
    d["squeeze"] = (d["conv_pct"] <= th_conv) & d["near_ma"]
    sqz = d[d["squeeze"]].copy()
    # 직후 N봉 forward return
    for h in [5, 10, 20]:
        fwd = d["close"].shift(-h) / d["close"] - 1
        sqz[f"fwd_{h}"] = fwd.reindex(sqz.index)
    print(f"\n  trigger 자리(수렴 하위 10% + low가 ma10*1.02 이내) 누적 발생 횟수 = {len(sqz)}")
    if len(sqz) > 0:
        for h in [5, 10, 20]:
            v = sqz[f"fwd_{h}"].dropna() * 100
            if len(v) > 0:
                print(f"  fwd {h:>2}봉 평균: {v.mean():+.2f}%   중앙값: {v.median():+.2f}%   양수비율: {(v>0).mean()*100:.0f}%   n={len(v)}")
        print(f"\n  최근 5개 trigger:")
        for idx, r in sqz.tail(5).iterrows():
            print(f"    {idx.date()}  close={r['close']:.2f}  ma10={r['ma10']:.2f}  ma20={r['ma20']:.2f}  수렴={r['conv_pct']:.2f}%  fwd5={r['fwd_5']*100 if pd.notna(r['fwd_5']) else float('nan'):+.1f}%  fwd20={r['fwd_20']*100 if pd.notna(r['fwd_20']) else float('nan'):+.1f}%")

for name, d in frames.items():
    analyze(name, d)
