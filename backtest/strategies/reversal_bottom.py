"""전략 D — 장기 하락 끝 추세 전환 (long-only, 1D 권장).

진입 조건 (셋 모두 충족):
    1) 200일 고점 대비 ``drawdown_min`` 이상 하락 (-0.6 = -60%)
    2) RSI 강세 다이버전스: 최근 ``div_lookback`` 봉에서 가격은 새 저점,
       그 사이 RSI(14)는 직전 저점보다 높음
    3) 구조 확인: 다이버전스 발생 후 첫 HH(higher high) 형성 시 진입 트리거

청산:
    - 직전 스윙저점 하향 이탈 OR 보유 ``max_hold`` 봉 초과 OR 익절 ``tp_pct``

스윙은 ``backtest.engine.swing.detect_swings`` 사용. 룩어헤드 회피 위해
swing 라벨은 ``shift(k)``로 k봉 지연 후 사용 (확정 시점 = t+k).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engine.swing import detect_swings

NAME = "reversal_bottom"

DEFAULT_PARAMS = {
    "lookback_high": 200,
    "drawdown_min": -0.60,
    "rsi_n": 14,
    "div_lookback": 60,
    "swing_k": 3,
    "max_hold": 60,
    "tp_pct": 0.50,
    "sl_pct": -0.15,
    "btc_filter": True,
    "btc_filter_ema": 200,
}


def _rsi(close: pd.Series, n: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def signal(df: pd.DataFrame, params: dict) -> pd.Series:
    p = {**DEFAULT_PARAMS, **params}
    close = df["close"].astype("float64")
    low = df["low"].astype("float64")
    high = df["high"].astype("float64")

    lb_high = int(p["lookback_high"])
    div_lb = int(p["div_lookback"])
    k = int(p["swing_k"])

    # 1) 깊은 낙폭
    rolling_high = high.rolling(lb_high, min_periods=lb_high).max()
    drawdown = close / rolling_high - 1.0
    deep_dd = drawdown <= float(p["drawdown_min"])

    # 2) 다이버전스: 최근 div_lb 봉 동안의 최저 종가가 close[t]이면서,
    #    그 시점의 RSI가 직전 저점 RSI보다 높은가 → 단순 근사:
    #    close가 div_lb 신저점 + RSI는 div_lb 신저점이 아님
    rsi = _rsi(close, int(p["rsi_n"]))
    new_low_price = close == close.rolling(div_lb, min_periods=div_lb).min()
    new_low_rsi = rsi == rsi.rolling(div_lb, min_periods=div_lb).min()
    bull_div = new_low_price & ~new_low_rsi

    # 다이버전스가 최근 div_lb 봉 이내에 발생했는지 (지속 윈도우)
    div_recent = bull_div.shift(1).rolling(div_lb, min_periods=1).max().fillna(0).astype(bool)

    # 3) 구조 확인: swing high가 확정되고, 그 swing high의 가격이 직전 swing high보다 높음 (HH).
    swings = detect_swings(df, k=k)
    sh_raw = swings["swing_high"]
    # 룩어헤드 회피: swing high가 t에 라벨됐어도 t+k까지 정보 필요 → k봉 지연
    sh_confirmed = sh_raw.shift(k).fillna(False)

    # 마지막 confirmed swing high가 그 직전 swing high보다 높은 시점만 1.
    # 벡터화: high를 confirmed swing high인 시점에서만 추출 후 ffill 비교.
    sh_high_value = high.where(sh_confirmed)
    last_sh = sh_high_value.ffill()
    prev_sh = sh_high_value.shift(1).ffill()
    hh = (last_sh > prev_sh) & sh_confirmed

    # HH가 최근 30봉 이내에 발생했는지
    hh_recent = hh.rolling(30, min_periods=1).max().fillna(0).astype(bool)

    enter = (deep_dd & div_recent & hh_recent).fillna(False)

    if bool(p.get("btc_filter", False)):
        from backtest.engine.btc_filter import btc_uptrend_mask
        mask = btc_uptrend_mask(df, ema_n=int(p["btc_filter_ema"]))
        enter = enter & pd.Series(mask, index=df.index)

    # 청산: 단순화 — 보유 max_hold 또는 손익률 ±tp/sl
    n = len(df)
    state = np.zeros(n, dtype=np.int8)
    e = enter.to_numpy()
    cl = close.to_numpy()
    max_hold = int(p["max_hold"])
    tp = float(p["tp_pct"])
    sl = float(p["sl_pct"])
    cur = 0
    held = 0
    entry_px = np.nan
    for i in range(n):
        if cur == 1:
            held += 1
            ret = cl[i] / entry_px - 1.0
            if ret >= tp or ret <= sl or held >= max_hold:
                cur = 0
                held = 0
                entry_px = np.nan
        if cur == 0 and e[i]:
            cur = 1
            held = 0
            entry_px = cl[i]
        state[i] = cur

    return pd.Series(state, index=df.index, dtype="int8")
