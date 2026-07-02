"""G1 (그랜빌 1법칙) — 바닥 반등 catch.

MA 시리즈에 2차함수(``y = a·x² + b·x + c``) 를 적합해서 "MA 하락 종료 + 반등 시작"
자리를 검출. 골든크로스 시점보다 몇 봉 늦지만 false breakout 필터링 강함.

룰 근거: ``docs/granville_quadratic_fit.md`` §4.

파이프라인 배선 상태: **대기**. ``dashboards/_precompute.py`` 미호출,
``_recs.parquet.g1`` 컬럼 없음. 배선 시 ticker swap 필터(§6.2)도 함께 얹기로 결정.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd

# 룰 파라미터 (docs/granville_quadratic_fit.md §4)
G1_N_WIN = 10              # 적합 윈도우 (봉 개수)
G1_R2_MIN = 0.85           # 적합 신뢰
G1_A_PCT_MIN = 0.10        # 곡률(a) 정규화 최소값 — U자 강도
G1_VERTEX_POS_MIN = 0.30   # vertex 상대 위치 하한 (윈도우 안 중반부터)
G1_VERTEX_POS_MAX = 0.85   # vertex 상대 위치 상한 (끝단은 "감속 중 하락" false positive)
G1_PX_VS_MA_MAX = 0.10     # |close − MA[-1]| / MA[-1] — 가격이 MA 근처


def signal_g1(df_tf: pd.DataFrame, ma_col: str = "ma20",
              n_win: int = G1_N_WIN) -> Tuple[bool, dict]:
    """G1 (그랜빌 1법칙) — MA 시리즈에 2차함수 적합.

    사이클 시작 = "MA 하락 종료 + 반등 시작". 골든크로스 시점보다 몇 봉 늦지만
    false breakout 필터링 강함.

    적합: 최근 n_win 봉의 ``ma_col`` 값에 ``y = a·x² + b·x + c`` 을 numpy.polyfit
    으로 적합. 정규화:
      - a_pct      = a / mean(MA) * 100  (곡률, % per bar²)
      - vertex_pos = (-b/2a) / (n_win-1) (윈도우 내 vertex 상대 위치, 0..1)
      - R²         = 1 − SS_res / SS_tot

    통과 조건 (docs/granville_quadratic_fit.md §4):
      1. R² ≥ G1_R2_MIN
      2. a_pct ≥ G1_A_PCT_MIN            (U자 곡률 충분)
      3. vertex_pos ∈ [G1_VERTEX_POS_MIN, G1_VERTEX_POS_MAX]
      4. MA[-1] > MA[-3]                 (실측 MA 회복 방향)
      5. |close − MA[-1]| / MA[-1] ≤ G1_PX_VS_MA_MAX

    반환: (passed, extras).
      extras = {a_pct, r2, vertex_pos, px_vs_ma, ma_last}
    """
    if len(df_tf) < n_win:
        return False, {}
    tail = df_tf.tail(n_win)
    ma = tail[ma_col].to_numpy(dtype=float)
    if np.isnan(ma).any() or float(np.mean(ma)) == 0.0:
        return False, {}

    x = np.arange(n_win, dtype=float)
    a, b, c = np.polyfit(x, ma, 2)
    y_hat = a * x * x + b * x + c
    ss_res = float(np.sum((ma - y_hat) ** 2))
    ss_tot = float(np.sum((ma - ma.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    ma_mean = float(ma.mean())
    a_pct = a / ma_mean * 100.0
    vertex_pos = (-b / (2.0 * a)) / (n_win - 1) if a != 0 else float("nan")

    ma_last = float(tail[ma_col].iloc[-1])
    ma_prev3 = float(tail[ma_col].iloc[-3])
    close = float(tail["close"].iloc[-1])
    px_vs_ma = abs(close - ma_last) / ma_last if ma_last > 0 else float("nan")

    passed = bool(
        r2 >= G1_R2_MIN
        and a_pct >= G1_A_PCT_MIN
        and G1_VERTEX_POS_MIN <= vertex_pos <= G1_VERTEX_POS_MAX
        and ma_last > ma_prev3
        and px_vs_ma <= G1_PX_VS_MA_MAX
    )
    extras = {
        "a_pct": float(a_pct),
        "r2": float(r2),
        "vertex_pos": float(vertex_pos) if not np.isnan(vertex_pos) else float("nan"),
        "px_vs_ma": float(px_vs_ma) if not np.isnan(px_vs_ma) else float("nan"),
        "ma_last": ma_last,
    }
    return passed, extras
