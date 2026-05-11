"""BTC 거시 필터: 각 전략 시그널을 'BTC 강세장' 봉에서만 1로 유지.

규칙(룩어헤드 안전):
    - BTC 1D close > EMA(``ema_n``) → 강세
    - 1D 라벨을 1일 시프트해 사용 (오늘 적용되는 BTC 강세 = 어제 일봉 종가 기준)
    - merge_asof(backward)로 전략 봉 timestamp에 매핑

사용:
    from backtest.engine.btc_filter import btc_uptrend_mask
    mask = btc_uptrend_mask(df, ema_n=200)   # bool, 길이 == len(df)
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from data.resample import load as load_ohlcv


@lru_cache(maxsize=8)
def _btc_uptrend_daily(ema_n: int) -> pd.DataFrame:
    btc = load_ohlcv("BTCUSDT", "1d").copy()
    ema = btc["close"].ewm(span=ema_n, adjust=False, min_periods=ema_n).mean()
    up = (btc["close"] > ema).fillna(False)
    # 어제 일봉 종가 기준으로 오늘 적용 (룩어헤드 회피)
    up = up.shift(1).fillna(False)
    return pd.DataFrame({"timestamp": btc["timestamp"].astype("int64").to_numpy(),
                         "btc_up": up.to_numpy().astype(bool)})


def btc_uptrend_mask(df: pd.DataFrame, ema_n: int = 200) -> np.ndarray:
    """전략 df의 각 봉에 대해 BTC 일봉 강세 여부 (bool array)."""
    btc_up = _btc_uptrend_daily(ema_n)
    left = pd.DataFrame({"timestamp": df["timestamp"].astype("int64").to_numpy()})
    merged = pd.merge_asof(left, btc_up, on="timestamp", direction="backward")
    return merged["btc_up"].fillna(False).to_numpy().astype(bool)
