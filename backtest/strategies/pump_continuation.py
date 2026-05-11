"""전략 C — 임펄스 후 2차 파동 (long-only, whale 종목 타겟).

논리:
    1) 임펄스: 직전 ``impulse_bars`` 봉 동안 누적 수익률 ≥ ``impulse_pct``
    2) 조정 건강성: 임펄스 고점 대비 현재 종가 되돌림 ≤ ``retrace_max``
       (임펄스 이후 ``cool_max`` 봉 이내 진입 가능)
    3) 트리거: 종가가 임펄스 이후의 ``trigger_n`` 봉 박스 최고가를 돌파
              + 거래량 ≥ ``vol_n`` 평균 × ``vol_mul``

청산:
    - 종가 < EMA(``exit_ema``) 또는 보유 ``max_hold`` 봉 초과

엔진은 t→t+1 시프트만 처리. 1H 인터벌 권장.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NAME = "pump_continuation"

DEFAULT_PARAMS = {
    "impulse_bars": 24,        # 1H 24개 = 24h
    "impulse_pct": 0.20,       # +20% 이상
    "retrace_max": 0.50,       # 50% 이내 되돌림만 건강
    "cool_max": 24,            # 임펄스 후 24봉 내 진입
    "trigger_n": 6,            # 직전 6봉 박스 돌파
    "vol_n": 20,
    "vol_mul": 1.5,
    "exit_ema": 20,
    "max_hold": 48,            # 최대 48봉 보유
    "btc_filter": True,
    "btc_filter_ema": 200,
}


def signal(df: pd.DataFrame, params: dict) -> pd.Series:
    p = {**DEFAULT_PARAMS, **params}
    close = df["close"].astype("float64")
    high = df["high"].astype("float64")
    volume = df["volume"].astype("float64")

    imp_n = int(p["impulse_bars"])
    cool = int(p["cool_max"])
    trig_n = int(p["trigger_n"])
    vol_n = int(p["vol_n"])

    # 임펄스: t-imp_n에서 t까지의 누적수익률
    impulse_ret = close / close.shift(imp_n) - 1.0
    impulse_hit = impulse_ret >= float(p["impulse_pct"])

    # 임펄스 이후 cool 봉 이내 윈도우 내에 임펄스가 있었는지
    # impulse_hit를 cool봉 만큼 ffill한 효과
    impulse_recent = impulse_hit.shift(1).rolling(cool, min_periods=1).max().fillna(0).astype(bool)

    # 임펄스 윈도우 최고가 (직전 imp_n + cool 봉 동안의 최대)
    impulse_peak = high.shift(1).rolling(imp_n + cool, min_periods=1).max()
    retrace = (impulse_peak - close) / impulse_peak
    retrace_ok = retrace <= float(p["retrace_max"])

    # 트리거: 직전 trig_n 봉 박스 돌파
    box_high = high.shift(1).rolling(trig_n, min_periods=trig_n).max()
    breakout = close > box_high

    vol_avg = volume.rolling(vol_n, min_periods=vol_n).mean()
    vol_spike = volume >= vol_avg * float(p["vol_mul"])

    enter = (impulse_recent & retrace_ok & breakout & vol_spike).fillna(False)

    if bool(p.get("btc_filter", False)):
        from backtest.engine.btc_filter import btc_uptrend_mask
        mask = btc_uptrend_mask(df, ema_n=int(p["btc_filter_ema"]))
        enter = enter & pd.Series(mask, index=df.index)

    # exit
    exit_ema = close.ewm(span=int(p["exit_ema"]), adjust=False, min_periods=int(p["exit_ema"])).mean()
    exit_cond = (close < exit_ema).fillna(False)

    n = len(df)
    state = np.zeros(n, dtype=np.int8)
    e = enter.to_numpy()
    x = exit_cond.to_numpy()
    max_hold = int(p["max_hold"])
    cur = 0
    held = 0
    for i in range(n):
        if cur == 1:
            held += 1
            if x[i] or held >= max_hold:
                cur = 0
                held = 0
        if cur == 0 and e[i]:
            cur = 1
            held = 0
        state[i] = cur

    return pd.Series(state, index=df.index, dtype="int8")
