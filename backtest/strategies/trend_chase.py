"""'추세 추격' (trend_chase) — 장대양봉 + 거래량 폭증 기반 추격 매수 추천 시그널.

대시보드 라벨: '추세 추격'
영문 코드명: trend_chase

== 사용자 직관 ==
이평선과는 무관. 추세에 올라탔다고 판단되는 강한 일/주봉이 나왔을 때 추격 매수 후보.
핵심은 **장대양봉 + 거래량 폭증** 두 가지.

== 점수 공식 (0~100) ==
  종가 상승률 (당일 양봉 크기) ............ 0~40
    >= +3%   : +15
    >= +5%   : +10 추가
    >= +7%   : +10 추가
    >= +10%  : +5  추가
  거래량 폭증 (당일 / 20봉 평균) ........... 0~40
    >= 1.5x  : +15
    >= 2.0x  : +10 추가
    >= 3.0x  : +10 추가
    >= 5.0x  : +5  추가
  양봉 실체 강도 ((close-open)/(high-low) ≥ 0.6) ..... +10
  거래대금 절대 규모 (해당 봉의 amount 상위 30% 이내)
    — 자산 내부 분위, 같은 시계열 안에서 비교 ........... +10
  ===
  합계 0~100

== signal ==
  score >= score_threshold (기본 60) 일 때 1.

== 엔진 호환 ==
  - 룩어헤드 금지: amount 분위는 expanding(min_periods=W) 으로 과거 데이터만 사용
  - 반환 signal: pd.Series of int8 in {0, 1}
  - score / 컴포넌트 디버깅: score_components(df, params) -> pd.DataFrame
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NAME = "trend_chase"
LABEL_KR = "추세 추격"

DEFAULT_PARAMS = {
    "vol_ma": 20,             # 거래량 평균 기간
    "ret_th": [0.03, 0.05, 0.07, 0.10],   # 종가 상승률 4단
    "ret_pts": [15, 10, 10, 5],
    "volx_th": [1.5, 2.0, 3.0, 5.0],      # 거래량 배수 4단
    "volx_pts": [15, 10, 10, 5],
    "body_ratio_min": 0.6,    # 양봉 실체 / (high-low)
    "body_pts": 10,
    "amount_pctl_min": 0.70,  # 절대 거래대금 상위 30%
    "amount_pts": 10,
    "amount_lookback": 250,   # 분위 계산 윈도우 (일봉 1년치, 주봉 5년치 ~ expanding)
    "score_threshold": 80,
}


def _typical_amount(df: pd.DataFrame) -> pd.Series:
    """amount 컬럼이 있으면 그대로, 없으면 close*volume 으로 대체."""
    if "amount" in df.columns and df["amount"].notna().any():
        return df["amount"].astype("float64")
    return (df["close"].astype("float64") * df["volume"].astype("float64"))


def score_components(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    p = {**DEFAULT_PARAMS, **params}
    vol_ma = int(p["vol_ma"])

    close = df["close"].astype("float64")
    open_ = df["open"].astype("float64")
    high = df["high"].astype("float64")
    low = df["low"].astype("float64")
    volume = df["volume"].astype("float64")

    # 1) 종가 상승률 (오늘 close vs 어제 close)
    ret = close.pct_change()
    ret_score = pd.Series(0.0, index=df.index)
    for th, pts in zip(p["ret_th"], p["ret_pts"]):
        ret_score = ret_score + np.where(ret >= th, pts, 0)
    ret_score = pd.Series(ret_score, index=df.index)

    # 2) 거래량 폭증 (오늘 volume / MA volume)
    vol_avg = volume.rolling(vol_ma, min_periods=vol_ma).mean()
    volx = volume / vol_avg
    vol_score = pd.Series(0.0, index=df.index)
    for th, pts in zip(p["volx_th"], p["volx_pts"]):
        vol_score = vol_score + np.where(volx >= th, pts, 0)
    vol_score = pd.Series(vol_score, index=df.index)

    # 3) 양봉 실체 강도
    body = (close - open_).clip(lower=0)
    rng = (high - low).replace(0, np.nan)
    body_ratio = body / rng
    body_score = np.where(
        (ret > 0) & (body_ratio >= p["body_ratio_min"]),
        p["body_pts"], 0,
    )
    body_score = pd.Series(body_score, index=df.index, dtype="float64")

    # 4) 거래대금 절대 규모 (자산 시계열 내 분위)
    amt = _typical_amount(df)
    lb = int(p["amount_lookback"])
    # expanding 분위로 룩어헤드 방지
    amt_pctl = amt.rolling(lb, min_periods=min(60, lb)).apply(
        lambda x: (x[-1] >= np.quantile(x, p["amount_pctl_min"])) * 1.0,
        raw=True,
    )
    amount_score = (amt_pctl.fillna(0) * p["amount_pts"]).astype("float64")

    score = (ret_score + vol_score + body_score + amount_score).clip(upper=100)

    out = pd.DataFrame({
        "ret_score": ret_score,
        "vol_score": vol_score,
        "body_score": body_score,
        "amount_score": amount_score,
        "score": score,
        "ret": ret,
        "volx": volx,
        "body_ratio": body_ratio,
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
