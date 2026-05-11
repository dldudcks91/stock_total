"""전략 B — 변동성 스퀴즈 후 도네치안 돌파 (long-only).

진입 (둘 다 충족된 첫 봉):
    - 종가 > 직전 ``donchian_n`` 봉 최고가 (lookback excludes current bar)
    - 직전 ``squeeze_n`` 봉 표준편차가 ``squeeze_lookback`` 평균 대비 ``squeeze_ratio`` 이하
    - 거래량 ≥ ``vol_n`` 평균 × ``vol_mul``

청산:
    - 종가 < EMA(``exit_ema``)  하향 이탈
    - (벡터화: 진입 조건 → 1, EMA 이탈 → 0, 그 사이 ffill)

룩어헤드 안전. 엔진이 t→t+1 시프트.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NAME = "breakout_start"

DEFAULT_PARAMS = {
    "donchian_n": 20,
    "squeeze_n": 20,
    "squeeze_lookback": 60,
    "squeeze_ratio": 0.7,
    "vol_n": 20,
    "vol_mul": 2.0,
    "exit_ema": 20,
    "weekly_filter": True,
    "weekly_sma": 10,
}


def signal(df: pd.DataFrame, params: dict) -> pd.Series:
    p = {**DEFAULT_PARAMS, **params}
    close = df["close"].astype("float64")
    high = df["high"].astype("float64")
    volume = df["volume"].astype("float64")

    don_n = int(p["donchian_n"])
    sq_n = int(p["squeeze_n"])
    sq_lb = int(p["squeeze_lookback"])
    vol_n = int(p["vol_n"])

    # Donchian high excludes the current bar
    don_high = high.shift(1).rolling(don_n, min_periods=don_n).max()
    breakout = close > don_high

    # Squeeze: short-term std vs long-term avg of std
    std_s = close.rolling(sq_n, min_periods=sq_n).std(ddof=0)
    std_l = std_s.rolling(sq_lb, min_periods=sq_lb).mean()
    squeezed = std_s <= std_l * float(p["squeeze_ratio"])
    # squeeze should be true *recently* — check if it was true in the last sq_n bars
    squeeze_recent = squeezed.shift(1).rolling(sq_n, min_periods=1).max().fillna(0).astype(bool)

    vol_avg = volume.rolling(vol_n, min_periods=vol_n).mean()
    vol_spike = volume >= vol_avg * float(p["vol_mul"])

    enter = (breakout & squeeze_recent & vol_spike).fillna(False)

    if bool(p.get("weekly_filter", False)) and p.get("_symbol"):
        from backtest.engine.weekly_filter import weekly_above_sma_mask
        wm = weekly_above_sma_mask(p["_symbol"], df, sma_n=int(p["weekly_sma"]))
        enter = enter & pd.Series(wm, index=df.index)

    # Exit when close < EMA(exit_ema)
    exit_ema = close.ewm(span=int(p["exit_ema"]), adjust=False, min_periods=int(p["exit_ema"])).mean()
    exit_cond = (close < exit_ema).fillna(False)

    # State machine via vectorized cumulative scan:
    # state[t] = 1 if enter else (state[t-1] if not exit else 0).
    # Implement using a per-row loop on numpy (n is small enough; alternative: use np.where + ffill trick).
    n = len(df)
    state = np.zeros(n, dtype=np.int8)
    e = enter.to_numpy()
    x = exit_cond.to_numpy()
    cur = 0
    for i in range(n):
        if cur == 1 and x[i]:
            cur = 0
        if e[i]:
            cur = 1
        state[i] = cur

    return pd.Series(state, index=df.index, dtype="int8")
