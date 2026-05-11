"""1H parquet 캐시 → 4H/1D/1W 리샘플 (메모리 상에서만, 저장 안 함).

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


def _cache_path(symbol: str) -> Path:
    return CACHE_DIR / f"bitget_{symbol}_1h.parquet"


def resample(df_1h: pd.DataFrame, interval: str) -> pd.DataFrame:
    rule = RULE[interval]
    if rule is None:
        return df_1h.copy()

    df = df_1h.copy()
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
    df_1h = pd.read_parquet(_cache_path(symbol))
    return resample(df_1h, interval)
