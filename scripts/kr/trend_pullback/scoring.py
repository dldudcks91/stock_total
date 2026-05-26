"""trend_pullback — numeric (일봉 df) 기반 점수.

scripts._common.indicators.compute_indicators 가 add 한 컬럼들을 받아 score 를 매긴다.
같은 종목 × 같은 시점에 v2 와 v3 점수는 *다른* 시스템이며, 운영 표준은 **v3**.

운영 threshold (kr_backtest_numeric.py 백테스트 기반):
  - PULLBACK ≥ 45   (점수 분위 q8~q9, D+60 mean +15~17%, Sharpe 0.28)

입력 df 에 다음 컬럼이 미리 add 돼 있어야 함 (compute_indicators + acc_w):
  bull_stack, bear_stack, ma10_slope, ma20_slope, dist_ma10, dist_ma20,
  acc_d, acc_w, ret_30d, ret_90d, from_high_1y, vol_recent_vs_prior,
  recent_strong_bull_10d, Close, ma10, ma20.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def score_pullback(df: pd.DataFrame) -> pd.Series:
    """v2 — visual_review 라벨 없는 첫 numeric 버전. 백테스트 baseline 용."""
    sc = pd.Series(0.0, index=df.index)

    # 1) 정배열 + slope up
    bull_up = (df["bull_stack"] == 1) & (df["ma10_slope"] > 0) & (df["ma20_slope"] > 0)
    sc += np.where(bull_up, 20, 0)
    recovery = (df["bear_stack"] == 0) & (df["bull_stack"] == 0) & (df["Close"] > df["ma20"]) & (df["ma20_slope"] > -0.01)
    sc += np.where(recovery, 10, 0)

    # 2) MA10 근접 (눌림목)
    near_ma10 = (df["dist_ma10"].abs() < 0.03) & (df["ma10_slope"] > 0)
    sc += np.where(near_ma10, 15, 0)
    near_ma10_loose = (df["dist_ma10"].abs() < 0.05) & (~near_ma10)
    sc += np.where(near_ma10_loose, 8, 0)

    # 3) MA20 근접 (좀 더 깊은 눌림)
    near_ma20 = (df["dist_ma20"].abs() < 0.04) & (df["ma20_slope"] > 0) & (~near_ma10)
    sc += np.where(near_ma20, 10, 0)

    # 4) 매집 (acc_w × 10 + acc_d × 8)
    sc += df["acc_w"] * 10 + df["acc_d"] * 8

    # 5) ret_30d 적정 (눌림은 너무 안 올랐어야)
    sc += np.where(df["ret_30d"].between(0.0, 0.20), 5, 0)
    sc += np.where(df["ret_30d"].between(-0.05, 0.0), 3, 0)
    sc += np.where(df["ret_30d"] > 0.50, -15, 0)
    sc += np.where(df["ret_30d"].between(0.30, 0.50), -5, 0)
    sc += np.where(df["ret_30d"] < -0.15, -8, 0)

    # 6) from_high 조정 폭 (-5% ~ -25% 이상적)
    sc += np.where(df["from_high_1y"].between(-0.25, -0.05), 5, 0)
    sc += np.where(df["from_high_1y"] < -0.50, -8, 0)
    sc += np.where(df["from_high_1y"] > -0.02, -3, 0)

    # 7) 거래량 정상 (눌림은 거래량 줄어듦)
    sc += np.where(df["vol_recent_vs_prior"].between(0.5, 1.3), 3, 0)

    # 8) 최근 강양봉 (반등 시그널)
    sc += np.where(df["recent_strong_bull_10d"] == 1, 5, 0)

    # 페널티: 역배열 + 가격 < MA10
    sc += np.where((df["bear_stack"] == 1) & (df["Close"] < df["ma10"]), -15, 0)

    return sc


def score_pullback_v3(df: pd.DataFrame) -> pd.Series:
    """v3 — 상관계수 기반 가중치 조정. 운영 표준.

    v2 대비 변경:
      - acc_w 제거 (음 상관 -0.029)
      - ret_90d 신규 (+0.068)
      - vol_recent_vs_prior 강화 (+0.066)
      - recent_strong_bull_10d 강화 (+0.059)
      - bull_stack 약화 (+0.018)
    """
    sc = pd.Series(0.0, index=df.index)

    # 1) 정배열 + slope up (가중치 절반)
    bull_up = (df["bull_stack"] == 1) & (df["ma10_slope"] > 0) & (df["ma20_slope"] > 0)
    sc += np.where(bull_up, 10, 0)
    recovery = (df["bear_stack"] == 0) & (df["bull_stack"] == 0) & (df["Close"] > df["ma20"]) & (df["ma20_slope"] > -0.01)
    sc += np.where(recovery, 8, 0)

    # 2) MA10/20 근접 (눌림목) - 살짝 축소
    near_ma10 = (df["dist_ma10"].abs() < 0.03) & (df["ma10_slope"] > 0)
    sc += np.where(near_ma10, 12, 0)
    near_ma10_loose = (df["dist_ma10"].abs() < 0.05) & (~near_ma10)
    sc += np.where(near_ma10_loose, 6, 0)
    near_ma20 = (df["dist_ma20"].abs() < 0.04) & (df["ma20_slope"] > 0) & (~near_ma10)
    sc += np.where(near_ma20, 8, 0)

    # 3) 매집 (acc_w 제거, acc_d 만)
    sc += df["acc_d"] * 10

    # 4) ret_30d (가중치 축소)
    sc += np.where(df["ret_30d"].between(0.0, 0.20), 3, 0)
    sc += np.where(df["ret_30d"].between(-0.05, 0.0), 2, 0)
    sc += np.where(df["ret_30d"] > 0.50, -10, 0)
    sc += np.where(df["ret_30d"] < -0.15, -8, 0)

    # 5) ret_90d (NEW — 강한 양 상관)
    sc += np.where(df["ret_90d"] > 0.20, 10, 0)
    sc += np.where(df["ret_90d"].between(0.05, 0.20), 6, 0)
    sc += np.where(df["ret_90d"] < -0.10, -8, 0)

    # 6) from_high_1y (신고가 근접 가산)
    sc += np.where(df["from_high_1y"] > -0.10, 6, 0)
    sc += np.where(df["from_high_1y"].between(-0.25, -0.10), 3, 0)
    sc += np.where(df["from_high_1y"] < -0.50, -10, 0)

    # 7) 거래량 증가 (양 상관 강화)
    sc += np.where(df["vol_recent_vs_prior"] > 1.5, 8, 0)
    sc += np.where(df["vol_recent_vs_prior"].between(1.0, 1.5), 4, 0)
    sc += np.where(df["vol_recent_vs_prior"] < 0.5, -3, 0)

    # 8) 최근 강양봉 (양 상관 강화)
    sc += np.where(df["recent_strong_bull_10d"] == 1, 10, 0)

    # 페널티
    sc += np.where((df["bear_stack"] == 1) & (df["Close"] < df["ma10"]), -15, 0)

    return sc


# 점수 최대값 (페널티 제외, 보수적 추정). recommend_v3 운영 표시용.
PB_V3_MAX = 77
