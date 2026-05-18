"""quiet_bottom v2 — QUIET_BOTTOM.md 의 "미구현" 섹션 보강 지표 추가.

기존 quiet_bottom 6 조건 + 보강 5 조건 (slope20 시계열 linear fit + 박치기 카운트).

추가 조건 (옵션화, params 로 on/off):
  (1) min(slope20[t-11:t+1]) < 0     12주 안에 음수였음 (한참 떨어졌었음)
  (2) slope20[t] > 0                 현재 양 전환 완료
  (3) β(slope20 linear fit) > 0      평균적으로 증가 추세
  (4) R²(slope20 linear fit) ≥ 0.70  매끄러운 증가
  (5) cross_up_78w ≤ 2               박치기 카운트 (close 가 MA20 하 -> 상 교차 횟수)

  → CHZ 박스권 안 박치기 7회 / BANANAS31 들락날락 같은 케이스 제거 목적.

params 키:
  use_slope_r2_filter   : bool, default True
  slope_fit_window      : int, default 12 (주)
  slope_r2_min          : float, default 0.70
  use_crossup_filter    : bool, default True
  crossup_window        : int, default 78 (주)
  crossup_max           : int, default 2

기존 quiet_bottom 의 모든 키도 지원.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NAME = "quiet_bottom_v2"
LABEL_KR = "조용한 바닥 v2"

DEFAULT_PARAMS = {
    # 기존 quiet_bottom 동일
    "ma_fast": 10,
    "ma_slow": 20,
    "slope_period": 1,
    "dd_lookback_104w": 104,
    "dd_avg_max": -0.45,
    "path_window_52w": 52,
    "path_r2_max": 0.50,
    "recent_window_4w": 4,
    "recent_ret_max": 0.60,
    # 보강
    "use_slope_r2_filter": True,
    "slope_fit_window": 12,
    "slope_r2_min": 0.70,
    "use_crossup_filter": True,
    "crossup_window": 78,
    "crossup_max": 2,
}


def _rolling_path_r2(close: pd.Series, window: int) -> pd.Series:
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


def _rolling_linear_fit(series: pd.Series, window: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """각 위치 t 에 대해 [t-window+1 ... t] 윈도우의 (beta, R², min) 반환."""
    arr = series.to_numpy(dtype="float64")
    n = len(arr)
    beta = np.full(n, np.nan)
    r2 = np.full(n, np.nan)
    minv = np.full(n, np.nan)
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
        beta[i] = b
        r2[i] = (1.0 - ss_res / ss_tot) if ss_tot > 0 else np.nan
        minv[i] = float(y.min())
    return (pd.Series(beta, index=series.index),
            pd.Series(r2, index=series.index),
            pd.Series(minv, index=series.index))


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

    # === 보강 1: slope20 시계열 linear fit ===
    if bool(p["use_slope_r2_filter"]):
        sw = int(p["slope_fit_window"])
        r2_min = float(p["slope_r2_min"])
        beta_s, r2_s, min_s = _rolling_linear_fit(slope_s.fillna(0.0), sw)
        # 조건 (1) min(slope20[t-sw+1:t+1]) < 0
        cond_had_neg = min_s < 0
        # 조건 (2) slope20[t] > 0  → 이미 slope_pos 에 포함, 중복 보장
        # 조건 (3) β > 0
        cond_beta = beta_s > 0
        # 조건 (4) R² >= r2_min
        cond_r2 = r2_s >= r2_min
        slope_filter = (cond_had_neg & cond_beta & cond_r2).fillna(False)
        enter = enter & slope_filter

    # === 보강 5: 박치기 카운트 ===
    if bool(p["use_crossup_filter"]):
        cw = int(p["crossup_window"])
        cmax = int(p["crossup_max"])
        # close > MA20 (오늘) AND close.shift(1) <= MA20.shift(1) → cross-up 이벤트
        cu_event = (close > ma_s) & (close.shift(1) <= ma_s.shift(1))
        cu_event = cu_event.fillna(False).astype(int)
        # 직전 cw 봉 (오늘 이벤트 제외) cross-up 횟수
        prior_cu = cu_event.shift(1).rolling(cw, min_periods=1).sum().fillna(0)
        crossup_ok = prior_cu <= cmax
        enter = enter & crossup_ok

    return enter.astype("int8")
