"""모멘텀 ROC 가속 진입 (long-only).

진입:
    - ROC(``roc_n``) ≥ ``roc_min``  (장기 모멘텀 양호)
    - ROC(``roc_short``) > ROC(``roc_short``).rolling(``accel_n``).mean()  (단기 가속)
    - close > EMA(``trend_ema``)
청산:
    - close < EMA(``exit_ema``) 또는 ROC(``roc_short``) < 0
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NAME = "momentum_roc"

DEFAULT_PARAMS = {
    "roc_n": 30,
    "roc_min": 0.10,
    "roc_short": 5,
    "accel_n": 10,
    "trend_ema": 100,
    "exit_ema": 20,
    "max_hold": 60,
    "sl_pct": -0.10,
    "weekly_filter": True,
    "weekly_sma": 10,
}


def signal(df: pd.DataFrame, params: dict) -> pd.Series:
    p = {**DEFAULT_PARAMS, **params}
    close = df["close"].astype("float64")

    roc_l = close.pct_change(int(p["roc_n"]))
    roc_s = close.pct_change(int(p["roc_short"]))
    accel = roc_s > roc_s.rolling(int(p["accel_n"]), min_periods=int(p["accel_n"])).mean()

    trend_ema = close.ewm(span=int(p["trend_ema"]), adjust=False, min_periods=int(p["trend_ema"])).mean()
    in_uptrend = close > trend_ema

    enter = (
        (roc_l >= float(p["roc_min"])) & accel & in_uptrend
    ).fillna(False)

    exit_ema = close.ewm(span=int(p["exit_ema"]), adjust=False, min_periods=int(p["exit_ema"])).mean()
    exit_cond = ((close < exit_ema) | (roc_s < 0)).fillna(False)

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
