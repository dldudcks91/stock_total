"""G2 (사용자 재정의) — 추격 자리: 강한 거래량 통한 상승 catch.

Livermore Pivotal Point / Darvas Box Breakout / Turtle Donchian / O'Neil Cup
Breakout / Minervini VCP 계보와 정합. 유명 트레이더들이 가장 많이 지지하는
자리 — 브레이크아웃 + 대량거래.

파이프라인 배선 상태: **대기**. ``_recs.parquet.g2`` 컬럼 없음.

사용자 신조 (G3 자리 한정, "찍고 간다") 는 여기에 적용되지 않음 — G2 는 애초에
추격 관점의 자리를 명시적으로 잡는 컬럼이므로.
"""
from __future__ import annotations

from typing import Tuple

import pandas as pd

# 룰 파라미터 — 유명 트레이더 임계 참고:
#   Turtle 20일 신고가 (기계적), Weinstein 30주 MA 돌파 + 2×vol,
#   Darvas Box 2배 이상 대량, O'Neil 컵 브레이크아웃 40~50% 대량, Minervini VCP 정배열.
#   중도 그룹 감으로 잡음 — 3배 이상은 오탐 없지만 신호 부족, 1.5배는 남발.
G2_VOL_MULT_MIN = 2.0            # 오늘 거래량 ≥ K × 20봉 평균
G2_RETURN_MIN_STOCK = 0.03       # KR/US: 오늘 수익률 ≥ +3%
G2_RETURN_MIN_CRYPTO = 0.05      # Crypto: 변동성 크므로 +5% 상향
G2_LOOKBACK_HIGH = 5             # 최근 N봉 (오늘 제외) 신고가 갱신
G2_VOL_AVG_WINDOW = 20           # 평균 거래량 산정 봉 수


def signal_g2(df_tf: pd.DataFrame,
              vol_mult_min: float = G2_VOL_MULT_MIN,
              return_min: float = G2_RETURN_MIN_STOCK,
              lookback_high: int = G2_LOOKBACK_HIGH,
              vol_avg_window: int = G2_VOL_AVG_WINDOW) -> Tuple[bool, dict]:
    """G2 (사용자 재정의) — 추격 자리: 강한 거래량 통한 상승 catch.

    Livermore Pivotal Point / Darvas Box Breakout / Turtle Donchian / O'Neil Cup
    Breakout / Minervini VCP 계보와 정합. 유명 트레이더들이 가장 많이 지지하는
    자리 — 브레이크아웃 + 대량거래.

    자산별 임계는 호출부에서 ``return_min`` 으로 넘김:
      - KR/US: ``G2_RETURN_MIN_STOCK`` (+3%)
      - Crypto: ``G2_RETURN_MIN_CRYPTO`` (+5%, 변동성 상향)

    통과 조건 (모두 AND):
      1. 오늘 거래량 ≥ ``vol_mult_min`` × 최근 ``vol_avg_window`` 봉 (오늘 제외) 평균
      2. 오늘 수익률 (close/prev_close − 1) ≥ ``return_min``
      3. 오늘 high > 최근 ``lookback_high`` 봉 (오늘 제외) high 최대 — 신고가 갱신

    이평선 조건은 의도적으로 뺌 — G3 가 이평선 지지 담당이므로 G2 는 순수 추격
    시그널로 두어 컬럼 성격 분리.

    반환: (passed, extras).
      extras = {vol_mult, today_return, prev_high_max, avg_volume, close, prev_close}
    """
    min_bars = max(lookback_high, vol_avg_window) + 1
    if len(df_tf) < min_bars:
        return False, {}

    last = df_tf.iloc[-1]
    close = float(last["close"])
    high = float(last["high"])
    volume = float(last["volume"])
    prev_close = float(df_tf.iloc[-2]["close"])

    if any(pd.isna(x) or x <= 0 for x in (close, high, volume, prev_close)):
        return False, {}

    prev_vols = df_tf["volume"].iloc[-(vol_avg_window + 1):-1]
    avg_vol = float(prev_vols.mean())
    if avg_vol <= 0 or pd.isna(avg_vol):
        return False, {}
    vol_mult = volume / avg_vol

    today_return = (close / prev_close) - 1.0

    prev_highs = df_tf["high"].iloc[-(lookback_high + 1):-1]
    prev_high_max = float(prev_highs.max())
    is_new_high = high > prev_high_max

    passed = bool(
        vol_mult >= vol_mult_min
        and today_return >= return_min
        and is_new_high
    )
    extras = {
        "vol_mult": float(vol_mult),
        "today_return": float(today_return),
        "prev_high_max": float(prev_high_max),
        "avg_volume": float(avg_vol),
        "close": float(close),
        "prev_close": float(prev_close),
    }
    return passed, extras
