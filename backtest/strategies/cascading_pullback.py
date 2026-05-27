"""'다단계 눌림목' (cascading_pullback) — 장대양봉 후 multi-TF MA10/20/34 풀백 진입.

대시보드 라벨: '다단계 눌림목'
영문 코드명: cascading_pullback

== 직관 ==
1h 에서 첫 임펄스 → 1h 내 미시 풀백/임펄스 누적 → 4h 단위 임펄스로 승격 → 4h 풀백
→ 더 큰 1d 임펄스 → 1d 풀백. 차수가 올라갈수록 추세 강도·holding 기간이 길어짐.

== 임펄스 정의 ==
  bull candle (close > open, body/range > 0.4)
  + body_pct = (close-open)/open >= 임계 (1h:3% / 4h:5% / 1d:7%)
  + vol_rank (직전 30봉 대비) >= 0.85
  + 효력 유지: 현재 close >= impulse_high * 0.50 (절반 위에서 살아있는 한 유효)

== 차수 (tier) — 큰 TF 임펄스가 있으면 승격 ==
  tier 3: 1d 에 살아있는 임펄스 — base 100
  tier 2: 4h 에 살아있는 임펄스 (1d 미충족) — base 60
  tier 1: 1h 에 살아있는 임펄스 (4h/1d 미충족) — base 30
  tier 0: 아무 TF 에도 살아있는 임펄스 없음 — score 0

== 풀백 정의 ==
  tier 의 TF 에서 MA10 / MA20 / MA34 중 하나에 ATR 1.0 단위 이내 접근
  (low 가 MA 아래 또는 close 가 MA 에 ATR<=1.0)

== 점수 ==
  score = tier_base + pullback_proximity_bonus(0~20) + react_bonus(10)
        pullback_proximity_bonus = 20 * (1 - closest_atr / 1.0)   # MA에 가까울수록 +
        react_bonus = 10  if 마지막 봉 회복 양봉 (body/range>0.4)

== 호출 ==
  compute_cascade(df_1h_norm, df_1d_norm=None, params=None) -> dict

  df_*_norm 은 capitalized columns (Open/High/Low/Close/Volume) + DatetimeIndex
  (scripts._common.visual_review.facts._normalize 결과 형태).
"""
from __future__ import annotations
from typing import Optional

import numpy as np
import pandas as pd

NAME = "cascading_pullback"
LABEL_KR = "다단계 눌림목"

DEFAULT_PARAMS = {
    # Impulse body % per TF (close 대비 실체 비율)
    "impulse_body_1h": 0.03,
    "impulse_body_4h": 0.05,
    "impulse_body_1d": 0.07,
    "impulse_vol_rank_min": 0.85,
    # Impulse 효력 유지: close >= impulse_high * holding_min 이어야 살아있음
    "impulse_holding_min": 0.50,

    # Pullback MA 후보 (10, 20, 34)
    "ma_periods": (10, 20, 34),
    "ma_touch_atr": 1.0,           # ATR 1.0 단위 이내 접근시 터치

    # Tier 가중치
    "tier_score": {1: 30.0, 2: 60.0, 3: 100.0},
    "pullback_bonus_max": 20.0,
    "react_bonus": 10.0,

    "score_threshold": 50.0,        # signal 활성 임계
}

_AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df.resample(rule).agg(_AGG).dropna()


