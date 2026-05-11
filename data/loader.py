"""자산 무관 OHLCV 로더.

차트/대시보드/리포트가 자산(crypto/kr/us)에 관계없이 동일한 함수 시그니처로
캐시를 읽도록 하는 얇은 어댑터 레이어.

규약:
  crypto → data/cache/crypto/bitget_{SYMBOL}_1h.parquet, 1h/4h/1d/1w (resample)
  kr     → data/cache/kr/{6자리}.parquet, 1d (1w resample 지원)
  us     → data/cache/us/{TICKER}.parquet, 1d (1w resample 지원)

반환 DataFrame 컬럼은 자산 원본 스키마 그대로 유지 (정규화는 차트/지표 레이어에서):
  crypto → timestamp(UTC ms), open/high/low/close/volume/amount
  kr/us  → DatetimeIndex(naive), Open/High/Low/Close/Volume/Change
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd

Asset = Literal["crypto", "kr", "us"]

CACHE_ROOT = Path(__file__).resolve().parent / "cache"

CRYPTO_INTERVALS = ("1h", "4h", "1d", "1w")
STOCK_INTERVALS = ("1d", "1w")

_WEEKLY_AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def load_ohlcv(asset: Asset, symbol: str, interval: str = "1d") -> pd.DataFrame:
    """자산/심볼/인터벌에 맞는 OHLCV를 캐시에서 로드.

    Raises
    ------
    FileNotFoundError : 캐시 파일이 없을 때
    ValueError        : 지원 안 되는 (asset, interval) 조합
    """
    interval = interval.lower()

    if asset == "crypto":
        if interval not in CRYPTO_INTERVALS:
            raise ValueError(f"crypto interval must be one of {CRYPTO_INTERVALS}, got {interval}")
        from data.resample import load
        return load(symbol, interval)

    if asset in ("kr", "us"):
        if interval not in STOCK_INTERVALS:
            raise ValueError(f"{asset} interval must be one of {STOCK_INTERVALS}, got {interval}")
        path = CACHE_ROOT / asset / f"{symbol}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"cache miss: {path}. Run /{asset}-fetch first.")
        df = pd.read_parquet(path)
        if interval == "1w":
            return df.resample("W-FRI").agg(_WEEKLY_AGG).dropna()
        return df

    raise ValueError(f"unknown asset: {asset!r} (expected 'crypto'|'kr'|'us')")


def list_symbols(asset: Asset) -> list[str]:
    """캐시에 존재하는 심볼 리스트 (정렬됨)."""
    if asset == "crypto":
        files = sorted((CACHE_ROOT / "crypto").glob("bitget_*_1h.parquet"))
        return [f.stem.replace("bitget_", "").replace("_1h", "") for f in files]
    if asset in ("kr", "us"):
        files = sorted((CACHE_ROOT / asset).glob("*.parquet"))
        return [f.stem for f in files if not f.stem.startswith("_")]
    raise ValueError(f"unknown asset: {asset!r}")
