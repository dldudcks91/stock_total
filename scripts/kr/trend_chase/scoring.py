"""trend_chase — numeric (일봉 df) 기반 점수.

같은 indicators 입력으로 chase 패턴 점수를 매긴다. v2 → v5 까지 진화:
  - v2  : 기본
  - v3  : 상관계수 기반 가중치 조정
  - v4  : "강한 추격" 본질 강조 (LG이노텍 같은 폭등주 잡기)
  - v5  : 두 패턴 모두 (MA10 riding + 강양봉 후 매도세 X)
  - v5_1: v5 + 오늘 폭등 / MA10 너무 멀어진 자리 페널티 강화

운영 표준 = **v5_1** (recommend_v3 가 사용).

운영 threshold (kr_backtest_numeric.py 백테스트 기반):
  - CHASE ≥ 13 (점수 분위 q3 sweet spot, D+60 Sharpe 0.39)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def score_chase(df: pd.DataFrame) -> pd.Series:
    """v2 — 기본 chase. baseline."""
    sc = pd.Series(0.0, index=df.index)

    bull = (df["bull_stack"] == 1) & (df["Close"] > df["ma10"])
    sc += np.where(bull, 20, 0)
    all_up = (df["ma10_slope"] > 0) & (df["ma20_slope"] > 0) & (df["ma50_slope"] > 0)
    sc += np.where(all_up, 10, 0)

    sc += np.where(df["ret_30d"] > 0.50, 12, 0)
    sc += np.where(df["ret_30d"].between(0.30, 0.50), 9, 0)
    sc += np.where(df["ret_30d"].between(0.15, 0.30), 6, 0)
    sc += np.where(df["ret_30d"].between(0.05, 0.15), 3, 0)
    sc += np.where(df["ret_30d"] < 0, -10, 0)

    sc += np.where(df["ret_90d"] > 1.0, 10, 0)
    sc += np.where(df["ret_90d"].between(0.5, 1.0), 7, 0)
    sc += np.where(df["ret_90d"].between(0.3, 0.5), 5, 0)
    sc += np.where(df["ret_90d"].between(0.1, 0.3), 2, 0)
    sc += np.where(df["ret_90d"] < -0.1, -15, 0)

    accel_ratio = df["ret_30d"] / (df["ret_90d"] / 3).replace(0, np.nan)
    sc += np.where(accel_ratio > 1.5, 8, 0)
    sc += np.where(accel_ratio.between(1.0, 1.5), 4, 0)

    sc += np.where(df["vol_recent_vs_prior"] > 2.0, 8, 0)
    sc += np.where(df["vol_recent_vs_prior"].between(1.5, 2.0), 5, 0)
    sc += np.where(df["vol_recent_vs_prior"].between(1.2, 1.5), 2, 0)

    sc += np.where(df["recent_strong_bull_10d"] == 1, 6, 0)

    sc += np.where(df["from_high_1y"] > -0.05, 5, 0)
    sc += np.where(df["from_high_1y"].between(-0.15, -0.05), 3, 0)
    sc += np.where(df["from_high_1y"] < -0.30, -8, 0)

    sc += np.where(df["bear_stack"] == 1, -20, 0)
    sc += np.where(df["Close"] < df["ma10"], -8, 0)
    return sc


def score_chase_v3(df: pd.DataFrame) -> pd.Series:
    """v3 — 상관계수 기반 조정.

    변경: ret_30d 가중치 축소, ret_90d 축소, from_high_1y 강화, recent_strong_bull 강화.
    """
    sc = pd.Series(0.0, index=df.index)

    bull = (df["bull_stack"] == 1) & (df["Close"] > df["ma10"])
    sc += np.where(bull, 12, 0)
    all_up = (df["ma10_slope"] > 0) & (df["ma20_slope"] > 0) & (df["ma50_slope"] > 0)
    sc += np.where(all_up, 6, 0)

    sc += np.where(df["ret_30d"] > 0.50, -8, 0)
    sc += np.where(df["ret_30d"].between(0.30, 0.50), 0, 0)
    sc += np.where(df["ret_30d"].between(0.15, 0.30), 5, 0)
    sc += np.where(df["ret_30d"].between(0.05, 0.15), 6, 0)
    sc += np.where(df["ret_30d"].between(-0.05, 0.05), 2, 0)
    sc += np.where(df["ret_30d"] < -0.05, -8, 0)

    sc += np.where(df["ret_90d"] > 1.0, 3, 0)
    sc += np.where(df["ret_90d"].between(0.5, 1.0), 4, 0)
    sc += np.where(df["ret_90d"].between(0.3, 0.5), 5, 0)
    sc += np.where(df["ret_90d"].between(0.1, 0.3), 4, 0)
    sc += np.where(df["ret_90d"] < -0.1, -15, 0)

    accel_ratio = df["ret_30d"] / (df["ret_90d"] / 3).replace(0, np.nan)
    sc += np.where(accel_ratio > 1.5, 6, 0)
    sc += np.where(accel_ratio.between(1.0, 1.5), 3, 0)

    sc += np.where(df["vol_recent_vs_prior"] > 2.0, 8, 0)
    sc += np.where(df["vol_recent_vs_prior"].between(1.5, 2.0), 5, 0)
    sc += np.where(df["vol_recent_vs_prior"].between(1.2, 1.5), 2, 0)

    sc += np.where(df["recent_strong_bull_10d"] == 1, 10, 0)

    sc += np.where(df["from_high_1y"] > -0.05, 10, 0)
    sc += np.where(df["from_high_1y"].between(-0.15, -0.05), 6, 0)
    sc += np.where(df["from_high_1y"] < -0.30, -10, 0)

    sc += np.where(df["bear_stack"] == 1, -20, 0)
    sc += np.where(df["Close"] < df["ma10"], -8, 0)
    return sc


def score_chase_v4(df: pd.DataFrame) -> pd.Series:
    """v4 — "강한 추격" 본질 강조. 폭등주 (LG이노텍 같은) 명시적으로 잡기.

    D+10~D+20 단기 평가용. 사용자 의도로 추가됨.
    """
    sc = pd.Series(0.0, index=df.index)

    bull = (df["bull_stack"] == 1) & (df["Close"] > df["ma10"])
    sc += np.where(bull, 15, 0)
    all_up = (df["ma10_slope"] > 0) & (df["ma20_slope"] > 0) & (df["ma50_slope"] > 0)
    sc += np.where(all_up, 10, 0)

    sc += np.where(df["ret_30d"] > 1.0, 15, 0)
    sc += np.where(df["ret_30d"].between(0.5, 1.0), 12, 0)
    sc += np.where(df["ret_30d"].between(0.3, 0.5), 10, 0)
    sc += np.where(df["ret_30d"].between(0.15, 0.3), 6, 0)
    sc += np.where(df["ret_30d"].between(0.05, 0.15), 2, 0)
    sc += np.where(df["ret_30d"] < -0.05, -15, 0)

    sc += np.where(df["ret_90d"] > 2.0, 12, 0)
    sc += np.where(df["ret_90d"].between(1.0, 2.0), 10, 0)
    sc += np.where(df["ret_90d"].between(0.5, 1.0), 7, 0)
    sc += np.where(df["ret_90d"].between(0.25, 0.5), 4, 0)
    sc += np.where(df["ret_90d"] < 0, -20, 0)

    accel_ratio = df["ret_30d"] / (df["ret_90d"] / 3).replace(0, np.nan)
    sc += np.where(accel_ratio > 2, 10, 0)
    sc += np.where(accel_ratio.between(1.5, 2), 6, 0)
    sc += np.where(accel_ratio.between(1.0, 1.5), 3, 0)

    sc += np.where(df["vol_recent_vs_prior"] > 3.0, 12, 0)
    sc += np.where(df["vol_recent_vs_prior"].between(2.0, 3.0), 8, 0)
    sc += np.where(df["vol_recent_vs_prior"].between(1.5, 2.0), 5, 0)
    sc += np.where(df["vol_recent_vs_prior"].between(1.2, 1.5), 3, 0)
    sc += np.where(df["vol_recent_vs_prior"] < 0.7, -5, 0)

    sc += np.where(df["recent_strong_bull_10d"] == 1, 12, 0)

    sc += np.where(df["from_high_1y"] > -0.03, 12, 0)
    sc += np.where(df["from_high_1y"].between(-0.10, -0.03), 8, 0)
    sc += np.where(df["from_high_1y"].between(-0.20, -0.10), 3, 0)
    sc += np.where(df["from_high_1y"] < -0.30, -15, 0)

    sc += np.where(df["bear_stack"] == 1, -25, 0)
    sc += np.where(df["Close"] < df["ma10"], -10, 0)
    return sc


def score_chase_v5(df: pd.DataFrame) -> pd.Series:
    """v5 — 두 패턴 모두 잡기.

    패턴 1: MA10 riding (반복적 MA10 터치 → 양봉 반등)
    패턴 2: 강양봉 후 매도세 X (직선 상승)
    """
    sc = pd.Series(0.0, index=df.index)

    # 공통 — 정배열 + 추세 강도
    bull = (df["bull_stack"] == 1) & (df["Close"] > df["ma10"])
    sc += np.where(bull, 12, 0)
    all_up = (df["ma10_slope"] > 0) & (df["ma20_slope"] > 0) & (df["ma50_slope"] > 0)
    sc += np.where(all_up, 8, 0)

    # 공통 — ret_30d / ret_90d
    sc += np.where(df["ret_30d"] > 1.0, 10, 0)
    sc += np.where(df["ret_30d"].between(0.5, 1.0), 8, 0)
    sc += np.where(df["ret_30d"].between(0.3, 0.5), 7, 0)
    sc += np.where(df["ret_30d"].between(0.15, 0.3), 5, 0)
    sc += np.where(df["ret_30d"].between(0.05, 0.15), 2, 0)
    sc += np.where(df["ret_30d"] < -0.05, -15, 0)

    sc += np.where(df["ret_90d"] > 2.0, 10, 0)
    sc += np.where(df["ret_90d"].between(1.0, 2.0), 8, 0)
    sc += np.where(df["ret_90d"].between(0.5, 1.0), 6, 0)
    sc += np.where(df["ret_90d"].between(0.25, 0.5), 4, 0)
    sc += np.where(df["ret_90d"] < 0, -20, 0)

    # 공통 — 거래량 폭증
    sc += np.where(df["vol_recent_vs_prior"] > 3.0, 10, 0)
    sc += np.where(df["vol_recent_vs_prior"].between(2.0, 3.0), 7, 0)
    sc += np.where(df["vol_recent_vs_prior"].between(1.5, 2.0), 4, 0)
    sc += np.where(df["vol_recent_vs_prior"].between(1.2, 1.5), 2, 0)
    sc += np.where(df["vol_recent_vs_prior"] < 0.7, -5, 0)

    # ─── 패턴 1 — MA10 riding ───
    sc += np.where((df["ma10_strong_up"] == 1) & (df["Close"] > df["ma10"]), 8, 0)
    sc += np.where(df["ma10_touch_recent_5d"] == 1, 10, 0)
    sc += np.where(df["dist_ma10"].between(0, 0.10), 6, 0)
    sc += np.where(df["dist_ma10"] > 0.30, -5, 0)

    # ─── 패턴 2 — 강양봉 후 매도세 X ───
    sc += np.where(df["today_strong_bull"] == 1, 12, 0)
    sc += np.where(df["bullish_holding"] == 1, 8, 0)
    sc += np.where(df["from_high_1y"] > -0.03, 12, 0)
    sc += np.where(df["from_high_1y"].between(-0.10, -0.03), 8, 0)
    sc += np.where(df["from_high_1y"] < -0.30, -10, 0)

    # 페널티
    sc += np.where(df["bear_stack"] == 1, -25, 0)
    sc += np.where(df["Close"] < df["ma10"], -10, 0)
    return sc


def score_chase_v5_1(df: pd.DataFrame) -> pd.Series:
    """v5.1 — v5 + "이미 너무 오른 자리" 페널티 강화. **운영 표준**.

    오늘 폭등 (+15~20%) / MA10 너무 멀어진 종목은 진입 시점 늦음 → 페널티.
    """
    sc = score_chase_v5(df)
    # 오늘 폭등 페널티 (진입 자리 아님)
    sc += np.where(df["today_chg"] > 0.15, -20, 0)
    sc += np.where(df["today_chg"].between(0.08, 0.15), -10, 0)
    # MA10 너무 멀리 떨어진 자리 페널티 (강화)
    sc += np.where(df["dist_ma10"] > 0.30, -15, 0)
    sc += np.where(df["dist_ma10"].between(0.20, 0.30), -8, 0)
    return sc


# 점수 최대값 (페널티 제외, 보수적). recommend_v3 운영 표시용.
CH_V5_MAX = 106
