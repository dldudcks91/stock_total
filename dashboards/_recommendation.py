"""대시보드 추천 컬럼 — 종목별 MA20 추세 게이트 (● / 공백).

각 종목에 대해 단일 추세 게이트를 평가해 표 한 칸에 ● 로 표시한다.
백테스트 전략 점수(수렴/추격/바닥)는 사용하지 않는다 — 자산 무관 동일 규칙.

게이트 (자산 공통, 최신 봉 기준):
  - 일봉 close > MA20(20일)
  - 주봉 close > MA20(20주)
  - 주봉 slope_4w(MA20) = MA20w[t] / MA20w[t-4] - 1 ≥ 0

세 조건을 모두 만족하면 ``gate_pass=True``. 산출 컬럼은 ``symbol, gate_pass``
한 쌍이며, ``_precompute`` 가 ``_recs.parquet`` 로 저장하고 라이브 탭이 머지해
``_stock_grid.JS_FMT_REC`` (● 렌더러) 로 표시한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _norm_stock_df(df: pd.DataFrame) -> pd.DataFrame:
    """KR/US 캐시 (대문자 OHLCV) → 전략 모듈이 받는 형식 (소문자 + amount)."""
    if df is None or df.empty:
        return df
    rename = {c: c.lower() for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns}
    out = df.rename(columns=rename)
    if "amount" not in out.columns and "close" in out.columns and "volume" in out.columns:
        out = out.copy()
        out["amount"] = out["close"].astype("float64") * out["volume"].astype("float64")
    return out


def _norm_crypto_df(df: pd.DataFrame) -> pd.DataFrame:
    """Crypto 캐시 (소문자, timestamp ms 컬럼) → 인덱스화."""
    if df is None or df.empty:
        return df
    if "timestamp" in df.columns and not isinstance(df.index, pd.DatetimeIndex):
        out = df.copy()
        out["dt"] = pd.to_datetime(out["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
        out = out.set_index("dt").sort_index()
        return out
    return df


MA_WINDOW = 20      # MA20 (일봉 20일 / 주봉 20주)
SLOPE_WINDOW = 4    # 주봉 slope 4주 정규화 차분


def _gate_pass(d1d: pd.DataFrame, d1w: pd.DataFrame) -> bool:
    """MA20 추세 게이트 — 세 조건 모두 만족하면 True.

    - 일봉 close > MA20(20)
    - 주봉 close > MA20(20)
    - 주봉 slope_4w(MA20) = MA20w[-1] / MA20w[-1-4] - 1 ≥ 0

    데이터 부족·NaN 은 False (미통과). d1d/d1w 는 norm 거친 소문자 'close' 보유.
    """
    if d1d is None or d1d.empty or d1w is None or d1w.empty:
        return False
    if "close" not in d1d.columns or "close" not in d1w.columns:
        return False
    cd, cw = d1d["close"], d1w["close"]
    if len(cd) < MA_WINDOW or len(cw) < MA_WINDOW + SLOPE_WINDOW:
        return False

    ma20d = cd.rolling(MA_WINDOW).mean().iloc[-1]
    ma20w_series = cw.rolling(MA_WINDOW).mean()
    ma20w = ma20w_series.iloc[-1]
    ma20w_prev = ma20w_series.shift(SLOPE_WINDOW).iloc[-1]
    if not (np.isfinite(ma20d) and np.isfinite(ma20w) and np.isfinite(ma20w_prev)) or ma20w_prev == 0:
        return False

    slope_4w = ma20w / ma20w_prev - 1.0
    return bool(
        cd.iloc[-1] > ma20d
        and cw.iloc[-1] > ma20w
        and slope_4w >= 0.0
    )


def compute_recommendations(
    asset: str,
    symbols: list[str],
    loaders: dict,
) -> pd.DataFrame:
    """심볼 리스트 → MA20 게이트 DataFrame (symbol, gate_pass).

    함수명은 호환을 위해 유지 — ``_precompute`` 호출부·머지 배관·``_recs.parquet``
    경로가 그대로 재사용된다. 백테스트 전략 점수는 더 이상 계산하지 않는다.

    Args:
      asset    : "kr" / "us" / "crypto" — norm 함수만 결정 (게이트 규칙은 공통).
      symbols  : 처리할 심볼 리스트.
      loaders  : ``{interval: callable(sym) -> Optional[pd.DataFrame]}``.
                 1d / 1w 로더만 사용 (그 외 interval 은 무시).

    Returns:
      DataFrame[symbol, gate_pass(bool)] — gate_pass True 면 ● 표시.
    """
    is_stock = asset in ("kr", "us")
    norm = _norm_stock_df if is_stock else _norm_crypto_df
    ld_1d = loaders.get("1d")
    ld_1w = loaders.get("1w")

    rows = []
    for sym in symbols:
        try:
            d1d = norm(ld_1d(sym)) if ld_1d is not None else None
        except Exception:
            d1d = None
        try:
            d1w = norm(ld_1w(sym)) if ld_1w is not None else None
        except Exception:
            d1w = None
        rows.append({"symbol": sym, "gate_pass": _gate_pass(d1d, d1w)})
    return pd.DataFrame(rows)
