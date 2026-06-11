"""ma_touch 시그널 — full / partial 두 종류.

룰 (사용자 신조 "시작 전 무조건 찍고 간다"):
  정배열 (B):   MA10 > MA20  AND  close > MA20
  slope+:       slope_MA10 > 0  AND  slope_MA20 > 0
  임계:         K × range_7  (range_7 = 최근 7봉 (high − low) 평균, 절대값)
  터치 (롱 부등식): (low − MA10 ≤ 임계)  OR  (low − MA20 ≤ 임계)
                  → low 가 MA 아래는 무한 OK (가로지름), MA 위로는 임계 안만 OK
  통과 = 정배열 + slope+ + 터치
"""
from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd

K_DIST_THRESHOLD = 0.2     # 임계 = K × range_7 (절대값)
N_ATR_WINDOW = 7           # range_7 = 최근 7봉 (high − low) 평균
ANGLE_MEDIUM_DEG = 15.0
ANGLE_STRONG_DEG = 30.0
PARTIAL_CONSEC_BARS = 3


def _angle_label(angle_deg: float) -> str:
    if pd.isna(angle_deg):
        return "n/a"
    a = abs(angle_deg)
    if a >= ANGLE_STRONG_DEG:
        return "strong"
    if a >= ANGLE_MEDIUM_DEG:
        return "medium"
    return "weak"


def _compute_range_threshold(df_tf: pd.DataFrame) -> float:
    """K × 최근 N_ATR_WINDOW 봉 평균 봉폭 (절대값)."""
    if len(df_tf) < 1:
        return float("nan")
    rng = (df_tf["high"] - df_tf["low"]).tail(N_ATR_WINDOW).mean()
    if pd.isna(rng):
        return float("nan")
    return float(K_DIST_THRESHOLD * rng)


def signal_ma_touch_full(df_tf: pd.DataFrame, today_low: float = None) -> Tuple[bool, dict]:
    """FULL 시그널 — MA10 + MA20 둘 다 있는 TF.

    today_low: 오늘 일봉의 low. None 이면 df_tf 마지막 봉의 low (1D 평가용).
    1W/1M/1Q/1Y 평가 시 TF 마지막 봉 (큰 기간 안 모든 일봉 low 중 최저) 가 아니라
    **현재 시점 일봉 low** 으로 터치 게이트 평가 → 추격 자리 자동 cut.
    """
    if len(df_tf) < 1:
        return False, {}

    last = df_tf.iloc[-1]
    close = last["close"]
    low = today_low if today_low is not None else last["low"]
    ma10 = last["ma10"]
    ma20 = last["ma20"]
    slope10 = last["slope_pct_ma10"]
    slope20 = last["slope_pct_ma20"]
    angle20 = last.get("angle_ma20_deg", float("nan"))

    if any(pd.isna(x) for x in (low, ma10, ma20, slope10, slope20)):
        return False, {}

    th = _compute_range_threshold(df_tf)
    if pd.isna(th):
        return False, {}

    gate_align = (ma10 > ma20) and (close > ma20)
    gate_slope = (slope10 > 0) and (slope20 > 0)
    gate_touch = ((low - ma10) <= th) or ((low - ma20) <= th)

    passed = bool(gate_align and gate_slope and gate_touch)
    return passed, {"angle_strength_label": _angle_label(angle20), "dist_threshold_abs": th}


def signal_ma_touch_partial(df_tf: pd.DataFrame, today_low: float = None) -> Tuple[bool, dict]:
    """PARTIAL 시그널 — MA10 만 있는 TF (신생주).

    today_low: 오늘 일봉의 low. None 이면 df_tf 마지막 봉의 low.

    게이트:
      1. close > ma10
      2. slope_ma10 > 0
      3. today_low − ma10 ≤ 임계 (롱 부등식)
      4. close > ma10 가 최근 PARTIAL_CONSEC_BARS 봉 연속 유지
    """
    if len(df_tf) < PARTIAL_CONSEC_BARS:
        return False, {}

    last = df_tf.iloc[-1]
    close = last["close"]
    low = today_low if today_low is not None else last["low"]
    ma10 = last["ma10"]
    slope10 = last["slope_pct_ma10"]
    angle10 = last.get("angle_ma10_deg", float("nan"))

    if any(pd.isna(x) for x in (low, ma10, slope10)):
        return False, {}

    th = _compute_range_threshold(df_tf)
    if pd.isna(th):
        return False, {}

    gate_above = close > ma10
    gate_slope = slope10 > 0
    gate_touch = (low - ma10) <= th

    tail = df_tf.tail(PARTIAL_CONSEC_BARS)
    gate_consec = bool((tail["close"] > tail["ma10"]).all())

    passed = bool(gate_above and gate_slope and gate_touch and gate_consec)
    return passed, {"angle_strength_label": _angle_label(angle10), "dist_threshold_abs": th}


def evaluate_tf(df_tf: pd.DataFrame, kind: str, today_low: float = None) -> Tuple[bool, bool, dict]:
    """단일 TF 평가 dispatch — kind 에 따라 full / partial / skip.

    today_low: 오늘 일봉 low. 모든 TF 평가에서 동일하게 사용 (추격 자리 자동 cut).

    반환: (passed_full, passed_partial, extras). skip 이면 (False, False, {}).
    """
    if kind == "full":
        passed, extras = signal_ma_touch_full(df_tf, today_low=today_low)
        return passed, False, extras
    if kind == "partial":
        passed, extras = signal_ma_touch_partial(df_tf, today_low=today_low)
        return False, passed, extras
    return False, False, {}
