"""Crypto OHLCV 로더 (캐시 우선, 부족하면 리샘플).

캐시 정책:
  1h : data/cache/crypto/1h/{SYMBOL}.parquet (raw)
  1d : data/cache/crypto/1d/{SYMBOL}.parquet (raw, 있으면 우선 사용)
  4h : 1h 캐시에서 메모리 리샘플
  1w : 1d 캐시에서 메모리 리샘플 (없으면 1h에서)
  1M : 1d 캐시에서 메모리 리샘플 (없으면 1h에서)

사용:
    from data.resample import load
    df = load("BTCUSDT", "4h")
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).parent / "cache" / "crypto"

RULE = {
    "1h": None,
    "4h": "4h",
    "1d": "1D",
    "1w": "W-MON",
    "1M": "MS",   # month-start
}

OHLCV_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
    "amount": "sum",
}

OUT_COLS = ["timestamp", "open", "high", "low", "close", "volume", "amount"]


def _cache_path(symbol: str, gran: str = "1h") -> Path:
    return CACHE_DIR / gran / f"{symbol}.parquet"


def resample(df_src: pd.DataFrame, interval: str) -> pd.DataFrame:
    rule = RULE[interval]
    if rule is None:
        return df_src.copy()

    df = df_src.copy()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("dt")
    out = df.resample(rule, label="left", closed="left").agg(OHLCV_AGG).dropna()
    # pandas 2.x는 ns, 3.x는 ms 정밀도라 // 10**6이 깨진다.
    # numpy datetime64[ms]로 강제 변환해 어떤 pandas 버전에서도 ms int64를 얻음.
    out["timestamp"] = (
        out.index.tz_convert("UTC")
        .tz_localize(None)
        .to_numpy(dtype="datetime64[ms]")
        .astype("int64")
    )
    return out.reset_index(drop=True)[OUT_COLS]


def load(symbol: str, interval: str = "1h") -> pd.DataFrame:
    if interval not in RULE:
        raise ValueError(f"interval must be one of {list(RULE)}, got {interval}")

    path_1d = _cache_path(symbol, "1d")
    path_1h = _cache_path(symbol, "1h")

    # 1h / 4h 는 1h raw 가 항상 필요
    if interval in ("1h", "4h"):
        return resample(pd.read_parquet(path_1h), interval)

    # 1d : 1d 캐시 있으면 그대로 반환, 없으면 1h 에서 리샘플
    if interval == "1d":
        if path_1d.exists():
            return pd.read_parquet(path_1d)[OUT_COLS]
        return resample(pd.read_parquet(path_1h), "1d")

    # 1w / 1M : 1d 캐시 우선, 없으면 1h
    src = pd.read_parquet(path_1d) if path_1d.exists() else pd.read_parquet(path_1h)
    return resample(src, interval)
