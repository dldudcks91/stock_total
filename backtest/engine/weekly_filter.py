"""주봉 SMA(N) 위인지 판정하는 거시 필터 (per-symbol).

규칙(룩어헤드 안전):
    - 해당 심볼의 1W 종가 > SMA(``sma_n``) → True
    - 1주 시프트 (직전 주봉 확정 종가만 사용)
    - merge_asof(backward)로 전략 봉 timestamp에 매핑

전략에서:
    from backtest.engine.weekly_filter import weekly_above_sma_mask
    mask = weekly_above_sma_mask(symbol, df, sma_n=10)   # bool, len == len(df)
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from data.resample import load as load_ohlcv


@lru_cache(maxsize=2048)
def _weekly_above_sma(symbol: str, sma_n: int) -> pd.DataFrame:
    w = load_ohlcv(symbol, "1w").copy()
    sma = w["close"].rolling(sma_n, min_periods=sma_n).mean()
    above = (w["close"] > sma).fillna(False)
    above = above.shift(1).fillna(False)  # 직전 주봉 종가까지만 정보
    return pd.DataFrame({
        "timestamp": w["timestamp"].astype("int64").to_numpy(),
        "weekly_above": above.to_numpy().astype(bool),
    })


def weekly_above_sma_mask(symbol: str, df: pd.DataFrame, sma_n: int = 10) -> np.ndarray:
    table = _weekly_above_sma(symbol, sma_n)
    if len(table) == 0:
        return np.zeros(len(df), dtype=bool)
    left = pd.DataFrame({"timestamp": df["timestamp"].astype("int64").to_numpy()})
    merged = pd.merge_asof(left, table, on="timestamp", direction="backward")
    return merged["weekly_above"].fillna(False).to_numpy().astype(bool)
