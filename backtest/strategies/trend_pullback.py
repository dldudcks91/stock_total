"""'추세 눌림목' (trend_pullback) — 정배열 추세 중 MA10/MA20 터치 후 반등 추천 시그널.

대시보드 라벨: '추세 눌림목'
영문 코드명: trend_pullback

== 사용자 직관 ==
정배열 추세가 유지되는 동안, 가격이 MA10 또는 MA20 근처까지 단기 조정 → 다시 양봉으로
반등하는 자리. 핵심은 **터치 전 하락 각도(가파르지 않게)** 와 **터치 후 반응(강한 양봉)**.

== 점수 공식 (0~100) ==
  추세 살아있음                                          0~25
    MA20 슬로프 양수                          +15
    종가 > 장기 추세선 (MA60)                  +10
  MA 터치 (최근 touch_lookback 봉 이내)                  0~15
    low <= MA10 또는 low <= MA20             +15
  터치 전 하락 각도 완만 (직전 5봉 close 평균 변화율)     0~20
    -1%/봉 이내 (완만)                         +20
    -2%/봉 이내 (보통)                         +10
    -3%/봉 초과 (가파름)                       0
  터치 후 반응 ★ 핵심 가중                              0~30
    당일 양봉 + 종가 회복 (close > MA10 or MA20)  +15
    거래량 >= 평균                              +10
    양봉 실체 비율 >= 0.5                       +5
  조정 깊이 적절 (직전 N봉 고점 대비 -5%~-20%)            +10
  ===
  합계 0~100

== signal ==
  score >= score_threshold (기본 60) 일 때 1.

== 엔진 호환 ==
  - 룩어헤드 금지: 모든 rolling 윈도우는 t 시점까지 데이터만 사용
  - 반환 signal: pd.Series of int8 in {0, 1}
  - 컴포넌트 디버깅: score_components(df, params) -> pd.DataFrame
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NAME = "trend_pullback"
LABEL_KR = "추세 눌림목"

DEFAULT_PARAMS = {
    "ma_fast": 10,
    "ma_slow": 20,
    "ma_long": 60,
    "touch_lookback": 3,           # 최근 N봉 내 MA 터치 인정
    "decline_lookback": 5,         # 터치 직전 N봉 하락 각도 측정
    "decline_th": [-0.01, -0.02, -0.03],  # 일평균 변화율 임계 (완만/보통/가파름)
    "decline_pts": [20, 10, 0],
    "react_volume_ma": 20,
    "react_body_ratio_min": 0.5,
    "depth_lookback": 20,          # 직전 고점 lookback
    "depth_min": -0.20,
    "depth_max": -0.05,
    "score_threshold": 80,
    "touch_pad_pct": 0.005,        # MA 근처 인정 padding (low <= MA*(1+pad))
}


def score_components(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    p = {**DEFAULT_PARAMS, **params}
    fast = int(p["ma_fast"])
    slow = int(p["ma_slow"])
    long_p = int(p["ma_long"])

    close = df["close"].astype("float64")
    open_ = df["open"].astype("float64")
    high = df["high"].astype("float64")
    low = df["low"].astype("float64")
    volume = df["volume"].astype("float64")

    ma_f = close.rolling(fast, min_periods=fast).mean()
    ma_s = close.rolling(slow, min_periods=slow).mean()
    ma_l = close.rolling(long_p, min_periods=long_p).mean()

    # 1) 추세 살아있음
    slope_pos = (ma_s.diff() > 0)
    above_long = (close > ma_l)
    trend_score = (slope_pos.astype(int) * 15) + (above_long.astype(int) * 10)
    trend_score = trend_score.astype("float64")

    # 2) MA 터치 (최근 touch_lookback 봉 내)
    pad = float(p["touch_pad_pct"])
    touch_now = (low <= ma_f * (1.0 + pad)) | (low <= ma_s * (1.0 + pad))
    touch_recent = touch_now.rolling(int(p["touch_lookback"]),
                                     min_periods=1).max().astype(bool)
    touch_score = touch_recent.astype(int) * 15
    touch_score = touch_score.astype("float64")

    # 3) 터치 전 하락 각도 (직전 decline_lookback 봉 close 평균 변화율)
    #    decline_lookback 동안의 close.pct_change().mean()
    dec_lb = int(p["decline_lookback"])
    ret1 = close.pct_change()
    # 터치 *이전* 구간을 보고 싶음 — 현재 봉 t, 평균은 [t-dec_lb+1 ... t]
    avg_ret_lb = ret1.rolling(dec_lb, min_periods=dec_lb).mean()
    decline_score = pd.Series(0.0, index=df.index)
    th = p["decline_th"]
    pts = p["decline_pts"]
    # 완만: -0.01 이상 (== avg_ret_lb >= -0.01)
    decline_score = np.where(avg_ret_lb >= th[0], pts[0],
                    np.where(avg_ret_lb >= th[1], pts[1],
                    np.where(avg_ret_lb >= th[2], pts[2], 0)))
    decline_score = pd.Series(decline_score, index=df.index, dtype="float64")
    # 단, 터치 자체가 없으면 의미 없음 — 터치 score 0 일 때는 decline 도 0 처리
    decline_score = decline_score.where(touch_recent, 0.0)

    # 4) 터치 후 반응 (현재 봉이 양봉 + 거래량 + 실체 비율)
    is_up = (close > open_) & (close.pct_change() > 0)
    recover = (close > ma_f) | (close > ma_s)
    react_a = (is_up & recover).astype(int) * 15
    vol_avg = volume.rolling(int(p["react_volume_ma"]),
                              min_periods=int(p["react_volume_ma"])).mean()
    react_b = ((volume >= vol_avg) & is_up).astype(int) * 10
    rng = (high - low).replace(0, np.nan)
    body = (close - open_).clip(lower=0)
    body_ratio = body / rng
    react_c = ((body_ratio >= p["react_body_ratio_min"]) & is_up).astype(int) * 5
    react_score = (react_a + react_b + react_c).astype("float64")
    # 터치 없으면 의미 없음
    react_score = react_score.where(touch_recent, 0.0)

    # 5) 조정 깊이 (직전 N봉 고점 대비)
    dep_lb = int(p["depth_lookback"])
    prev_high = high.rolling(dep_lb, min_periods=dep_lb).max().shift(1)
    drawdown = close / prev_high - 1.0
    depth_ok = (drawdown >= float(p["depth_min"])) & (drawdown <= float(p["depth_max"]))
    depth_score = depth_ok.astype(int) * 10
    depth_score = depth_score.astype("float64")

    score = (trend_score + touch_score + decline_score + react_score + depth_score).clip(upper=100)

    out = pd.DataFrame({
        "trend_score": trend_score,
        "touch_score": touch_score,
        "decline_score": decline_score,
        "react_score": react_score,
        "depth_score": depth_score,
        "score": score,
        "avg_ret_lb": avg_ret_lb,
        "drawdown": drawdown,
        "touch_recent": touch_recent.astype(int),
    }, index=df.index)
    return out


def score(df: pd.DataFrame, params: dict) -> pd.Series:
    return score_components(df, params)["score"]


def signal(df: pd.DataFrame, params: dict) -> pd.Series:
    p = {**DEFAULT_PARAMS, **params}
    th = float(p["score_threshold"])
    s = score(df, params)
    sig = (s >= th).fillna(False).astype("int8")
    return sig
