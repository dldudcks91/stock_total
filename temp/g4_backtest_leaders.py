"""G4 (그랜빌 4법칙) 임계값 탐색 — 주도주 대상 간단 백테스트.

목적: "MA60 하락 + close 이격 하위 X% percentile" 자리에서 진입했을 때
     forward return 이 어떤지 자산군별로 눈으로 확인.

룰:
  - MA60 (일봉) slope (20일 변화율) < 0 : 하락 추세
  - close < MA60
  - deviation = (close - MA60) / MA60  (음수)
  - deviation 이 rolling 3년(756봉) 분포에서 하위 5%/10% percentile 이하
  - 연속 신호는 첫봉만 (30일 재신호 억제)
  - forward 5/10/20/60일 수익률 = close(t+n) / close(t) - 1

주도주 (하드코딩):
  KR: 005930 삼성전자, 000660 SK하이닉스, 373220 LG에너지솔루션,
      207940 삼성바이오로직스, 005380 현대차
  US: AAPL, MSFT, NVDA, GOOGL, AMZN
  Crypto: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
KR_DIR = ROOT / "data" / "cache" / "kr"
US_DIR = ROOT / "data" / "cache" / "us"
CR_DIR = ROOT / "data" / "cache" / "crypto" / "1d"

LEADERS = {
    "KR": [
        ("005930", "삼성전자"),
        ("000660", "SK하이닉스"),
        ("373220", "LG에너지솔루션"),
        ("207940", "삼성바이오로직스"),
        ("005380", "현대차"),
    ],
    "US": [
        ("AAPL", "Apple"),
        ("MSFT", "Microsoft"),
        ("NVDA", "NVIDIA"),
        ("GOOGL", "Alphabet"),
        ("AMZN", "Amazon"),
    ],
    "Crypto": [
        ("BTCUSDT", "BTC"),
        ("ETHUSDT", "ETH"),
        ("SOLUSDT", "SOL"),
        ("XRPUSDT", "XRP"),
        ("BNBUSDT", "BNB"),
    ],
}

MA_WIN = 60
SLOPE_WIN = 20
PCT_WIN = 756          # 약 3년 (거래일)
FORWARDS = [5, 10, 20, 60]
COOLDOWN = 30          # 재신호 억제 봉수
PCTS = [0.05, 0.10]    # 하위 5%, 10% 두 개 비교


def load(asset: str, sym: str) -> pd.DataFrame:
    """자산별 캐시 read → 표준 컬럼(close) 로 정규화된 일봉."""
    if asset == "KR":
        p = KR_DIR / f"{sym}.parquet"
    elif asset == "US":
        p = US_DIR / f"{sym}.parquet"
    else:
        p = CR_DIR / f"{sym}.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    if asset == "Crypto":
        # timestamp(ms) → DatetimeIndex, close 소문자
        df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert(None)
        df = df.set_index("ts").sort_index()
        df["close"] = df["close"].astype(float)
    else:
        # FDR: Close 대문자 → close
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
    return df[["close"]]


def backtest_symbol(df: pd.DataFrame, pct: float) -> pd.DataFrame:
    """단일 심볼 백테스트. 신호 발생 시점별 forward return 반환."""
    if len(df) < PCT_WIN + MA_WIN:
        return pd.DataFrame()
    close = df["close"]
    ma = close.rolling(MA_WIN).mean()
    slope = ma.diff(SLOPE_WIN)
    dev = (close - ma) / ma
    # rolling percentile 임계 (하위 pct 분위)
    pct_thresh = dev.rolling(PCT_WIN, min_periods=252).quantile(pct)

    cond = (slope < 0) & (close < ma) & (dev <= pct_thresh)

    # cooldown: 신호 후 COOLDOWN 봉 안 재신호 무시
    signals = []
    last_i = -10**9
    idx = df.index
    cond_arr = cond.to_numpy()
    for i in range(len(df)):
        if not cond_arr[i]:
            continue
        if i - last_i < COOLDOWN:
            continue
        signals.append(i)
        last_i = i

    if not signals:
        return pd.DataFrame()

    rows = []
    close_arr = close.to_numpy()
    for i in signals:
        row = {"date": idx[i], "dev": dev.iloc[i]}
        for n in FORWARDS:
            j = i + n
            if j >= len(close_arr):
                row[f"ret_{n}d"] = np.nan
            else:
                row[f"ret_{n}d"] = close_arr[j] / close_arr[i] - 1
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(rets: pd.DataFrame, pct_label: str, asset: str, name: str) -> dict:
    if rets.empty:
        return {
            "asset": asset, "종목": name, "임계": pct_label,
            "신호수": 0,
        }
    out = {
        "asset": asset, "종목": name, "임계": pct_label,
        "신호수": len(rets),
        "평균이격": f"{rets['dev'].mean()*100:.1f}%",
    }
    for n in FORWARDS:
        col = f"ret_{n}d"
        r = rets[col].dropna()
        if r.empty:
            out[f"평균수익_{n}일"] = "-"
            out[f"승률_{n}일"] = "-"
            continue
        out[f"평균수익_{n}일"] = f"{r.mean()*100:+.1f}%"
        out[f"승률_{n}일"] = f"{(r > 0).mean()*100:.0f}%"
    return out


def main():
    all_rows = []
    for asset, syms in LEADERS.items():
        for sym, name in syms:
            df = load(asset, sym)
            if df.empty:
                print(f"[SKIP] {asset} {sym} {name} — 캐시 없음/부족")
                continue
            for pct in PCTS:
                rets = backtest_symbol(df, pct)
                all_rows.append(summarize(rets, f"하위{int(pct*100)}%", asset, name))

    tbl = pd.DataFrame(all_rows)
    # 자산별 임계별 평균 요약도
    print("\n=== 종목별 상세 ===")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(tbl.to_string(index=False))

    # 자산-임계 그룹 평균 (신호수 가중)
    print("\n=== 자산 × 임계 요약 (모든 주도주 신호를 합쳐서 재집계) ===")
    grouped_rows = []
    for asset, syms in LEADERS.items():
        for pct in PCTS:
            all_signals = []
            for sym, name in syms:
                df = load(asset, sym)
                if df.empty:
                    continue
                rets = backtest_symbol(df, pct)
                if not rets.empty:
                    rets = rets.copy()
                    rets["종목"] = name
                    all_signals.append(rets)
            if not all_signals:
                grouped_rows.append({"asset": asset, "임계": f"하위{int(pct*100)}%", "신호수": 0})
                continue
            merged = pd.concat(all_signals, ignore_index=True)
            row = {
                "asset": asset,
                "임계": f"하위{int(pct*100)}%",
                "신호수": len(merged),
                "평균이격": f"{merged['dev'].mean()*100:.1f}%",
            }
            for n in FORWARDS:
                r = merged[f"ret_{n}d"].dropna()
                if r.empty:
                    row[f"평균수익_{n}일"] = "-"
                    row[f"승률_{n}일"] = "-"
                    continue
                row[f"평균수익_{n}일"] = f"{r.mean()*100:+.1f}%"
                row[f"승률_{n}일"] = f"{(r > 0).mean()*100:.0f}%"
                row[f"중앙_{n}일"] = f"{r.median()*100:+.1f}%"
            grouped_rows.append(row)
    gtbl = pd.DataFrame(grouped_rows)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(gtbl.to_string(index=False))


if __name__ == "__main__":
    main()
