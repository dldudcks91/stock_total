"""주봉 10MA 트렌드 추종 (long-only).

조건:
- 주봉 종가 > 주봉 SMA(N) → 롱 (1)
- 그 외 → 관망 (0)

엔진은 t -> t+1 체결을 처리하므로 여기선 raw 시그널만 반환.
권장 사용: ``--interval 1w`` (가장 자연스러움). 1d/4h 인터벌도 가능하지만
그 경우 ma_window를 그 인터벌 기준으로 다시 잡아야 (예: 1d면 70).
"""
from __future__ import annotations

import pandas as pd

NAME = "weekly_trend"

DEFAULT_PARAMS = {
    "ma_window": 10,
}


def signal(df: pd.DataFrame, params: dict) -> pd.Series:
    w = int(params.get("ma_window", DEFAULT_PARAMS["ma_window"]))
    if w <= 0:
        raise ValueError(f"ma_window must be > 0, got {w}")

    close = df["close"].astype("float64")
    sma = close.rolling(w, min_periods=w).mean()

    sig = pd.Series(0, index=df.index, dtype="int8")
    sig = sig.where(~(close > sma), 1)
    # warmup 구간(NaN)은 0 유지
    sig = sig.fillna(0).astype("int8")
    return sig
