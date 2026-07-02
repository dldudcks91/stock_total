"""G3 (그랜빌 3법칙) = ma_touch — 지지·눌림 catch.

정배열(MA10 > MA20 AND close > MA20) + slope 양수 + 오늘 일봉 low 가 MA10/MA20
에 근접(터치 임계 이내) 한 자리. 사용자 신조 "찍고 간다" 가 적용되는 유일한
자리 — 이미 가속한 종목을 이 안에 끌어들이지 않는다.

파이프라인: ``dashboards/_precompute.py`` 에서 호출, ``_recs.parquet.gate_pass``
= 그리드 G3 셀.

이 파일 안의 심볼 (한 자리 룰인데 심볼이 여럿인 이유 = 신생주 대응):
  판정 함수 (2개)
    - ``signal_ma_touch_full``    : MA20 만들 수 있는 종목 (≥20봉)
    - ``signal_ma_touch_partial`` : MA10 만 있는 신생주 fallback (<20봉)
  디스패치 (1개)
    - ``evaluate_tf``             : kind ∈ {"full", "partial"} 에 따라 위 둘 중 선택
  파라미터 상수 (5개)
    - ``K_DIST_THRESHOLD``, ``N_ATR_WINDOW``, ``PARTIAL_CONSEC_BARS``,
      ``ANGLE_MEDIUM_DEG``, ``ANGLE_STRONG_DEG``
  내부 헬퍼 (2개)
    - ``_angle_label``, ``_compute_range_threshold``
"""
from __future__ import annotations

from typing import Tuple

import pandas as pd

# 룰 파라미터
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


def _compute_range_threshold(df_daily: pd.DataFrame) -> float:
    """K × **일봉** 최근 N_ATR_WINDOW 봉 평균 봉폭 (절대값).

    df_daily 는 평가 자산의 일봉 dataframe. 모든 TF (1D/1W/1M/1Q/1Y) 평가에서
    동일하게 이 임계를 사용 — TF 별 봉폭이 아니라 일봉 변동폭으로 통일.
    """
    if len(df_daily) < 1:
        return float("nan")
    rng = (df_daily["high"] - df_daily["low"]).tail(N_ATR_WINDOW).mean()
    if pd.isna(rng):
        return float("nan")
    return float(K_DIST_THRESHOLD * rng)


def signal_ma_touch_full(df_tf: pd.DataFrame, df_daily: pd.DataFrame,
                         today_low: float = None) -> Tuple[bool, dict]:
    """FULL 시그널 — MA10 + MA20 둘 다 있는 TF.

    df_daily: 일봉 dataframe. range_7 임계 계산에 사용 (모든 TF 공통).
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

    th = _compute_range_threshold(df_daily)
    if pd.isna(th):
        return False, {}

    gate_align = (ma10 > ma20) and (close > ma20)
    gate_slope = (slope10 > 0) and (slope20 > 0)
    gate_touch = (abs(low - ma10) <= th) or (abs(low - ma20) <= th)

    passed = bool(gate_align and gate_slope and gate_touch)
    return passed, {"angle_strength_label": _angle_label(angle20), "dist_threshold_abs": th}


def signal_ma_touch_partial(df_tf: pd.DataFrame, df_daily: pd.DataFrame,
                            today_low: float = None) -> Tuple[bool, dict]:
    """PARTIAL 시그널 — MA10 만 있는 TF (신생주).

    df_daily: 일봉 dataframe. range_7 임계 계산에 사용 (모든 TF 공통).
    today_low: 오늘 일봉의 low. None 이면 df_tf 마지막 봉의 low.

    게이트:
      1. close > ma10
      2. slope_ma10 > 0
      3. |today_low − ma10| ≤ 임계 (양방향 절대값)
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

    th = _compute_range_threshold(df_daily)
    if pd.isna(th):
        return False, {}

    gate_above = close > ma10
    gate_slope = slope10 > 0
    gate_touch = abs(low - ma10) <= th

    tail = df_tf.tail(PARTIAL_CONSEC_BARS)
    gate_consec = bool((tail["close"] > tail["ma10"]).all())

    passed = bool(gate_above and gate_slope and gate_touch and gate_consec)
    return passed, {"angle_strength_label": _angle_label(angle10), "dist_threshold_abs": th}


def evaluate_tf(df_tf: pd.DataFrame, df_daily: pd.DataFrame, kind: str,
                today_low: float = None) -> Tuple[bool, bool, dict]:
    """단일 TF 평가 dispatch — kind 에 따라 full / partial / skip.

    df_daily: 일봉 dataframe. range_7 임계 계산에 사용 (모든 TF 공통).
    today_low: 오늘 일봉 low. 모든 TF 평가에서 동일하게 사용 (추격 자리 자동 cut).

    반환: (passed_full, passed_partial, extras). skip 이면 (False, False, {}).
    """
    if kind == "full":
        passed, extras = signal_ma_touch_full(df_tf, df_daily, today_low=today_low)
        return passed, False, extras
    if kind == "partial":
        passed, extras = signal_ma_touch_partial(df_tf, df_daily, today_low=today_low)
        return False, passed, extras
    return False, False, {}
