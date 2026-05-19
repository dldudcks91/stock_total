"""사이클 B 6단계 후보 스캔: 각 단계에 해당할 수 있는 종목을 자동 추출."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
from data.loader import load_ohlcv

CACHE_1D = Path("data/cache/crypto/1d")

def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    return df.resample(rule).agg(agg).dropna()

def analyze(symbol: str) -> dict | None:
    try:
        df_1d = load_ohlcv("crypto", symbol, "1d")
    except Exception:
        return None
    if len(df_1d) < 200:
        return None
    # Normalize
    df_1d = df_1d.rename(columns={c: c.lower() for c in df_1d.columns})
    if "timestamp" in df_1d.columns:
        idx = pd.to_datetime(df_1d["timestamp"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
        df_1d = df_1d.set_index(idx)
    df_1d = df_1d[["open","high","low","close","volume"]]
    df = resample(df_1d, "W-MON")
    if len(df) < 60:
        return None
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma50"] = df["close"].rolling(50).mean()
    # 1W 분석
    last = df.iloc[-1]
    if pd.isna(last["ma50"]):
        return None
    close = last["close"]
    ma20, ma50 = last["ma20"], last["ma50"]
    # 최근 4주 MA20 기울기
    ma20_slope = (last["ma20"] - df["ma20"].iloc[-5]) / df["ma20"].iloc[-5]
    ma50_slope = (last["ma50"] - df["ma50"].iloc[-5]) / df["ma50"].iloc[-5]
    # 52주 고점 대비 거리
    hh_52 = df["high"].iloc[-52:].max()
    drawdown = (close - hh_52) / hh_52
    # 고점 발생 시점 (몇 주 전)
    weeks_since_peak = len(df) - 1 - df["high"].iloc[-52:].idxmax().to_pydatetime().__sub__(df.index[0]).days // 7 if False else None
    # 52주 평균 거래대금 (proxy: volume * close)
    avg_amount = (df["volume"].iloc[-26:] * df["close"].iloc[-26:]).mean()
    return {
        "symbol": symbol,
        "close": close,
        "ma20": ma20,
        "ma50": ma50,
        "vs_ma20_%": (close/ma20 - 1) * 100,
        "vs_ma50_%": (close/ma50 - 1) * 100,
        "ma20_slope_4w_%": ma20_slope * 100,
        "ma50_slope_4w_%": ma50_slope * 100,
        "dd_from_52wh_%": drawdown * 100,
        "avg_amount_usd": avg_amount,
    }

def stage_label(row: dict) -> str:
    """완화된 휴리스틱."""
    p_vs20 = row["vs_ma20_%"]
    p_vs50 = row["vs_ma50_%"]
    s20 = row["ma20_slope_4w_%"]
    s50 = row["ma50_slope_4w_%"]
    dd = row["dd_from_52wh_%"]

    # B1: 우상향 추세 유지 + 가격 MA20 위 + 고점 근처
    if p_vs20 > 3 and s20 > 1 and s50 > 0.5 and dd > -20:
        return "B1_uptrend"
    # B2: 피크 직후 횡보 — MA20 부근, slope 거의 0
    if abs(p_vs20) < 5 and abs(s20) < 1.5 and -20 < dd < -3 and s50 > -1:
        return "B2_top_compression"
    # B3: 막 MA20 깨고 내려옴, MA50 은 아직 양 기울기
    if -12 < p_vs20 < 0 and -3 < s20 < 0 and s50 > 0 and -25 < dd < -8:
        return "B3_breakdown"
    # B4: 본격 하락 — MA20 음 기울기, MA50 도 평탄/음
    if p_vs20 < -3 and s20 < -1 and s50 < 0.5 and -40 < dd < -15:
        return "B4_breakdown_confirming"
    # B5: 깊은 하락 확정
    if p_vs20 < -8 and p_vs50 < -15 and s20 < -3 and s50 < -2 and dd < -30:
        return "B5_breakdown_confirmed"
    # B6: 깊은 하락 후 단기 반등 (가격이 MA20 근처로 회복)
    if -8 < p_vs20 < 0 and p_vs50 < -20 and s20 < 0 and s50 < -1:
        return "B6_bounce_after"
    return "other"

if __name__ == "__main__":
    symbols = [p.stem for p in CACHE_1D.glob("*.parquet")]
    print(f"scanning {len(symbols)} crypto symbols ...")
    rows = []
    for s in symbols:
        r = analyze(s)
        if r is None:
            continue
        # 유동성 컷
        if r["avg_amount_usd"] < 5_000_000:
            continue
        r["stage"] = stage_label(r)
        rows.append(r)
    df = pd.DataFrame(rows).set_index("symbol")
    df = df.sort_values(["stage", "avg_amount_usd"], ascending=[True, False])
    print()
    for stage in ["B1_uptrend","B2_top_compression","B3_breakdown","B4_breakdown_confirming","B5_breakdown_confirmed","B6_bounce_after"]:
        sub = df[df["stage"] == stage].head(3)
        if len(sub) == 0:
            print(f"\n=== {stage}: (없음) ===")
            continue
        print(f"\n=== {stage} (top 3 by liquidity) ===")
        cols = ["close","vs_ma20_%","vs_ma50_%","ma20_slope_4w_%","ma50_slope_4w_%","dd_from_52wh_%"]
        print(sub[cols].round(2).to_string())
