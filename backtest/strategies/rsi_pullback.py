"""상승추세 중 RSI 풀백 후 반등 진입 (long-only).

진입:
    - 상승추세: EMA(``trend_ema``) 상승 (close > EMA)
    - 풀백: RSI(``rsi_n``)가 ``rsi_low`` 이하로 진입
    - 반등 트리거: RSI가 ``rsi_low``를 상향 돌파
청산:
    - close < EMA(``exit_ema``)  또는 보유 ``max_hold`` 봉 초과 또는 손절 ``sl_pct``
공통 게이트:
    - 주봉 종가 > SMA(``weekly_sma``)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NAME = "rsi_pullback"

DEFAULT_PARAMS = {
    "trend_ema": 100,
    "rsi_n": 14,
    "rsi_low": 35.0,
    "exit_ema": 20,
    "max_hold": 80,
    "sl_pct": -0.10,
    "weekly_filter": True,
    "weekly_sma": 10,
}


def _rsi(close: pd.Series, n: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    ag = gain.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    al = loss.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = ag / al.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def signal(df: pd.DataFrame, params: dict) -> pd.Series:
    p = {**DEFAULT_PARAMS, **params}
    close = df["close"].astype("float64")

    trend_ema = close.ewm(span=int(p["trend_ema"]), adjust=False, min_periods=int(p["trend_ema"])).mean()
    in_uptrend = (close > trend_ema).fillna(False)

    rsi = _rsi(close, int(p["rsi_n"]))
    low_t = float(p["rsi_low"])
    rsi_prev = rsi.shift(1)
    cross_up = (rsi > low_t) & (rsi_prev <= low_t)
    enter = (in_uptrend & cross_up).fillna(False)

    exit_ema = close.ewm(span=int(p["exit_ema"]), adjust=False, min_periods=int(p["exit_ema"])).mean()
    exit_cond = (close < exit_ema).fillna(False)

    if bool(p.get("weekly_filter", False)) and p.get("_symbol"):
        from backtest.engine.weekly_filter import weekly_above_sma_mask
        wm = weekly_above_sma_mask(p["_symbol"], df, sma_n=int(p["weekly_sma"]))
        enter = enter & pd.Series(wm, index=df.index)

    n = len(df)
    state = np.zeros(n, dtype=np.int8)
    e = enter.to_numpy()
    x = exit_cond.to_numpy()
    cl = close.to_numpy()
    max_hold = int(p["max_hold"])
    sl = float(p["sl_pct"])
    cur = 0
    held = 0
    entry_px = np.nan
    for i in range(n):
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
