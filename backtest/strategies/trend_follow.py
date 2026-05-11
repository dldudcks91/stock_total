"""전략 A — 추세 진행 중 종목 롱 추종 (long-only).

보유 조건 (모두 충족 시 long, 그 외 0):
    - EMA(fast) > EMA(mid) > EMA(slow)  정배열
    - ADX(adx_n) > adx_min  (추세 강도)

룩어헤드 안전. 엔진이 t→t+1 체결 시프트 처리.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NAME = "trend_follow"

DEFAULT_PARAMS = {
    "ema_fast": 20,
    "ema_mid": 50,
    "ema_slow": 200,
    "adx_n": 14,
    "adx_min": 20.0,
    "weekly_filter": True,
    "weekly_sma": 10,
}


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _adx(df: pd.DataFrame, n: int) -> pd.Series:
    high = df["high"].astype("float64")
    low = df["low"].astype("float64")
    close = df["close"].astype("float64")
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat(
        [(high - low),
         (high - close.shift(1)).abs(),
         (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    atr_n = tr.rolling(n, min_periods=n).mean()
    plus_di = 100.0 * pd.Series(plus_dm, index=df.index).rolling(n, min_periods=n).mean() / atr_n
    minus_di = 100.0 * pd.Series(minus_dm, index=df.index).rolling(n, min_periods=n).mean() / atr_n
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(n, min_periods=n).mean()


def signal(df: pd.DataFrame, params: dict) -> pd.Series:
    p = {**DEFAULT_PARAMS, **params}
    close = df["close"].astype("float64")

    ema_f = _ema(close, int(p["ema_fast"]))
    ema_m = _ema(close, int(p["ema_mid"]))
    ema_s = _ema(close, int(p["ema_slow"]))
    adx = _adx(df, int(p["adx_n"]))

    aligned = (ema_f > ema_m) & (ema_m > ema_s)
    strong = adx > float(p["adx_min"])
    long_hold = (aligned & strong).fillna(False)

    if bool(p.get("weekly_filter", False)) and p.get("_symbol"):
        from backtest.engine.weekly_filter import weekly_above_sma_mask
        wm = weekly_above_sma_mask(p["_symbol"], df, sma_n=int(p["weekly_sma"]))
        long_hold = long_hold & pd.Series(wm, index=df.index)

    return long_hold.astype("int8").rename(None)
