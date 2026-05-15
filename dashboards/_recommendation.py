"""대시보드 추천 컬럼 — 종목별 최신 봉 기준 전략 점수.

각 종목의 여러 TF 데이터(자산별로 다름)에 대해 여러 전략의 점수를 계산해
가장 강한 추천 1개를 표 한 칸에 표시한다. 자동매매가 아닌 추천 도구 —
score >= 80 인 신호만 켬.

전략 매핑 (stock = KR/US):
  - trend_chase    (1d, 1w)     — "추격" : 장대양봉 + 거래량 폭증
  - trend_pullback (1d, 1w, 1m) — "수렴" : 1차 상승 후 MA10/MA20 비비적
  - quiet_bottom   (1w)         — "바닥" : 조용한 바닥 (binary)

전략 매핑 (crypto):
  - trend_chase    (1h, 4h, 1d, 1w)  — TF별 변동성에 맞춰 ret_th/fresh_big_th 스케일
  - trend_pullback (1h, 4h, 1d, 1w)  — rally_lookback / rally_min_gain TF별 튜닝
  - quiet_bottom   (1w)              — long-term 바닥 패턴 (1w 만 의미)

표시 형식:  "추격d 95" / "수렴4h 85" / "바닥w 100"
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pandas as pd

from backtest.strategies import quiet_bottom, trend_chase, trend_pullback

# (label, code, interval, mod, min_bars, kind, params)
#   kind = "score"  → score(df, params).iloc[-1] 점수 그대로
#   kind = "binary" → signal(df, params).iloc[-1] == 1 이면 100 점
#   params         → 전략 모듈에 추가로 넘길 파라미터 dict (TF별 튜닝). 비우면 default.
_STRATEGY_SPECS_STOCK: list[tuple[str, str, str, object, int, str, dict]] = [
    # 추격 — TF 시간 스케일에 맞춰 fresh 게이트 파라미터 스케일.
    # 일봉: 60봉(3M) 안에 +5% 양봉 ≤2개, 60봉 전 대비 +30% 이내
    # 주봉: 26봉(6M) 안에 +10% 양봉 ≤2개, 26봉 전 대비 +60% 이내 (변동성 큼)
    # min_bars 는 base_lookback + 여유분으로 둬야 게이트가 NaN 으로 떨어지지 않음.
    ("추격", "chase",    "1d", trend_chase,    70,  "score",  {}),
    ("추격", "chase",    "1w", trend_chase,    30,  "score",  {"base_lookback": 26, "fresh_big_th": 0.10, "max_prior_extension": 0.60}),
    # 수렴 (= 눌림목) — rally_lookback 은 각 TF 의 "시간 스케일"에 맞춰 축소.
    # 일봉 60봉 ≈ 3개월 / 주봉 26봉 ≈ 6개월 / 월봉 12봉 ≈ 1년. depth_lookback 도 같이.
    ("수렴", "pullback", "1d", trend_pullback, 70,  "score",  {}),
    ("수렴", "pullback", "1w", trend_pullback, 30,  "score",  {"rally_lookback": 26}),
    ("수렴", "pullback", "1m", trend_pullback, 24,  "score",  {"rally_lookback": 12, "depth_lookback": 12, "react_volume_ma": 12}),
    ("바닥", "quiet",    "1w", quiet_bottom,   120, "binary", {}),
]

# Crypto 봉별 평균 변동성 (BTC 기준 σ): 1h≈1%, 4h≈2%, 1d≈4%, 1w≈10%.
# ret_th / fresh_big_th / max_prior_extension 을 이 스케일에 맞춰 조정.
# base_lookback / rally_lookback 은 "10일/1주/2개월/6개월" 정도의 의미 시간 단위가
# 유지되도록 봉 수로 환산 (1h: 240≈10일, 4h: 60≈10일, 1d: 60≈2개월, 1w: 26≈6개월).
_STRATEGY_SPECS_CRYPTO: list[tuple[str, str, str, object, int, str, dict]] = [
    # ── 추격 (chase) ────────────────────────────────────────────────────
    ("추격", "chase", "1h", trend_chase, 280, "score", {
        "ret_th":  [0.010, 0.015, 0.020, 0.030],
        "ret_pts": [15, 10, 10, 5],
        "base_lookback": 240,        # 10 일
        "fresh_big_th": 0.015,
        "max_prior_extension": 0.20,
        "amount_lookback": 720,      # 30 일치 분위
    }),
    ("추격", "chase", "4h", trend_chase, 90, "score", {
        "ret_th":  [0.020, 0.030, 0.040, 0.060],
        "ret_pts": [15, 10, 10, 5],
        "base_lookback": 60,         # 10 일 (60×4h)
        "fresh_big_th": 0.030,
        "max_prior_extension": 0.25,
        "amount_lookback": 180,      # 30 일치 분위
    }),
    ("추격", "chase", "1d", trend_chase, 70, "score", {
        "ret_th":  [0.04, 0.06, 0.09, 0.13],
        "ret_pts": [15, 10, 10, 5],
        "base_lookback": 60,         # 2 개월 (crypto 24/7)
        "fresh_big_th": 0.06,
        "max_prior_extension": 0.40,
        # amount_lookback default 250 = 1년치 OK
    }),
    ("추격", "chase", "1w", trend_chase, 30, "score", {
        "ret_th":  [0.08, 0.12, 0.17, 0.25],
        "ret_pts": [15, 10, 10, 5],
        "base_lookback": 26,         # 6 개월
        "fresh_big_th": 0.13,
        "max_prior_extension": 0.80,
        "amount_lookback": 100,      # ~2 년치 분위
    }),
    # ── 수렴 (pullback) ────────────────────────────────────────────────
    ("수렴", "pullback", "1h", trend_pullback, 280, "score", {
        "rally_lookback": 168,       # 7 일
        "rally_min_gain": 0.10,
        "depth_lookback": 48,        # 2 일
    }),
    ("수렴", "pullback", "4h", trend_pullback, 90, "score", {
        "rally_lookback": 42,        # 7 일
        "rally_min_gain": 0.15,
        "depth_lookback": 30,        # 5 일
    }),
    ("수렴", "pullback", "1d", trend_pullback, 70, "score", {
        # default rally_lookback=60 (≈2개월), rally_min_gain=0.30 — crypto OK
    }),
    ("수렴", "pullback", "1w", trend_pullback, 30, "score", {
        "rally_lookback": 26,
        "rally_min_gain": 0.60,
    }),
    # ── 바닥 (quiet_bottom) — 1w only ──────────────────────────────────
    ("바닥", "quiet", "1w", quiet_bottom, 120, "binary", {}),
]

# 인터벌 → 라벨 접미사
_IV_SUFFIX = {"1h": "h", "4h": "4h", "1d": "d", "1w": "w", "1m": "m"}

SCORE_THRESHOLD = 80


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


def _last_score(mod, df: pd.DataFrame, kind: str, params: dict) -> float:
    """전략의 마지막 봉 점수. 실패 시 NaN."""
    try:
        if kind == "score":
            s = mod.score(df.reset_index(drop=True), params)
            v = float(s.iloc[-1])
            return v if np.isfinite(v) else np.nan
        # binary
        sig = mod.signal(df.reset_index(drop=True), params)
        return 100.0 if int(sig.iloc[-1]) == 1 else 0.0
    except Exception:
        return np.nan


def compute_recommendations(
    asset: str,
    symbols: list[str],
    loaders: dict,
) -> pd.DataFrame:
    """심볼 리스트 → 추천 DataFrame (symbol, rec_label, rec_score, rec_detail).

    Args:
      asset    : "kr" / "us" / "crypto" — strategy specs 와 norm 함수를 결정.
      symbols  : 처리할 심볼 리스트.
      loaders  : ``{interval: callable(sym) -> Optional[pd.DataFrame]}``.
                 stock 은 ``{"1d": ..., "1w": ..., "1m": ...}``,
                 crypto 는 ``{"1h": ..., "4h": ..., "1d": ..., "1w": ...}``.
                 사용되지 않는 interval 은 누락해도 무방 (해당 spec 만 skip).

    Returns:
      rec_label  : "추격d", "눌림w", "바닥w" 같은 짧은 라벨 (활성 신호 중 최고점)
      rec_score  : 활성 신호의 최고점 (>=80 만 표시, 그 외 NaN)
      rec_detail : 활성 신호 모두 ("추격d 95 / 눌림w 85" 같은 멀티-시그널 표시)
      rec_kind   : "chase" / "pullback" / "quiet" — 색상 구분용
    """
    is_stock = asset in ("kr", "us")
    norm = _norm_stock_df if is_stock else _norm_crypto_df
    specs = _STRATEGY_SPECS_STOCK if is_stock else _STRATEGY_SPECS_CRYPTO
    # specs 가 실제로 요구하는 interval 만 로드 (예: stock 은 1h/4h 안 받음).
    needed_intervals = {spec[2] for spec in specs}

    rows = []
    for sym in symbols:
        result = {
            "symbol": sym,
            "rec_label": None, "rec_score": np.nan,
            "rec_detail": None, "rec_kind": None,
        }
        # interval → normalized df. 누락된 interval (loader 없거나 fail) 은 None.
        dfs: dict = {}
        for iv in needed_intervals:
            loader = loaders.get(iv)
            if loader is None:
                dfs[iv] = None
                continue
            try:
                dfs[iv] = norm(loader(sym))
            except Exception:
                dfs[iv] = None

        candidates: list[tuple[str, str, float, str]] = []  # (label, code, score, kind_name)
        for label, code, interval, mod, min_bars, kind, params in specs:
            df = dfs.get(interval)
            if df is None or df.empty or len(df) < min_bars:
                continue
            s = _last_score(mod, df, kind, params)
            if not np.isfinite(s) or s < SCORE_THRESHOLD:
                continue
            iv_suffix = _IV_SUFFIX.get(interval, interval)
            candidates.append((f"{label}{iv_suffix}", code, s, kind))

        if candidates:
            candidates.sort(key=lambda x: x[2], reverse=True)
            best = candidates[0]
            result["rec_label"] = best[0]
            result["rec_score"] = best[2]
            result["rec_kind"] = best[1]
            # 멀티-시그널 detail (점수 높은 순)
            result["rec_detail"] = " / ".join(f"{lab} {int(round(sc))}" for lab, _, sc, _ in candidates)
        rows.append(result)
    return pd.DataFrame(rows)
