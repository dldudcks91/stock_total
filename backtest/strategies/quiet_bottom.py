"""'조용한 바닥' — long-only 주봉 추천 시그널 (자동매매 X, 추천용).

대시보드 라벨: '조용한 바닥'
영문 코드명: quiet_bottom

== 사용자 직관 ==
차트에서 본 직감: 종목이 한참 흘러내려 푹 잠긴 후, 중간중간 'MA20에 박치기 → 다시 추락'하는
가짜 출발이 없이, 조용히 횡보/바닥 다지기를 거치고 처음으로 부드럽게 올라오는 패턴.

== 진입 조건 (현재 구현 — 1차) ==
    [기본 신호]
    a) close > MA20
    b) slope10 > 0 AND slope20 > 0     (이평선 기울기 둘 다 양수)
    c) accel10 > 0 AND accel20 > 0     (가속도 둘 다 양수)

    [핵심 필터]
    1) avg_dd_104w <= -0.45            직전 2년(104주) 평균 고점 대비 낙폭 ≤ -45%
                                       → "장기 침잠" 보장
    2) path_R2_52w <= 0.50             직전 1년 log(close) 선형 fit R² ≤ 0.50
                                       → 직선 추세 거름 (= 횡보·바닥 다지기 패턴만 통과)
    3) ret_4w_total <= +0.60           직전 4주 누적 수익률 ≤ +60%
                                       → V-spike 떡상 직후 진입 거름

== 미구현 (사용자가 다음에 검증하고 싶다 한 보강 지표) ==
    [slope 시계열 자체에 fit — "음→양 부드러운 전환" 정량화]
    (1) min(slope20[t-11:t+1]) < 0     12주 안에 음수였음 (한참 떨어졌었음)
    (2) slope20[t] > 0                 현재 양 전환 완료
    (3) β(slope linear fit) > 0        평균적으로 증가 추세
    (4) R²(slope linear fit) ≥ 0.70   매끄러운 증가 (점프/박치기 없음)
    (5) 박치기 카운트 cross_up_78w ≤ 2  최근 78주 안 MA20 위로 박치기 ≤ 2회

  → path_R²(가격 직선 여부) 만으로는 CHZ 같은 "박스권 안 박치기 7회" 케이스를 거르지 못함.
    slope 시계열의 R² (β/R²/min/current 묶음) 가 더 정확히 사용자 직관 잡음 (검증 완료, 코드 미반영).

== 자산별 청산 룰 (시뮬레이션 결과) ==
  추천용 — 자동매매 아님. 백테스트 best practice 참고:
    crypto: hold_13w + trailing_pct 0.15 + cut_1w_neg=True   (Sharpe 0.69, n=31, 3y)
    kr    : hold_52w + trailing_pct 0.20 + take_profit 0.30  (Sharpe 5.84, n=584, 6y; OOS 4.29)
    us    : hold_52w + trailing_pct 0.20 + take_profit 0.30  (Sharpe 3.56, n=303, 6y; OOS 4.88)

  주의: Crypto는 본 조건과 안 맞음 (베어가 직선 하락이라 path_R² 통과 안 됨, 단순 일봉 변환도 실패).
  추천 자산: KR / US 우선.

== 엔진 호환 ==
  - 룩어헤드 금지: 시그널은 t 시점, 체결 t+1 (엔진이 처리)
  - 반환: pd.Series of int8 in {0, 1} — 0 = 신호 없음, 1 = 진입 신호
  - 자세한 자산별 백테스트 결과: backtest/strategies/QUIET_BOTTOM.md
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NAME = "quiet_bottom"
LABEL_KR = "조용한 바닥"

DEFAULT_PARAMS = {
    "ma_fast": 10,
    "ma_slow": 20,
    "slope_period": 1,
    # 핵심 3 조건
    "dd_lookback_104w": 104,
    "dd_avg_max": -0.45,
    "path_window_52w": 52,
    "path_r2_max": 0.50,
    "recent_window_4w": 4,
    "recent_ret_max": 0.60,
}


def _rolling_path_r2(close: pd.Series, window: int) -> pd.Series:
    """log(close) 시계열에 선형 fit → R² (각 위치 t는 [t-window+1 ... t] 윈도우)."""
    log_p = np.log(close.astype("float64"))
    arr = log_p.to_numpy()
    n = len(arr)
    out = np.full(n, np.nan)
    t = np.arange(window, dtype=float)
    t_centered = t - t.mean()
    denom = (t_centered ** 2).sum()
    for i in range(window - 1, n):
        y = arr[i - window + 1 : i + 1]
        if np.isnan(y).any():
            continue
        y_mean = y.mean()
        b = ((t_centered) * (y - y_mean)).sum() / denom
        a = y_mean - b * t.mean()
        y_hat = a + b * t
        ss_res = ((y - y_hat) ** 2).sum()
        ss_tot = ((y - y_mean) ** 2).sum()
        if ss_tot > 0:
            out[i] = 1.0 - ss_res / ss_tot
    return pd.Series(out, index=close.index)


def signal(df: pd.DataFrame, params: dict) -> pd.Series:
    p = {**DEFAULT_PARAMS, **params}
    fast = int(p["ma_fast"])
    slow = int(p["ma_slow"])
    sp = int(p["slope_period"])
    dd_lb = int(p["dd_lookback_104w"])
    dd_max = float(p["dd_avg_max"])
    path_w = int(p["path_window_52w"])
    r2_max = float(p["path_r2_max"])
    rec_w = int(p["recent_window_4w"])
    rec_max = float(p["recent_ret_max"])

    if fast <= 0 or slow <= 0 or fast >= slow:
        raise ValueError(f"require 0 < ma_fast < ma_slow, got {fast}/{slow}")

    close = df["close"].astype("float64")
    ma_f = close.rolling(fast, min_periods=fast).mean()
    ma_s = close.rolling(slow, min_periods=slow).mean()

    slope_f = ma_f.diff(sp)
    slope_s = ma_s.diff(sp)
    accel_f = slope_f.diff()
    accel_s = slope_s.diff()

    # 기본 신호
    slope_pos = (slope_f > 0) & (slope_s > 0)
    accel_pos = (accel_f > 0) & (accel_s > 0)
    price_above_slow = close > ma_s

    # 핵심 3
    rolling_max = close.rolling(dd_lb, min_periods=dd_lb).max()
    dd = close / rolling_max - 1.0
    avg_dd = dd.rolling(dd_lb, min_periods=dd_lb).mean()
    deep_dive = avg_dd <= dd_max

    path_r2 = _rolling_path_r2(close, path_w)
    not_linear = path_r2 <= r2_max

    recent_ret = close / close.shift(rec_w) - 1.0
    no_vspike = recent_ret <= rec_max

    enter = (
        slope_pos & accel_pos & price_above_slow
        & deep_dive & not_linear & no_vspike
    ).fillna(False)

    # 추천용 raw 시그널 (0 / 1) — 진입 후 보유 상태 추적은 simulator 또는 대시보드에서.
    return enter.astype("int8")
