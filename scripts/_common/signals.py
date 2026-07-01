"""그랜빌 매수 자리 시그널.

현재 구현:
  - ``signal_ma_touch_full`` / ``signal_ma_touch_partial``
      G2·G3 통합. 정배열(MA10>MA20, close>MA20) + slope+ + |low − MA| ≤ 임계.
      임계 = K × range_7 (range_7 = 일봉 최근 7봉 (high−low) 평균).
      pierce 여부는 아직 안 갈라놓음 — 파생 sign 으로 G2(low<MA) / G3(low≥MA) 분리 예정.
  - ``signal_g1``
      G1 = MA 시리즈 2차함수 적합. R² + a_pct + vertex_pos + MA 회복 + 가격 근접 조건.
      "MA 하락 종료 + 반등 시작" 자리. 골든크로스보다 몇 봉 늦지만 false breakout 필터.

미구현:
  - G4 (하락 MA 이격 반등) — 대시보드 그리드에 자리만 노출됨

사용자 신조: "시작 전 무조건 찍고 간다" — 추격 자리 (`trend_strong`) 는 후순위.
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

# G1 (그랜빌 1법칙) — MA 시리즈에 2차함수 적합해서 "하락 종료 + 반등 시작" 검출.
# docs/granville_quadratic_fit.md 룰 §4.
G1_N_WIN = 10              # 적합 윈도우 (봉 개수)
G1_R2_MIN = 0.85           # 적합 신뢰
G1_A_PCT_MIN = 0.10        # 곡률(a) 정규화 최소값 — U자 강도
G1_VERTEX_POS_MIN = 0.30   # vertex 상대 위치 하한 (윈도우 안 중반부터)
G1_VERTEX_POS_MAX = 0.85   # vertex 상대 위치 상한 (끝단은 "감속 중 하락" false positive)
G1_PX_VS_MA_MAX = 0.10     # |close − MA[-1]| / MA[-1] — 가격이 MA 근처


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


def signal_g1(df_tf: pd.DataFrame, ma_col: str = "ma20",
              n_win: int = G1_N_WIN) -> Tuple[bool, dict]:
    """G1 (그랜빌 1법칙) — MA 시리즈에 2차함수 적합.

    사이클 시작 = "MA 하락 종료 + 반등 시작". 골든크로스 시점보다 몇 봉 늦지만
    false breakout 필터링 강함.

    적합: 최근 n_win 봉의 ``ma_col`` 값에 ``y = a·x² + b·x + c`` 을 numpy.polyfit
    으로 적합. 정규화:
      - a_pct      = a / mean(MA) * 100  (곡률, % per bar²)
      - vertex_pos = (-b/2a) / (n_win-1) (윈도우 내 vertex 상대 위치, 0..1)
      - R²         = 1 − SS_res / SS_tot

    통과 조건 (docs/granville_quadratic_fit.md §4):
      1. R² ≥ G1_R2_MIN
      2. a_pct ≥ G1_A_PCT_MIN            (U자 곡률 충분)
      3. vertex_pos ∈ [G1_VERTEX_POS_MIN, G1_VERTEX_POS_MAX]
      4. MA[-1] > MA[-3]                 (실측 MA 회복 방향)
      5. |close − MA[-1]| / MA[-1] ≤ G1_PX_VS_MA_MAX

    반환: (passed, extras).
      extras = {a_pct, r2, vertex_pos, px_vs_ma, ma_last}
    """
    if len(df_tf) < n_win:
        return False, {}
    tail = df_tf.tail(n_win)
    ma = tail[ma_col].to_numpy(dtype=float)
    if np.isnan(ma).any() or float(np.mean(ma)) == 0.0:
        return False, {}

    x = np.arange(n_win, dtype=float)
    a, b, c = np.polyfit(x, ma, 2)
    y_hat = a * x * x + b * x + c
    ss_res = float(np.sum((ma - y_hat) ** 2))
    ss_tot = float(np.sum((ma - ma.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    ma_mean = float(ma.mean())
    a_pct = a / ma_mean * 100.0
    vertex_pos = (-b / (2.0 * a)) / (n_win - 1) if a != 0 else float("nan")

    ma_last = float(tail[ma_col].iloc[-1])
    ma_prev3 = float(tail[ma_col].iloc[-3])
    close = float(tail["close"].iloc[-1])
    px_vs_ma = abs(close - ma_last) / ma_last if ma_last > 0 else float("nan")

    passed = bool(
        r2 >= G1_R2_MIN
        and a_pct >= G1_A_PCT_MIN
        and G1_VERTEX_POS_MIN <= vertex_pos <= G1_VERTEX_POS_MAX
        and ma_last > ma_prev3
        and px_vs_ma <= G1_PX_VS_MA_MAX
    )
    extras = {
        "a_pct": float(a_pct),
        "r2": float(r2),
        "vertex_pos": float(vertex_pos) if not np.isnan(vertex_pos) else float("nan"),
        "px_vs_ma": float(px_vs_ma) if not np.isnan(px_vs_ma) else float("nan"),
        "ma_last": ma_last,
    }
    return passed, extras


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