def _find_recent_impulse(df: pd.DataFrame, body_min: float, vol_rank_min: float) -> Optional[dict]:
    """가장 최근 impulse 봉 (시간 제한 없음 — 마지막에서 거슬러 첫 발견)."""
    n = len(df)
    if n < 35:
        return None
    vols = df["Volume"]
    for i in range(n - 1, 30, -1):
        bar = df.iloc[i]
        o, h, l, c, v = bar["Open"], bar["High"], bar["Low"], bar["Close"], bar["Volume"]
        if pd.isna(v) or o <= 0:
            continue
        rng = max(h - l, 1e-9)
        body = abs(c - o)
        if not (c > o and body / rng > 0.4):
            continue
        body_pct = float((c - o) / o)
        if body_pct < body_min:
            continue
        prior = vols.iloc[max(0, i - 30):i].dropna()
        if len(prior) < 5:
            continue
        rank = float((prior < v).sum() / len(prior))
        if rank < vol_rank_min:
            continue
        return {
            "bars_ago": n - 1 - i,
            "high": float(h),
            "close_impulse": float(c),
            "body_pct": body_pct,
            "vol_rank": rank,
        }
    return None


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return float("nan")
    h, l, c_prev = df["High"], df["Low"], df["Close"].shift(1)
    tr = pd.concat([h - l, (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean().iloc[-1]
    return float(atr) if not pd.isna(atr) else float("nan")


def _pullback_check(df: pd.DataFrame, ma_periods, touch_atr: float) -> dict:
    """현재 봉이 MA10/20/34 중 하나에 ATR 단위 touch_atr 이내인지."""
    out = {"pullback_ma": None, "distance_atr": None, "closest_atr": None}
    if len(df) < max(ma_periods) + 2:
        return out
    close = float(df["Close"].iloc[-1])
    low = float(df["Low"].iloc[-1])
    atr_val = _atr(df)
    if pd.isna(atr_val) or atr_val <= 0:
        return out

    candidates = []
    for period in ma_periods:
        ma_val = float(df["Close"].rolling(period).mean().iloc[-1])
        if pd.isna(ma_val):
            continue
        dist_atr = (close - ma_val) / atr_val
        touched = (low <= ma_val) or (abs(dist_atr) <= touch_atr)
        if touched:
            candidates.append((f"ma{period}", abs(dist_atr), dist_atr))
    if not candidates:
        return out
    candidates.sort(key=lambda x: x[1])
    name, abs_dist, dist = candidates[0]
    return {"pullback_ma": name, "distance_atr": dist, "closest_atr": abs_dist}


def _bull_recovery(df: pd.DataFrame) -> bool:
    if len(df) == 0:
        return False
    last = df.iloc[-1]
    o, h, l, c = last["Open"], last["High"], last["Low"], last["Close"]
    rng = max(h - l, 1e-9)
    return bool(c > o and (c - o) / rng > 0.4)


def compute_cascade(
    df_1h_norm: pd.DataFrame,
    df_1d_norm: Optional[pd.DataFrame] = None,
    params: Optional[dict] = None,
) -> dict:
    """multi-TF cascade score.

    Args:
      df_1h_norm: 1h OHLCV (정규화. Open/High/Low/Close/Volume + DatetimeIndex).
                  None 이면 4h/1d 만 사용 (1h tier 불가).
      df_1d_norm: 1d OHLCV (옵션 — 없으면 1h 에서 리샘플).
      params: DEFAULT_PARAMS 의 일부 키만 덮어쓰기 가능.
    """
    p = {**DEFAULT_PARAMS, **(params or {})}

    if df_1h_norm is None or len(df_1h_norm) < 200:
        return {"tier": 0, "score": 0.0, "reason": "no_data"}

    df_4h = _resample(df_1h_norm, "4h")
    df_1d = df_1d_norm if (df_1d_norm is not None and len(df_1d_norm) > 0) else _resample(df_1h_norm, "1D")
    if len(df_4h) < 35 or len(df_1d) < 35:
        return {"tier": 0, "score": 0.0, "reason": "insufficient_resample"}

    imp_1h = _find_recent_impulse(df_1h_norm, p["impulse_body_1h"], p["impulse_vol_rank_min"])
    imp_4h = _find_recent_impulse(df_4h, p["impulse_body_4h"], p["impulse_vol_rank_min"])
    imp_1d = _find_recent_impulse(df_1d, p["impulse_body_1d"], p["impulse_vol_rank_min"])

    tier = 0
    impulse_tf = None
    hold = p["impulse_holding_min"]
    if imp_1d and float(df_1d["Close"].iloc[-1]) >= imp_1d["high"] * hold:
        tier = 3
        impulse_tf = "1d"
    elif imp_4h and float(df_4h["Close"].iloc[-1]) >= imp_4h["high"] * hold:
        tier = 2
        impulse_tf = "4h"
    elif imp_1h and float(df_1h_norm["Close"].iloc[-1]) >= imp_1h["high"] * hold:
        tier = 1
        impulse_tf = "1h"

    if tier == 0:
        return {
            "tier": 0,
            "score": 0.0,
            "reason": "no_live_impulse",
            "impulse_1h": imp_1h, "impulse_4h": imp_4h, "impulse_1d": imp_1d,
        }

    pull_df = {1: df_1h_norm, 2: df_4h, 3: df_1d}[tier]
    pull = _pullback_check(pull_df, p["ma_periods"], p["ma_touch_atr"])

    base = p["tier_score"][tier]
    if pull["pullback_ma"] is None:
        # 임펄스는 살아있지만 풀백 자리 아님 — base 만, bonus 0
        score = base * 0.5  # 절반만 반영 (대기 상태)
        react = 0.0
        proximity = 0.0
    else:
        proximity = max(0.0, 1.0 - (pull["closest_atr"] or 0.0) / p["ma_touch_atr"])
        react = p["react_bonus"] if _bull_recovery(pull_df) else 0.0
        score = base + p["pullback_bonus_max"] * proximity + react

    return {
        "tier": tier,
        "impulse_tf": impulse_tf,
        "score": float(score),
        "pullback_ma": pull["pullback_ma"],
        "pullback_dist_atr": pull["distance_atr"],
        "pullback_closest_atr": pull["closest_atr"],
        "react_bull": react > 0,
        "proximity": proximity,
        "impulse_1h_bars_ago": imp_1h["bars_ago"] if imp_1h else None,
        "impulse_4h_bars_ago": imp_4h["bars_ago"] if imp_4h else None,
        "impulse_1d_bars_ago": imp_1d["bars_ago"] if imp_1d else None,
        "impulse_1h_body": imp_1h["body_pct"] if imp_1h else None,
        "impulse_4h_body": imp_4h["body_pct"] if imp_4h else None,
        "impulse_1d_body": imp_1d["body_pct"] if imp_1d else None,
    }


# ── 기존 strategy 인터페이스 호환 (df=1d, score Series 반환) ─────────────────────
# 백테스트 엔진 호환용 wrapper. 매 봉 다시 multi-TF 계산은 비용이 크므로,
# 실제 추천/대시보드 흐름은 compute_cascade() 를 직접 호출.

def signal(df: pd.DataFrame, params: dict) -> pd.Series:
    """현재 봉 시점 기준 score >= threshold 일 때 1.

    df 는 1d (lowercase) 가 표준 strategy 인터페이스. 1h 데이터가 없으므로
    df 를 1h 대체로 사용 (resample 만 1d→ 자기 자신, 4h→ 메모리상 어림).
    멀티-TF 정확도가 필요하면 compute_cascade() 를 직접 호출.
    """
    return (score(df, params) >= float({**DEFAULT_PARAMS, **(params or {})}["score_threshold"])).astype("int8")


def score(df: pd.DataFrame, params: dict) -> pd.Series:
    """단일 TF df 에 대한 score (대시보드 _precompute 호환).

    주의: 정확한 multi-TF cascade 를 원하면 compute_cascade() 를 직접 호출할 것.
    이 wrapper 는 df 를 1d 로 간주하고 1d-only cascade (tier ≤ 3 가능) 를 계산.
    """
    p = {**DEFAULT_PARAMS, **(params or {})}
    # lowercase → capitalized 정규화
    rename = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    df_norm = df.rename(columns=rename)[["Open", "High", "Low", "Close", "Volume"]]
    n = len(df_norm)
    out = pd.Series(0.0, index=df.index, dtype="float64")
    # 마지막 봉 시점만 정확히, 나머지는 0 (백테스트 엔진은 마지막 봉만 쓰는 경우가 많음)
    # 필요 시 sliding window 로 확장 가능.
    if n < 50:
        return out
    res = compute_cascade(df_norm, df_1d_norm=df_norm, params=p)
    out.iloc[-1] = float(res.get("score", 0.0))
    return out


def score_components(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """디버깅용 컴포넌트 (마지막 봉만)."""
    p = {**DEFAULT_PARAMS, **(params or {})}
    rename = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    df_norm = df.rename(columns=rename)[["Open", "High", "Low", "Close", "Volume"]]
    res = compute_cascade(df_norm, df_1d_norm=df_norm, params=p)
    row = {
        "tier": res.get("tier", 0),
        "impulse_tf": res.get("impulse_tf"),
        "score": res.get("score", 0.0),
        "pullback_ma": res.get("pullback_ma"),
        "pullback_closest_atr": res.get("pullback_closest_atr"),
        "proximity": res.get("proximity"),
        "react_bull": res.get("react_bull"),
    }
    return pd.DataFrame([row], index=[df.index[-1]] if len(df) > 0 else [])
