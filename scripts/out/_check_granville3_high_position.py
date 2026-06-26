"""3법칙 자리 종목들 — 정말 다 고점 부근인가?

위치 측정: 현재가가 28d/90d/1y high/low 사이 어디인가
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pathlib import Path
import numpy as np
import pandas as pd

K_DIST = 0.2

def position_pct(close, low, high):
    if high <= low:
        return 50.0
    return (close - low) / (high - low) * 100

def evaluate_asset(asset, symbols):
    rows = []
    for sym in symbols:
        fp = Path(f"data/cache/{asset}/{sym}.parquet")
        if not fp.exists():
            continue
        df = pd.read_parquet(fp)
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
        if len(df) < 250:
            continue
        last = df.iloc[-1]
        close = float(last["close"])

        h28 = float(df["high"].tail(28).max())
        l28 = float(df["low"].tail(28).min())
        h90 = float(df["high"].tail(90).max())
        l90 = float(df["low"].tail(90).min())
        h1y = float(df["high"].tail(252).max())
        l1y = float(df["low"].tail(252).min())

        rows.append({
            "symbol": sym,
            "close": close,
            "pos_28d": position_pct(close, l28, h28),
            "pos_90d": position_pct(close, l90, h90),
            "pos_1y": position_pct(close, l1y, h1y),
            "vs_1y_high_pct": (close / h1y - 1) * 100,
        })
    return pd.DataFrame(rows)

# KR 3법칙 통과
kr_syms = ["028260", "026940", "161890", "009320"]
# US 3법칙 상위 (메가캡 + slope 강한 자리)
us_syms = ["ASML", "FTNT", "NBIS", "VECO", "WING", "SDGR", "ACLS", "UPST",
           "PLXS", "RMIX", "SHAZ", "BGDE", "MBBC", "CCSI", "BBSI", "VITL"]

kr_df = evaluate_asset("kr", kr_syms)
us_df = evaluate_asset("us", us_syms)

# 이름 매핑
try:
    n1 = pd.read_csv("data/cache/kr/_names.csv", dtype={"Code": str})
    n2 = pd.read_csv("data/cache/kr/_names_kosdaq.csv", dtype={"Code": str})
    names = pd.concat([n1, n2]).drop_duplicates("Code").set_index("Code")["Name"].to_dict()
    kr_df["name"] = kr_df["symbol"].map(names)
except:
    pass

print("=== KR 3법칙 통과 종목의 위치 ===")
print("(pos_X = 현재가가 최근 X 박스의 어디 위치인지. 100% = 박스 상단, 0% = 박스 하단)")
print(kr_df.to_string(index=False, float_format=lambda v: f"{v:.1f}"))

print("\n=== US 3법칙 통과 메가캡/대형 종목의 위치 ===")
print(us_df.to_string(index=False, float_format=lambda v: f"{v:.1f}"))

# 평균
print("\n=== 평균 ===")
print(f"KR 평균 pos_1y: {kr_df['pos_1y'].mean():.1f}%   vs_1y_high: {kr_df['vs_1y_high_pct'].mean():.1f}%")
print(f"US 평균 pos_1y: {us_df['pos_1y'].mean():.1f}%   vs_1y_high: {us_df['vs_1y_high_pct'].mean():.1f}%")

# 1년 고점 5% 이내 종목 카운트
kr_near_high = (kr_df["vs_1y_high_pct"] >= -5).sum()
us_near_high = (us_df["vs_1y_high_pct"] >= -5).sum()
print(f"\n1년 고점 -5% 이내: KR {kr_near_high}/{len(kr_df)}, US {us_near_high}/{len(us_df)}")
