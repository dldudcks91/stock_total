"""다중 TF row 단위 지표 — ma_touch 시그널의 입력 컬럼 준비.

입력 df_tf: 단일 TF 의 normalize 된 OHLCV (소문자 close, volume, ...).
출력: 같은 df 에 다음 컬럼 add — 원본 보존을 위해 copy 후 반환.

  ma10, ma20                   (MA20 는 partial 케이스에 NaN)
  slope_pct_ma10               (5봉 윈도우 pct_change)
  slope_pct_ma20               (full 케이스만, partial 은 NaN)
  angle_ma10_deg               (degrees(arctan(slope_per_bar)) — 1봉당 변화율 환산)
  angle_ma20_deg               (full 케이스만)
  dist_to_ma10_pct             ((close/ma10 - 1) * 100)
  dist_to_ma20_pct             (full 케이스만)
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

MA10_PERIOD = 10
MA20_PERIOD = 20
SLOPE_WINDOW = 5


def compute_mtf_indicators(df_tf: pd.DataFrame, kind: Literal["full", "partial"]) -> pd.DataFrame:
    """단일 TF df 에 ma_touch 입력 지표 add.

    kind='full'   → ma10/ma20 둘 다 + 정배열 게이트용 컬럼 add
    kind='partial' → ma10 만 + partial 게이트용 컬럼 add (ma20 컬럼 NaN)
    """
    df = df_tf.copy()
    c = df["close"]

    df["ma10"] = c.rolling(MA10_PERIOD).mean()
    df["slope_pct_ma10"] = df["ma10"].pct_change(SLOPE_WINDOW, fill_method=None)
    df["angle_ma10_deg"] = np.degrees(np.arctan(df["slope_pct_ma10"] / SLOPE_WINDOW))
    df["dist_to_ma10_pct"] = (c / df["ma10"] - 1) * 100

    if kind == "full":
        df["ma20"] = c.rolling(MA20_PERIOD).mean()
        df["slope_pct_ma20"] = df["ma20"].pct_change(SLOPE_WINDOW, fill_method=None)
        df["angle_ma20_deg"] = np.degrees(np.arctan(df["slope_pct_ma20"] / SLOPE_WINDOW))
        df["dist_to_ma20_pct"] = (c / df["ma20"] - 1) * 100
    else:
        df["ma20"] = np.nan
        df["slope_pct_ma20"] = np.nan
        df["angle_ma20_deg"] = np.nan
        df["dist_to_ma20_pct"] = np.nan

    return df
