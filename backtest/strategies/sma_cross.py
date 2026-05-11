"""SMA crossover sample strategy.

Module interface contract (shared by all strategies):
- ``NAME``           : str  — short identifier used in run dir names
- ``DEFAULT_PARAMS`` : dict — default parameter values
- ``signal(df, params) -> pd.Series``
      values must be in {-1, 0, 1} and aligned to ``df.index``.
      The signal at bar ``t`` is computed using only data available up to and
      including bar ``t`` (close-of-bar). The engine handles the t -> t+1 shift,
      so do NOT shift here.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NAME = "sma_cross"

DEFAULT_PARAMS = {
    "fast": 10,
    "slow": 30,
}


def signal(df: pd.DataFrame, params: dict) -> pd.Series:
    fast = int(params.get("fast", DEFAULT_PARAMS["fast"]))
    slow = int(params.get("slow", DEFAULT_PARAMS["slow"]))
    if fast <= 0 or slow <= 0 or fast >= slow:
        raise ValueError(f"require 0 < fast < slow, got fast={fast}, slow={slow}")

    close = df["close"].astype("float64")
    fast_ma = close.rolling(fast, min_periods=fast).mean()
    slow_ma = close.rolling(slow, min_periods=slow).mean()

    sig = pd.Series(0, index=df.index, dtype="int8")
    sig = sig.where(~(fast_ma > slow_ma), 1)
    sig = sig.where(~(fast_ma < slow_ma), -1)
    # rows where MAs are NaN (warmup) stay 0 because `where` keeps original 0
    sig = sig.fillna(0).astype("int8")
    return sig
