"""G4 (그랜빌 4법칙) — 이격과대 반등 catch.

정통 정의: 하락 추세 MA 아래에서 주가가 MA 와 크게 이격된 후, 매도 클라이맥스가
지나가고 반등이 시작되는 자리.

룰 근거: ``docs/granville_g4_fit.md`` (D60 유니버스 시총 상위 KR200/US100 백테스트).

배선 상태: **함수 편입 완료, dashboards/_precompute.py 배선 대기**.

리스크 (편입 후에도 유효):
  - Livermore "떨어지는 칼날 잡지 마라" — 유명 트레이더 지지 없음.
  - 백테스트는 현존 종목 유니버스라 상장폐지 종목 반영 X (survivorship bias).
  - 손절 룰 백테스트에서 어떤 손절선도 성능 개선 X → 진입 후 회복까지 홀드가 정답.
    개별 종목이 회복 못 하는 경우 큰 손실 가능 → **포지션 사이징으로만 리스크 관리**.

Backtest 요약 (D60 + 거래량 필터 ON + 첫 양봉 진입, strict MA60 회복 청산):
  KR (시총 상위 200 중 3년치): 승률 73%, 평균수익 +4.79%, 보유 37일
  US (시총 상위 100 중 3년치): 승률 75%, 평균수익 +4.89%, 보유 35일
"""
from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd

# 룰 파라미터 (백테스트로 확정, docs/granville_g4_fit.md 참조)
G4_MA_WIN = 60                # 일봉 MA60 = 중기 하락 추세 기준선
G4_SLOPE_WIN = 20             # MA60 slope 판정 봉수 (20봉 diff < 0 → 하락)
G4_PCT_WIN = 756              # rolling percentile 윈도우 (거래일 3년)
G4_PCT_MIN_PERIODS = 252      # percentile 계산 최소 표본 (1년)
G4_PCT = 0.05                 # 이격 극단 = 3년 dev 분포 하위 5%
G4_VOL_WIN = 20               # 극단 봉 거래량 판정 기준선
G4_VOL_MULT = 1.5             # 극단 봉 거래량 ≥ 20일 평균 × 1.5 (매도 클라이맥스)
G4_MAX_LOOKBACK = 20          # 극단 봉이 최근 20봉 안에 있어야 유효 (오래된 신호 무시)


def signal_g4(df: pd.DataFrame,
              ma_win: int = G4_MA_WIN,
              slope_win: int = G4_SLOPE_WIN,
              pct_win: int = G4_PCT_WIN,
              pct: float = G4_PCT,
              vol_win: int = G4_VOL_WIN,
              vol_mult: float = G4_VOL_MULT,
              max_lookback: int = G4_MAX_LOOKBACK) -> Tuple[bool, dict]:
    """G4 (그랜빌 4법칙) — 이격과대 반등 catch.

    일봉 dataframe 전용 (필수 컬럼: open, close, volume).

    통과 조건 (모두 AND):
      1. 오늘 close < MA60                                      ← 사이클 안
      2. MA60 slope (``slope_win`` 봉 diff) < 0                 ← 하락 추세
      3. 오늘 close > 오늘 open                                 ← 첫 양봉 (반등 확인)
      4. 최근 ``max_lookback`` 봉 안에 "극단 봉" 존재:
         - close < MA60 AND slope < 0
         - dev = (close − MA60) / MA60 ≤ rolling 하위 ``pct`` percentile
         - volume ≥ 20일 평균 × ``vol_mult``                    ← 매도 클라이맥스
      5. 극단 봉 이후 오늘 전까지 close 가 MA60 을 재돌파한 봉 없음
         (사이클 여전히 진행 중, 신호 유효 상태)

    청산 (별도 gate): close ≥ MA60 재돌파 봉 종가. 손절 없음.

    반환: (passed, extras).
      extras = {
        dev_now, dev_extreme, days_since_extreme,
        ma60, ma60_slope, vol_mult_extreme
      }
    """
    min_bars = pct_win + ma_win
    if len(df) < min_bars:
        return False, {}
    if not {"open", "close", "volume"}.issubset(df.columns):
        return False, {}

    close = df["close"].astype(float)
    open_ = df["open"].astype(float)
    volume = df["volume"].astype(float)

    ma = close.rolling(ma_win).mean()
    slope = ma.diff(slope_win)
    dev = (close - ma) / ma
    pct_thresh = dev.rolling(pct_win, min_periods=G4_PCT_MIN_PERIODS).quantile(pct)
    vol_ma = volume.rolling(vol_win).mean()

    ma_now = ma.iloc[-1]
    slope_now = slope.iloc[-1]
    close_now = close.iloc[-1]
    open_now = open_.iloc[-1]

    if pd.isna(ma_now) or pd.isna(slope_now) or pd.isna(pct_thresh.iloc[-1]):
        return False, {}

    # gate 1~3
    if close_now >= ma_now:
        return False, {}
    if slope_now >= 0:
        return False, {}
    if close_now <= open_now:
        return False, {}

    # gate 4: 최근 max_lookback 봉 안 (오늘 제외) 극단 봉 존재
    start = max(0, len(df) - max_lookback - 1)
    end = len(df) - 1  # 오늘 제외
    if start >= end:
        return False, {}
    w_close = close.iloc[start:end]
    w_ma = ma.iloc[start:end]
    w_slope = slope.iloc[start:end]
    w_dev = dev.iloc[start:end]
    w_pct = pct_thresh.iloc[start:end]
    w_vol = volume.iloc[start:end]
    w_vol_ma = vol_ma.iloc[start:end]

    extreme_mask = (
        (w_slope < 0)
        & (w_close < w_ma)
        & (w_dev <= w_pct)
        & (w_vol_ma > 0)
        & (w_vol >= w_vol_ma * vol_mult)
    )
    if not extreme_mask.any():
        return False, {}

    # 가장 최근 극단 봉 (정수 위치, df 인덱스 무관하게 안전)
    extreme_pos = int(np.where(extreme_mask.to_numpy())[0][-1]) + start

    # gate 5: 극단 봉 이후 오늘 전까지 close ≥ ma 재돌파 없음
    if extreme_pos + 1 < end:
        after_close = close.iloc[extreme_pos + 1:end]
        after_ma = ma.iloc[extreme_pos + 1:end]
        if (after_close >= after_ma).any():
            return False, {}

    days_since = end - extreme_pos  # 오늘이 end=len-1 이므로 = len-1 - extreme_pos
    extras = {
        "dev_now": float(dev.iloc[-1]),
        "dev_extreme": float(dev.iloc[extreme_pos]),
        "days_since_extreme": days_since,
        "ma60": float(ma_now),
        "ma60_slope": float(slope_now),
        "vol_mult_extreme": float(volume.iloc[extreme_pos] / vol_ma.iloc[extreme_pos]),
    }
    return True, extras
