"""다중 TF (1D / 1W / 1M / 1Q / 1Y) OHLCV 로더.

자산별 raw parquet 을 읽어 `open, high, low, close, volume` 소문자 + DatetimeIndex
표준 스키마로 normalize 한 뒤, 1D / 1W / 1M / 1Q / 1Y 로 resample 한 dict 를 반환.

사용처: scripts/{kr,crypto,nasdaq}/ma_touch/recommend.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
_CACHE = _ROOT / "data" / "cache"

# 평가 대상 TF 와 pandas resample rule 매핑.
# (pandas 2.x: 'ME' / 'QE' / 'YE' — period end. 'W' 는 그대로.)
TF_FREQ: Dict[str, Optional[str]] = {
    "1D": None,    # resample 안 함 — daily 원본
    "1W": "W",
    "1M": "ME",
    "1Q": "QE",
    "1Y": "YE",
}

OHLCV_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def _crypto_path(symbol: str) -> Path:
    return _CACHE / "crypto" / "1d" / f"{symbol}.parquet"


def _stock_path(asset: str, symbol: str) -> Path:
    return _CACHE / asset / f"{symbol}.parquet"


def load_normalized_daily(asset: str, symbol: str) -> pd.DataFrame:
    """자산별 1D parquet 을 표준 스키마로 normalize.

    반환: 컬럼 [open, high, low, close, volume] (소문자) + DatetimeIndex 정렬.
    """
    if asset == "crypto":
        df = pd.read_parquet(_crypto_path(symbol))
        df = df.copy()
        df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("dt").sort_index()
        df = df[["open", "high", "low", "close", "volume"]]
    elif asset in ("kr", "us"):
        df = pd.read_parquet(_stock_path(asset, symbol))
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
        df = df[["open", "high", "low", "close", "volume"]]
    else:
        raise ValueError(f"Unknown asset: {asset!r} (expected kr/us/crypto)")
    # FDR 가 마지막 날 데이터 못 받으면 close=NaN 인 row 가 끝에 붙어 있을 수 있음.
    # 시그널은 마지막 봉을 보므로 close NaN row 는 평가 전에 제거.
    return df.dropna(subset=["close"])


def resample_multi_tf(df_d: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """1D OHLCV 를 5 TF dict 로 반환.

    출력 dict 키: '1D', '1W', '1M', '1Q', '1Y'. 각 값은 동일 컬럼 [open,high,low,close,volume].
    """
    out: Dict[str, pd.DataFrame] = {"1D": df_d}
    for tf, freq in TF_FREQ.items():
        if freq is None:
            continue
        rs = df_d.resample(freq).agg(OHLCV_AGG).dropna(how="all")
        out[tf] = rs
    return out


def load_multi_tf(asset: str, symbol: str) -> Dict[str, pd.DataFrame]:
    """1줄 헬퍼: load_normalized_daily + resample_multi_tf."""
    return resample_multi_tf(load_normalized_daily(asset, symbol))
