"""MTF 렌더: 각 차트는 200봉 고정, TF 별로 zoom level 이 다름."""
from __future__ import annotations
import sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import mplfinance as mpf
from data.loader import load_ohlcv

OUT = Path(__file__).parent
BARS = 200

def normalize(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for need in ("open", "high", "low", "close", "volume"):
        if need in cols:
            rename[cols[need]] = need.capitalize()
    df = df.rename(columns=rename)
    if "timestamp" in df.columns:
        idx = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
        df = df.set_index(idx)
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    return df[["Open", "High", "Low", "Close", "Volume"]]

def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    return df.resample(rule).agg(agg).dropna()

def render(df_full: pd.DataFrame, symbol: str, tf: str, fname: str, bars: int = BARS):
    """MA10/20/50 을 풀데이터로 계산 후 tail(bars) 만 출력."""
    out_path = OUT / fname
    t0 = time.perf_counter()
    ma10 = df_full["Close"].rolling(10).mean()
    ma20 = df_full["Close"].rolling(20).mean()
    ma50 = df_full["Close"].rolling(50).mean()
    df = df_full.tail(bars)
    addplots = [
        mpf.make_addplot(ma10.tail(bars), color="gold",   width=0.8),
        mpf.make_addplot(ma20.tail(bars), color="red",    width=0.8),
        mpf.make_addplot(ma50.tail(bars), color="blue",   width=0.8),
    ]
    span = f"{df.index[0].date()} ~ {df.index[-1].date()}"
    mpf.plot(
        df,
        type="candle",
        style="charles",
        volume=True,
        addplot=addplots,
        title=f"{symbol} · {tf} ({len(df)} bars · {span})  MA10/20/50",
        figsize=(14, 8),
        warn_too_much_data=10**7,
        savefig=dict(fname=str(out_path), dpi=110, bbox_inches="tight"),
    )
    dt = time.perf_counter() - t0
    print(f"  {tf}: {len(df)} bars  ({span})  ({dt:.2f}s)  → {out_path.name}")

def run(asset: str, symbol: str, tfs: list[str], prefix: str):
    print(f"[{asset}:{symbol}]")
    df_1d = normalize(load_ohlcv(asset, symbol, "1d"))
    rule_map = {"1d": None, "1w": "W-MON", "1m": "ME"}
    for tf in tfs:
        rule = rule_map[tf]
        df_full = df_1d if rule is None else resample(df_1d, rule)
        render(df_full, symbol, tf.upper(), f"{prefix}_{tf}.png")

if __name__ == "__main__":
    # warmup
    df_w = normalize(load_ohlcv("crypto", "POLYXUSDT", "1d"))
    render(df_w, "POLYXUSDT", "1D", "_warmup.png", bars=50)
    print()
    # Cycle B candidates (1W + 1D)
    run("crypto", "TRXUSDT", ["1w", "1d"], "trx")
    run("crypto", "BTCUSDT", ["1w", "1d"], "btc")
    run("crypto", "BCHUSDT", ["1w", "1d"], "bch")
    run("crypto", "SOLUSDT", ["1w", "1d"], "sol")
    run("crypto", "SUIUSDT", ["1w", "1d"], "sui")
