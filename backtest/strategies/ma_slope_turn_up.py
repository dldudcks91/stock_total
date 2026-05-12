"""주봉 MA10/MA20 기울기 전환 진입 (long-only, 1w 권장).

배경: 하락 추세 중에는 기울기의 변화량(2차 미분)만 보면 -3 → -1 같은 구간에서도
변화량이 +가 되어 매수 신호처럼 보임. 그래서 (a) 기울기 자체와 (b) 기울기의 변화량,
둘 다 동시에 양수가 되는 시점만 진입으로 잡는다.

진입 (여섯 모두 충족):
    1) 사전 하락세(단기): 최근 ``down_lookback`` 봉 내 slope10 < 0 AND slope20 < 0 시점 존재
    2) 기울기 양: slope10 > 0 AND slope20 > 0  (실제 기울기/각도)
    3) 가속 양: accel10 > 0 AND accel20 > 0    (기울기의 변화량 = slope.diff())
    4) 장기 낙폭 (A): close / rolling_max(close, long_dd_lookback) - 1 <= long_dd_min
    5) 장기 추세 음 (B): 최근 long_slope_lookback 봉 중 장기 MA 기울기가 음인 비율
       >= long_slope_neg_ratio
    6) 가격이 ma_slow 위: close > MA(ma_slow). 20선이 양 전환해도 가격이 그 아래면
       "MA가 가격을 따라 올라오는 중"이라 가짜 출발 위험. 가격이 MA 위에 있을 때만 진입.
    7) 안착 (settle): 진입 직전 ``settle_lookback`` 봉 동안 close가 MA_slow 아래로 내려간 적 없고
       (이탈 없음), 그 윈도우 안에 적어도 한 봉은 ``low/MA_slow - 1 <= pullback_thr`` 인 봉 존재
       (조정/눌림목). → "MA20 돌파 후 조정 → 이탈 없이 재상승" 패턴.

청산:
    - slope10 < 0 OR slope20 < 0 으로 전환되면 청산
    - (옵션) ``max_hold`` 봉 초과 시 강제 청산

slope 정의: ``MA.diff(slope_period)`` — slope_period 봉간 변화량. 부호만 쓰므로 가격
스케일 정규화는 불필요. 엔진이 t -> t+1 체결을 처리하므로 raw 시그널만 반환.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NAME = "ma_slope_turn_up"

DEFAULT_PARAMS = {
    "ma_fast": 10,
    "ma_slow": 20,
    "slope_period": 1,            # MA.diff(slope_period). 1 = 직전 봉 대비
    "down_lookback": 8,           # 단기: 직전 N봉 내 두 기울기 모두 음이었던 시점 존재
    "max_hold": 0,                # 0 이면 미사용
    # --- 장기 하락 추세 필터 ---
    "long_dd_lookback": 100,      # A: 낙폭 측정 윈도우 (주봉 100 ≈ 2년)
    "long_dd_min": -0.30,         # A: -30% 이상 빠진 상태여야 통과
    "long_ma": 60,                # B: 장기 MA 길이 (60주 ≈ 1년)
    "long_slope_lookback": 26,    # B: 기울기 부호 비율 측정 윈도우 (반년)
    "long_slope_neg_ratio": 0.70, # B: 그 윈도우에서 음(slope<0) 비율 70% 이상
    # --- 안착 (MA20 돌파 → 조정 → 이탈 없이 재상승) ---
    "settle_lookback": 4,         # 직전 N봉 동안 close가 MA_slow 아래로 안 내려감
    "pullback_thr": 0.03,         # 그 N봉 중 적어도 1봉은 low/MA_slow-1 <= 3% (조정)
    "slope_turn_before_settle": True,  # 안착 4봉 시작 시점에 이미 slope_slow 양이어야
                                       # (떡상 봉이 안착 내부에서 slope 끌어올리는 가짜 거름)
    # --- U자 곡률 (부드럽게 말려올라옴) ---
    "curl_window": 8,            # 최근 N봉 MA_slow에 2차 다항식 fit
    "curl_a_min": 0.0,           # 2차 계수 a > curl_a_min (U자 = a>0)
    "curl_r2_min": 0.90,         # R² 임계 (fit이 매끄러운 정도)
    "curl_accel_streak": 6,      # 최근 K봉 accel_slow > 0 연속 (jerk 작음 보조)
    "use_curl": False,           # 곡률 조건 사용 여부 (default OFF, 자산별 ON 결정)
}


def signal(df: pd.DataFrame, params: dict) -> pd.Series:
    p = {**DEFAULT_PARAMS, **params}
    fast = int(p["ma_fast"])
    slow = int(p["ma_slow"])
    sp = int(p["slope_period"])
    dlb = int(p["down_lookback"])
    max_hold = int(p["max_hold"])
    dd_lb = int(p["long_dd_lookback"])
    dd_min = float(p["long_dd_min"])
    long_ma_n = int(p["long_ma"])
    long_slb = int(p["long_slope_lookback"])
    long_neg_ratio = float(p["long_slope_neg_ratio"])
    settle_lb = int(p["settle_lookback"])
    pullback_thr = float(p["pullback_thr"])
    slope_turn_before = bool(p.get("slope_turn_before_settle", False))
    use_curl = bool(p.get("use_curl", False))
    curl_window = int(p.get("curl_window", 8))
    curl_a_min = float(p.get("curl_a_min", 0.0))
    curl_r2_min = float(p.get("curl_r2_min", 0.90))
    curl_accel_streak = int(p.get("curl_accel_streak", 6))

    if fast <= 0 or slow <= 0 or fast >= slow:
        raise ValueError(f"require 0 < ma_fast < ma_slow, got {fast}/{slow}")
    if sp <= 0:
        raise ValueError(f"slope_period must be > 0, got {sp}")
    if dlb <= 0:
        raise ValueError(f"down_lookback must be > 0, got {dlb}")
    if dd_lb <= 0 or long_ma_n <= 0 or long_slb <= 0:
        raise ValueError("long_dd_lookback / long_ma / long_slope_lookback must be > 0")
    if not (0.0 <= long_neg_ratio <= 1.0):
        raise ValueError(f"long_slope_neg_ratio must be in [0,1], got {long_neg_ratio}")
    if settle_lb <= 0:
        raise ValueError(f"settle_lookback must be > 0, got {settle_lb}")
    if pullback_thr < 0:
        raise ValueError(f"pullback_thr must be >= 0, got {pullback_thr}")

    close = df["close"].astype("float64")
    low = df["low"].astype("float64")
    ma_f = close.rolling(fast, min_periods=fast).mean()
    ma_s = close.rolling(slow, min_periods=slow).mean()

    slope_f = ma_f.diff(sp)
    slope_s = ma_s.diff(sp)
    accel_f = slope_f.diff()
    accel_s = slope_s.diff()

    # (2) 두 MA 기울기 모두 양수
    slope_pos = (slope_f > 0) & (slope_s > 0)
    # (3) 두 MA 기울기 변화량(가속도) 모두 양수
    accel_pos = (accel_f > 0) & (accel_s > 0)

    # (1) 사전 하락세: 직전 봉부터 down_lookback 봉 전까지 (shift(1)로 현재봉 제외)
    #     안에 slope_f < 0 AND slope_s < 0 인 시점이 한 번이라도 있었어야 함
    both_down = (slope_f < 0) & (slope_s < 0)
    prior_down = (
        both_down.shift(1)
        .rolling(dlb, min_periods=1)
        .max()
        .fillna(0)
        .astype(bool)
    )

    # (A) 장기 낙폭: 최근 dd_lb 봉 고점 대비 -dd_min 이상 빠진 상태
    rolling_high = close.rolling(dd_lb, min_periods=dd_lb).max()
    drawdown = close / rolling_high - 1.0
    long_deep_dd = drawdown <= dd_min

    # (B) 장기 MA 기울기 음 비율: 최근 long_slb 봉 중 slope_long < 0 비율 >= long_neg_ratio
    ma_long = close.rolling(long_ma_n, min_periods=long_ma_n).mean()
    slope_long = ma_long.diff()
    neg_share = (slope_long < 0).rolling(long_slb, min_periods=long_slb).mean()
    long_down_trend = neg_share >= long_neg_ratio

    # (6) 가격이 MA_slow(20선) 위에 있을 것
    price_above_slow = close > ma_s

    # (7) 안착: 진입 직전 settle_lb 봉 동안 close가 MA_slow 위에 머무름 (이탈 없음)
    #     + 그 N봉 안에 한 봉은 low/MA_slow - 1 <= pullback_thr (조정/근접)
    above_seq = (close >= ma_s)
    no_breakdown = (
        above_seq.rolling(settle_lb, min_periods=settle_lb)
        .min().fillna(0).astype(bool)
    )
    near_ma = (low / ma_s - 1.0) <= pullback_thr
    had_pullback = (
        near_ma.rolling(settle_lb, min_periods=settle_lb)
        .max().fillna(0).astype(bool)
    )

    # (8) 안착 시작 시점에 이미 slope_slow가 양이어야 (떡상이 안착 내부에 있으면 거름)
    if slope_turn_before:
        slope_pos_at_settle_start = (slope_s > 0).shift(settle_lb).fillna(False)
    else:
        slope_pos_at_settle_start = pd.Series(True, index=close.index)

    # (9) U자 곡률: 최근 curl_window 봉 MA에 2차 다항식 fit → a > a_min AND R² > r2_min
    #     MA_slow(20) 필수, MA_fast(10)도 함께 검사 (사용자 의도: "MA10/20 둘 다 부드럽게 말아짐")
    def _curl_ok(series: pd.Series) -> pd.Series:
        arr = series.to_numpy()
        n_bars = len(arr)
        ok = np.zeros(n_bars, dtype=bool)
        t = np.arange(curl_window, dtype=float)
        for i in range(curl_window - 1, n_bars):
            w = arr[i - curl_window + 1 : i + 1]
            if np.isnan(w).any():
                continue
            try:
                coef = np.polyfit(t, w, 2)
            except Exception:
                continue
            a = coef[0]
            if a <= curl_a_min:
                continue
            y_hat = np.polyval(coef, t)
            ss_res = ((w - y_hat) ** 2).sum()
            ss_tot = ((w - w.mean()) ** 2).sum()
            if ss_tot <= 0:
                continue
            if 1.0 - ss_res / ss_tot >= curl_r2_min:
                ok[i] = True
        return pd.Series(ok, index=series.index)

    if use_curl:
        curl_slow = _curl_ok(ma_s)
        curl_fast = _curl_ok(ma_f)
        accel_streak_ok = (
            (accel_s > 0)
            .rolling(curl_accel_streak, min_periods=curl_accel_streak)
            .min()
            .fillna(0).astype(bool)
        )
        curl_cond = curl_slow & curl_fast & accel_streak_ok
    else:
        curl_cond = pd.Series(True, index=close.index)

    enter = (
        slope_pos & accel_pos & prior_down & long_deep_dd & long_down_trend
        & price_above_slow & no_breakdown & had_pullback
        & slope_pos_at_settle_start & curl_cond
    ).fillna(False)

    # 청산 조건: slope_f < 0 OR slope_s < 0
    exit_cond = ((slope_f < 0) | (slope_s < 0)).fillna(False)

    # stateful 보유: 진입 후 청산조건 만족 또는 max_hold 초과 시 청산
    n = len(df)
    state = np.zeros(n, dtype=np.int8)
    e = enter.to_numpy()
    x = exit_cond.to_numpy()
    cur = 0
    held = 0
    for i in range(n):
        if cur == 1:
            held += 1
            if x[i] or (max_hold > 0 and held >= max_hold):
                cur = 0
                held = 0
        if cur == 0 and e[i]:
            cur = 1
            held = 0
        state[i] = cur

    return pd.Series(state, index=df.index, dtype="int8")
