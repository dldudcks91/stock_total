"""crypto trend_pullback — TF 무관 (1h/4h/1d) pullback 점수 Series.

설계 의도 (2026-05-27):
  - KR `scripts.kr.trend_pullback.scoring.score_pullback_v3` 의 로직을 crypto 전 TF 에
    재사용. 입력 df 의 timeframe 은 자동으로 적응 (10/30 "bar" 단위 의미가 TF별로
    1h/4h/1d 로 자연 스케일).
  - 하드 게이트(`had_rally`, `near_ma`) 같이 0/1 binary 컷오프는 사용하지 않음 —
    각 컴포넌트에 부분 점수 (partial credit). 이전 backtest 버전의 "게이트 flip 으로
    점수 0→100 점프" 문제 해결.

사용:
    from scripts.crypto.trend_pullback.scoring import score_pullback_crypto_tf
    sc_1h = score_pullback_crypto_tf(df_1h)   # crypto lowercase OHLCV
    sc_4h = score_pullback_crypto_tf(df_4h)   # 4h 리샘플 결과
    sc_1d = score_pullback_crypto_tf(df_1d)

반환은 모두 입력 df 의 index 에 align 된 pd.Series (점수 0~PB_CRYPTO_MAX).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts._common.indicators import compute_indicators
from scripts.crypto.trend_chase.scoring import to_kr_schema


# 점수 최대값 (페널티 제외, 보수적). 컴포넌트 합 = 10+8+12+6+8+10+10+6+3+8+4+3+10+10 ≈ 108
# 실제로 ret_30d/ret_90d/from_high 동시 만점은 어렵기 때문에 운영상 ~70~80 천장.
PB_CRYPTO_MAX = 100


def score_pullback_crypto_tf(df: pd.DataFrame) -> pd.Series:
    """crypto OHLCV (lowercase) 또는 KR style (uppercase) df → pullback v3 점수 Series.

    입력 df 는 임의 TF (1h/4h/1d 모두). row 수가 너무 적으면 (compute_indicators 가
    rolling 윈도우 못 채우는 구간) NaN → 0 으로 처리.

    Args:
      df : OHLCV. crypto 캐시 (timestamp + lowercase) 또는 이미 변환된 KR style 둘 다 OK.

    Returns:
      pd.Series, index = df 의 DatetimeIndex, dtype=float64.
    """
    if df is None or df.empty:
        return pd.Series(dtype="float64")

    # 1) schema 정규화 — crypto → KR (대문자 + DatetimeIndex)
    if "Close" not in df.columns:
        df_kr = to_kr_schema(df)
    else:
        df_kr = df.copy()
        if not isinstance(df_kr.index, pd.DatetimeIndex) and "timestamp" in df_kr.columns:
            df_kr = to_kr_schema(df_kr)
    if df_kr.empty or "Close" not in df_kr.columns:
        return pd.Series(dtype="float64", index=df.index)

    # 2) 지표 add — TF 무관 (10/30 "bar" 단위 의미만 달라짐)
    df_ind = compute_indicators(df_kr)

    # 3) v3 채점 (soft components — 하드 게이트 X)
    sc = pd.Series(0.0, index=df_ind.index)

    # (a) 추세 — 정배열 + slope up (KR v3 와 동일 가중치)
    bull_up = (df_ind["bull_stack"] == 1) & (df_ind["ma10_slope"] > 0) & (df_ind["ma20_slope"] > 0)
    sc += np.where(bull_up, 10, 0)
    # 회복 구간 (bear 도 bull 도 아닌 중립, MA20 위, slope 거의 양)
    recovery = (df_ind["bear_stack"] == 0) & (df_ind["bull_stack"] == 0) & \
               (df_ind["Close"] > df_ind["ma20"]) & (df_ind["ma20_slope"] > -0.01)
    sc += np.where(recovery, 8, 0)

    # (b) MA10/MA20 근접 (눌림목의 핵심) — soft, 가까울수록 가산
    near_ma10 = (df_ind["dist_ma10"].abs() < 0.03) & (df_ind["ma10_slope"] > 0)
    sc += np.where(near_ma10, 12, 0)
    near_ma10_loose = (df_ind["dist_ma10"].abs() < 0.05) & (~near_ma10)
    sc += np.where(near_ma10_loose, 6, 0)
    near_ma20 = (df_ind["dist_ma20"].abs() < 0.04) & (df_ind["ma20_slope"] > 0) & (~near_ma10)
    sc += np.where(near_ma20, 8, 0)

    # (c) 매집 (acc_d) — KR v3 그대로
    sc += df_ind["acc_d"].fillna(0) * 10

    # (d) ret_30d — crypto 스케일로 임계 ×2 조정 (1d 변동성 KR ~4%, crypto ~8%)
    #     단, TF 의존성을 두지 않기 위해 일반 임계 유지하고 +/- 폭만 약화.
    sc += np.where(df_ind["ret_30d"].between(0.0, 0.40), 3, 0)
    sc += np.where(df_ind["ret_30d"].between(-0.10, 0.0), 2, 0)
    sc += np.where(df_ind["ret_30d"] > 1.0, -10, 0)        # 너무 많이 올랐으면 -10
    sc += np.where(df_ind["ret_30d"] < -0.30, -8, 0)

    # (e) ret_90d — KR v3 의 핵심 양 상관 가중. crypto 스케일 ×2.
    sc += np.where(df_ind["ret_90d"] > 0.40, 10, 0)
    sc += np.where(df_ind["ret_90d"].between(0.10, 0.40), 6, 0)
    sc += np.where(df_ind["ret_90d"] < -0.20, -8, 0)

    # (f) from_high_1y — 신고가 근접 가산
    sc += np.where(df_ind["from_high_1y"] > -0.10, 6, 0)
    sc += np.where(df_ind["from_high_1y"].between(-0.25, -0.10), 3, 0)
    sc += np.where(df_ind["from_high_1y"] < -0.50, -10, 0)

    # (g) 거래량 증가 (반등 시그널)
    sc += np.where(df_ind["vol_recent_vs_prior"] > 1.5, 8, 0)
    sc += np.where(df_ind["vol_recent_vs_prior"].between(1.0, 1.5), 4, 0)
    sc += np.where(df_ind["vol_recent_vs_prior"] < 0.5, -3, 0)

    # (h) 최근 강양봉 (반등 트리거)
    sc += np.where(df_ind["recent_strong_bull_10d"] == 1, 10, 0)

    # (i) 페널티 — 역배열 + 가격 < MA10
    sc += np.where((df_ind["bear_stack"] == 1) & (df_ind["Close"] < df_ind["ma10"]), -15, 0)

    # 음수 점수는 0 으로 floor (운영 직관: "추천 후보 점수"는 음수 무의미)
    sc = sc.clip(lower=0).fillna(0)
    return sc
