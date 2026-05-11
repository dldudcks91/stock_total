"""스윙 포인트 추출 (지그재그) — 룩어헤드 안전 버전.

`detect_swings(df, k)`:
    - 각 봉이 swing-high인지 swing-low인지를 라벨링.
    - swing-high[t] := high[t]가 [t-k, t+k] 윈도우의 최댓값.
    - 단, 시그널로 쓸 때는 t+k까지의 정보가 필요하므로 라벨이 t에 "확정되는" 시점은 t+k.
      → 룩어헤드를 피하려면 ``shift(k)``를 추가해 사용한다.
    - 본 모듈은 raw 라벨만 반환; 사용자는 컨텍스트에 맞게 시프트.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def detect_swings(df: pd.DataFrame, k: int = 5) -> pd.DataFrame:
    """Return DataFrame with two boolean columns: swing_high, swing_low.

    swing_high[t] = True iff high[t] == max(high[t-k..t+k]).
    swing_low[t]  = True iff low[t]  == min(low[t-k..t+k]).
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    high = df["high"].astype("float64")
    low = df["low"].astype("float64")
    win = 2 * k + 1
    # rolling on shifted series so window is centered on t.
    # use .rolling(win, center=True)
    h_max = high.rolling(win, center=True, min_periods=win).max()
    l_min = low.rolling(win, center=True, min_periods=win).min()
    swing_high = (high == h_max)
    swing_low = (low == l_min)
    return pd.DataFrame({"swing_high": swing_high.fillna(False),
                         "swing_low": swing_low.fillna(False)})
