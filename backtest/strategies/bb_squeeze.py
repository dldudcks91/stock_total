"""볼린저밴드 폭 압축 후 상단 돌파 (long-only).

진입:
    - BB 폭(상단-하단)/중심선이 직전 ``squeeze_lookback`` 봉 평균보다 ``squeeze_ratio`` 이하
    - close > 상단 BB
    - 거래량 ≥ 평균 × ``vol_mul``
청산:
    - close < EMA(``exit_ema``)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NAME = "bb_squeeze"

DEFAULT_PARAMS = {
    "bb_n": 20,
    "bb_k": 2.0,
    "squeeze_lookback": 120,
    "squeeze_ratio": 0.7,
    "vol_n": 20,
    "vol_mul": 1.5,
    "exit_ema": 20,
    "max_hold": 60,
    "sl_pct": -0.10,
    "weekly_filter": True,
    "weekly_sma": 10,
}


def signal(df: pd.DataFrame, params: dict) -> pd.Series:
    p = {**DEFAULT_PARAMS, **params}
    close = df["close"].astype("float64")
    volume = df["volume"].astype("float64")

    n_bb = int(p["bb_n"])
    mid = close.rolling(n_bb, min_periods=n_bb).mean()
    std = close.rolling(n_bb, min_periods=n_bb).std(ddof=0)
    upper = mid + float(p["bb_k"]) * std
    lower = mid - float(p["bb_k"]) * std
    width = (upper - lower) / mid

    width_avg = width.rolling(int(p["squeeze_lookback"]), min_periods=int(p["squeeze_lookback"])).mean()
    squeezed = width <= width_avg * float(p["squeeze_ratio"])
    squeeze_recent = squeezed.shift(1).rolling(n_bb, min_periods=1).max().fillna(0).astype(bool)

    breakout = close > upper.shift(1)

    vol_avg = volume.rolling(int(p["vol_n"]), min_periods=int(p["vol_n"])).mean()
    vol_spike = volume >= vol_avg * float(p["vol_mul"])

    enter = (squeeze_recent & breakout & vol_spike).fillna(False)

    exit_ema = close.ewm(span=int(p["exit_ema"]), adjust=False, min_periods=int(p["exit_ema"])).mean()
    exit_cond = (close < exit_ema).fillna(False)

    if bool(p.get("weekly_filter", False)) and p.get("_symbol"):
        from backtest.engine.weekly_filter import weekly_above_sma_mask
        wm = weekly_above_sma_mask(p["_symbol"], df, sma_n=int(p["weekly_sma"]))
        enter = enter & pd.Series(wm, index=df.index)

    nrows = len(df)
    state = np.zeros(nrows, dtype=np.int8)
    e = enter.to_numpy()
    x = exit_cond.to_numpy()
    cl = close.to_numpy()
    max_hold = int(p["max_hold"])
    sl = float(p["sl_pct"])
    cur = 0
    held = 0
    entry_px = np.nan
    for i in range(nrows):
        if cur == 1:
            held += 1
            ret = cl[i] / entry_px - 1.0
            if x[i] or held >= max_hold or ret <= sl:
                cur = 0
                held = 0
                entry_px = np.nan
        if cur == 0 and e[i]:
            cur = 1
            held = 0
            entry_px = cl[i]
        state[i] = cur

    return pd.Series(state, index=df.index, dtype="int8")
