"""crypto trend_chase — 1d primary + 1h/4h alignment 보너스 멀티 TF 점수.

KR v5.1 (scripts.kr.trend_chase.scoring.score_chase_v5_1) 의 핵심 패턴
(MA10 riding + 강양봉 holding + 진입 시점 페널티) 를 보존하되 crypto 의 다음
특성을 활용:
  - 24/7 거래 → 1h/4h 봉이 의미 있음
  - 변동성 스케일: 1h≈1%, 4h≈2%, 1d≈4%, 1w≈10%
  - 멀티 TF 알라인먼트 (1d 추세 + 4h 가속 + 1h 진입 트리거)

설계 자세히: scripts/crypto/trend_chase/PLAN.md
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from scripts._common.indicators import compute_indicators, compute_weekly_acc


# ─────────────────────────────────────────────────────────────
# Schema bridge — crypto(소문자) → KR style(대문자) for compute_indicators
# ─────────────────────────────────────────────────────────────
def to_kr_schema(df: pd.DataFrame) -> pd.DataFrame:
    """crypto OHLCV (소문자 + timestamp ms) → KR style df (대문자, DatetimeIndex, Change).

    compute_indicators 는 KR/US 대문자 컬럼 가정. 이 헬퍼로 crypto 캐시를 동일 인터페이스로 변환.
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    if "timestamp" in out.columns and not isinstance(out.index, pd.DatetimeIndex):
        out["dt"] = pd.to_datetime(out["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
        out = out.set_index("dt").sort_index()
    rename = {c: c.capitalize() for c in ("open", "high", "low", "close", "volume") if c in out.columns}
    out = out.rename(columns=rename)
    if "Change" not in out.columns and "Close" in out.columns:
        out["Change"] = out["Close"].pct_change().fillna(0)
    return out


# ─────────────────────────────────────────────────────────────
# 1d core (KR v5.1 의 두 패턴 — crypto 스케일 조정)
# ─────────────────────────────────────────────────────────────
def score_chase_1d_core(df_1d: pd.DataFrame) -> pd.Series:
    """compute_indicators 가 add 된 1d df 받아 1d core 점수 Series 반환.

    KR v5.1 대비 변경:
      - ret_30d / ret_90d 임계값 ×2 (crypto 변동성)
      - dist_ma10 페널티 임계값 ×1.5
      - today_chg 페널티 임계값 ×2

    2026-05-27 v2 — fresh 게이트 복구 (backtest/strategies/trend_chase.py 의 원본 로직).
      "이미 큰 추세가 누적된 종목" 컷 — 추격은 추세의 *초입*만 의미가 있음.
      crypto 스케일 ×2 (KR 0.05/0.30 → crypto 0.10/0.50).
    """
    sc = pd.Series(0.0, index=df_1d.index)

    # 공통 — 정배열 + 추세 강도
    bull = (df_1d["bull_stack"] == 1) & (df_1d["Close"] > df_1d["ma10"])
    sc += np.where(bull, 12, 0)
    all_up = (df_1d["ma10_slope"] > 0) & (df_1d["ma20_slope"] > 0) & (df_1d["ma50_slope"] > 0)
    sc += np.where(all_up, 8, 0)

    # 공통 — ret_30d / ret_90d (crypto 스케일: KR ×2)
    sc += np.where(df_1d["ret_30d"] > 2.0, 10, 0)
    sc += np.where(df_1d["ret_30d"].between(1.0, 2.0), 8, 0)
    sc += np.where(df_1d["ret_30d"].between(0.5, 1.0), 7, 0)
    sc += np.where(df_1d["ret_30d"].between(0.3, 0.5), 5, 0)
    sc += np.where(df_1d["ret_30d"].between(0.1, 0.3), 2, 0)
    sc += np.where(df_1d["ret_30d"] < -0.05, -15, 0)

    sc += np.where(df_1d["ret_90d"] > 4.0, 10, 0)
    sc += np.where(df_1d["ret_90d"].between(2.0, 4.0), 8, 0)
    sc += np.where(df_1d["ret_90d"].between(1.0, 2.0), 6, 0)
    sc += np.where(df_1d["ret_90d"].between(0.5, 1.0), 4, 0)
    sc += np.where(df_1d["ret_90d"] < 0, -20, 0)

    # 공통 — 거래량 폭증
    sc += np.where(df_1d["vol_recent_vs_prior"] > 3.0, 10, 0)
    sc += np.where(df_1d["vol_recent_vs_prior"].between(2.0, 3.0), 7, 0)
    sc += np.where(df_1d["vol_recent_vs_prior"].between(1.5, 2.0), 4, 0)
    sc += np.where(df_1d["vol_recent_vs_prior"].between(1.2, 1.5), 2, 0)
    sc += np.where(df_1d["vol_recent_vs_prior"] < 0.7, -5, 0)

    # ─── 패턴 1 — MA10 riding (1d) ───
    sc += np.where((df_1d["ma10_strong_up"] == 1) & (df_1d["Close"] > df_1d["ma10"]), 8, 0)
    sc += np.where(df_1d["ma10_touch_recent_5d"] == 1, 10, 0)
    # dist_ma10 적정 (crypto 스케일: KR 0~0.10 → 0~0.15)
    sc += np.where(df_1d["dist_ma10"].between(0, 0.15), 6, 0)
    # 너무 멀어진 자리 페널티 (crypto 스케일: KR 0.30 → 0.45)
    sc += np.where(df_1d["dist_ma10"] > 0.45, -5, 0)

    # ─── 패턴 2 — 강양봉 후 매도세 X (1d) ───
    sc += np.where(df_1d["today_strong_bull"] == 1, 12, 0)
    sc += np.where(df_1d["bullish_holding"] == 1, 8, 0)
    sc += np.where(df_1d["from_high_1y"] > -0.05, 12, 0)
    sc += np.where(df_1d["from_high_1y"].between(-0.15, -0.05), 8, 0)
    sc += np.where(df_1d["from_high_1y"] < -0.30, -10, 0)

    # 페널티 (KR v5.1 의 today_chg / dist_ma10 페널티 crypto 스케일)
    sc += np.where(df_1d["today_chg"] > 0.30, -20, 0)   # crypto: KR 0.15 → 0.30
    sc += np.where(df_1d["today_chg"].between(0.15, 0.30), -10, 0)
    sc += np.where(df_1d["dist_ma10"] > 0.60, -15, 0)
    sc += np.where(df_1d["dist_ma10"].between(0.45, 0.60), -8, 0)
    sc += np.where(df_1d["bear_stack"] == 1, -25, 0)
    sc += np.where(df_1d["Close"] < df_1d["ma10"], -10, 0)

    # ─── Fresh 게이트 (2026-05-27 추가) ───────────────────────────────
    # 추격은 추세 초입만 의미 있음. "이미 한참 올랐다" 두 조건 OR 충족 시 강제 0점.
    # (a) base_lookback(60봉) 내 +fresh_big_th 이상 양봉이 1개 초과면 컷
    # (b) base_lookback 봉 전 종가 대비 어제 종가 누적 상승이 max_prior_ext 초과면 컷
    # crypto 임계 = KR backtest 의 ×2 (KR 0.05/0.30 → crypto 0.10/0.50).
    FRESH_BIG_TH = 0.10           # +10% 단봉 이상을 "큰 양봉" 으로 간주
    MAX_PRIOR_BIG_COUNT = 1       # 60봉 내 큰 양봉 1개까지 허용
    BASE_LOOKBACK = 60
    MAX_PRIOR_EXTENSION = 0.50    # 60봉 전 대비 어제 종가 +50% 이하

    close = df_1d["Close"]
    ret = close.pct_change()
    big_move = ret >= FRESH_BIG_TH
    prior_big_count = big_move.shift(1).rolling(BASE_LOOKBACK, min_periods=1).sum().fillna(0)
    fresh_a = prior_big_count <= MAX_PRIOR_BIG_COUNT

    prior_close = close.shift(1)
    base_ref = close.shift(BASE_LOOKBACK)
    prior_ext = prior_close / base_ref - 1.0
    fresh_b = (prior_ext <= MAX_PRIOR_EXTENSION).fillna(False)

    fresh = (fresh_a & fresh_b).fillna(False)
    sc = sc.where(fresh, 0.0)

    return sc


# ─────────────────────────────────────────────────────────────
# 4h / 1h alignment 보너스 (1d index 의 해당 시점값을 lookup)
# ─────────────────────────────────────────────────────────────
def _resample_close_volume(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """소문자 crypto df → 임의 rule (e.g. '4h') 로 OHLCV 리샘플."""
    if not isinstance(df.index, pd.DatetimeIndex):
        df = to_kr_schema(df)
    r = df[["Open", "High", "Low", "Close", "Volume"]].resample(rule).agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
    }).dropna()
    return r


def alignment_4h(df_1d_kr: pd.DataFrame, df_1h_kr: pd.DataFrame) -> pd.Series:
    """1h cache 를 4h 리샘플 → bull_stack_4h + ma10_slope_4h + ret_60bars_4h 를 1d 인덱스에 ffill 보너스.

    Returns: 1d index 의 Series (0~10 점)
    """
    if df_1h_kr is None or df_1h_kr.empty:
        return pd.Series(0.0, index=df_1d_kr.index)
    df_4h = _resample_close_volume(df_1h_kr, "4h")
    if len(df_4h) < 60:
        return pd.Series(0.0, index=df_1d_kr.index)
    c = df_4h["Close"]
    ma10 = c.rolling(10).mean()
    ma20 = c.rolling(20).mean()
    ma50 = c.rolling(50).mean()
    bull_4h = ((ma10 > ma20) & (ma20 > ma50)).astype(int)
    ma10_slope_4h = ma10.pct_change(5)
    ret_60_4h = c.pct_change(60)

    bonus_4h = pd.Series(0.0, index=df_4h.index)
    bonus_4h += np.where((bull_4h == 1) & (ma10_slope_4h > 0), 5, 0)
    bonus_4h += np.where(ret_60_4h > 0.20, 5, 0)

    # 1d 인덱스에 ffill (각 일자 cutoff 시점의 last 4h 값)
    return bonus_4h.reindex(df_1d_kr.index, method="ffill").fillna(0)


def alignment_1h(df_1d_kr: pd.DataFrame, df_1h_kr: pd.DataFrame) -> pd.Series:
    """1h cache 직접 사용: 거래량 폭증 (24h vs 72h prior) + 1h MA20 정배열.

    Returns: 1d index 의 Series (0~10 점)
    """
    if df_1h_kr is None or df_1h_kr.empty:
        return pd.Series(0.0, index=df_1d_kr.index)
    if len(df_1h_kr) < 100:
        return pd.Series(0.0, index=df_1d_kr.index)
    v = df_1h_kr["Volume"]
    vol_24h = v.rolling(24).sum()
    vol_prior_72h = v.shift(24).rolling(72).sum()
    vol_burst = vol_24h / vol_prior_72h.replace(0, np.nan)

    c = df_1h_kr["Close"]
    ma20_1h = c.rolling(20).mean()
    ma20_slope_1h = ma20_1h.pct_change(20)
    above_ma20 = (c > ma20_1h) & (ma20_slope_1h > 0)

    bonus_1h = pd.Series(0.0, index=df_1h_kr.index)
    bonus_1h += np.where(vol_burst > 2.0, 6, 0)
    bonus_1h += np.where(above_ma20, 4, 0)

    return bonus_1h.reindex(df_1d_kr.index, method="ffill").fillna(0)


def entry_timing_penalty_1h(df_1d_kr: pd.DataFrame, df_1h_kr: pd.DataFrame) -> pd.Series:
    """직전 24h 누적등락률, 4h ret, 1h dist_ma10 페널티 (1d 인덱스로 ffill).

    Returns: 1d index 의 음수 Series (0 또는 -8~-30)
    """
    if df_1h_kr is None or df_1h_kr.empty:
        return pd.Series(0.0, index=df_1d_kr.index)
    if len(df_1h_kr) < 100:
        return pd.Series(0.0, index=df_1d_kr.index)
    c = df_1h_kr["Close"]
    ret_24h = c.pct_change(24)
    ret_4h = c.pct_change(4)
    ma10_1h = c.rolling(10).mean()
    dist_ma10_1h = c / ma10_1h - 1

    pen = pd.Series(0.0, index=df_1h_kr.index)
    pen += np.where(ret_24h > 0.20, -15, 0)        # 너무 늦은 진입
    pen += np.where(ret_4h > 0.10, -10, 0)         # 직전 4h 폭등
    pen += np.where(dist_ma10_1h > 0.20, -8, 0)    # 1h MA10 너무 멀어짐

    return pen.reindex(df_1d_kr.index, method="ffill").fillna(0)


# ─────────────────────────────────────────────────────────────
# 통합 점수
# ─────────────────────────────────────────────────────────────
def score_chase_crypto(
    df_1d: pd.DataFrame,
    df_1h: Optional[pd.DataFrame] = None,
) -> pd.Series:
    """crypto trend_chase 통합 점수 — 1d primary + 1h 멀티 TF 보너스/페널티.

    Args:
      df_1d : 1d 일봉 (crypto 캐시 소문자 OR KR 스타일 대문자 OK)
      df_1h : 1h 캐시 (선택). None 이면 1d core 만 사용 (멀티 TF 보너스/페널티 0)

    Returns:
      Series with 1d index. Score range approx [-50, 115]. 운영 threshold 는 백테스트 후 결정.
    """
    df_1d_kr = to_kr_schema(df_1d) if "Close" not in df_1d.columns else df_1d
    df_1d_kr = compute_indicators(df_1d_kr)
    df_1d_kr["acc_w"] = compute_weekly_acc(df_1d_kr)

    sc = score_chase_1d_core(df_1d_kr)

    if df_1h is not None and not df_1h.empty:
        df_1h_kr = to_kr_schema(df_1h) if "Close" not in df_1h.columns else df_1h
        sc = sc + alignment_4h(df_1d_kr, df_1h_kr)
        sc = sc + alignment_1h(df_1d_kr, df_1h_kr)
        sc = sc + entry_timing_penalty_1h(df_1d_kr, df_1h_kr)

    return sc


# 점수 최대값 (페널티 제외, 보수적)
CH_CRYPTO_MAX = 115


# ─────────────────────────────────────────────────────────────
# v3 — TF 무관 vectorized chase 점수 Series (1h/4h/1d 공통 인터페이스)
# ─────────────────────────────────────────────────────────────
# 위의 score_chase_crypto 는 1d primary + 1h/4h alignment 보너스 (싱글 호출용).
# 이 함수는 임의 TF df 를 받아 그 TF 시계열 전체의 score Series 를 반환 — mtf_recs 처럼
# 1h, 4h, 1d 를 각각 채점한 뒤 합산하는 용도.
# ─────────────────────────────────────────────────────────────
def score_chase_crypto_tf(df: pd.DataFrame) -> pd.Series:
    """crypto OHLCV (lowercase) 또는 KR style (uppercase) df → score_chase_1d_core Series.

    입력 df 의 timeframe 은 자동으로 해석됨. compute_indicators 가 add 하는 rolling
    윈도우 (10/30/252 bars) 가 TF 별로 다른 시간 의미를 가짐 — 의도된 동작.

    Args:
      df : OHLCV. crypto 캐시 (timestamp + lowercase) 또는 KR style 둘 다 OK.

    Returns:
      pd.Series, index = df 의 DatetimeIndex, dtype=float64.
    """
    if df is None or df.empty:
        return pd.Series(dtype="float64")

    if "Close" not in df.columns:
        df_kr = to_kr_schema(df)
    else:
        df_kr = df.copy()
        if not isinstance(df_kr.index, pd.DatetimeIndex) and "timestamp" in df_kr.columns:
            df_kr = to_kr_schema(df_kr)
    if df_kr.empty or "Close" not in df_kr.columns:
        return pd.Series(dtype="float64", index=df.index)

    df_ind = compute_indicators(df_kr)
    sc = score_chase_1d_core(df_ind)
    # 음수는 0 으로 floor — pullback 과 일관성 유지
    return sc.clip(lower=0).fillna(0)


# ═════════════════════════════════════════════════════════════════════════════
# v3 (2026-05-27) — MTF MA10 bounce 추세 타기
# ═════════════════════════════════════════════════════════════════════════════
# 사용자 설계 의도: "1h+4h+1d MA10>MA20 정배열이고 1h MA10 위에서 2~3번 튕기는 자리"
#   - 강양봉/거래량 폭증 컴포넌트 제거
#   - MA10 bounce 횟수 (1h, 48h lookback, debounce 적용) 가 메인 점수
#   - 1h+4h+1d 정배열 + 1d fresh 게이트 (모두 통과해야 점수 살아남음)
# ═════════════════════════════════════════════════════════════════════════════


def _ma10_bounces_1h(df_1h_ind: pd.DataFrame, lookback_bars: int = 48,
                     touch_pct: float = 0.005, debounce_bars: int = 4) -> pd.Series:
    """1h 봉에서 MA10 터치 + close>MA10 회복 한 bounce 의 trailing lookback 카운트.

    Args:
      df_1h_ind : compute_indicators 적용된 1h KR-style df (ma10 컬럼 필수)
      lookback_bars : trailing 윈도우 (48h 기본)
      touch_pct : low <= ma10 * (1 + touch_pct) 면 터치로 인정 (0.5%)
      debounce_bars : 이 봉 수 안에 이미 bounce 있었으면 같은 클러스터 (1회로 처리)
    """
    low = df_1h_ind["Low"]
    close = df_1h_ind["Close"]
    ma10 = df_1h_ind["ma10"]
    touched = low <= ma10 * (1.0 + touch_pct)
    recovered = close > ma10
    bounce = (touched & recovered).fillna(False)
    prev_cluster = (bounce.rolling(debounce_bars, min_periods=1).max()
                          .shift(1).fillna(0).astype(bool))
    bounce_first = bounce & ~prev_cluster
    return bounce_first.rolling(lookback_bars, min_periods=1).sum()


def _fresh_gate_1d(df_1d_ind: pd.DataFrame, fresh_big_th: float = 0.10,
                   max_prior_big_count: int = 1, base_lookback: int = 60,
                   max_prior_ext: float = 0.50) -> pd.Series:
    """기존 score_chase_1d_core 의 fresh 게이트 — boolean Series (1d index)."""
    close = df_1d_ind["Close"]
    ret = close.pct_change()
    big_move = ret >= fresh_big_th
    prior_big_count = big_move.shift(1).rolling(base_lookback, min_periods=1).sum().fillna(0)
    fresh_a = prior_big_count <= max_prior_big_count
    prior_ext = close.shift(1) / close.shift(base_lookback) - 1.0
    fresh_b = (prior_ext <= max_prior_ext).fillna(False)
    return (fresh_a & fresh_b).fillna(False)


def score_chase_mtf(
    df_1h: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_1d: pd.DataFrame,
    *,
    bounce_lookback_1h: int = 48,
) -> pd.Series:
    """v3 chase — MTF MA10 bounce 추세 타기. 1h index Series 반환 (0~100).

    하드 게이트 (전부 충족해야 점수 0 이상):
      1) 1h MA10 > MA20  (정배열 = bull_stack 의 약식, MA10>MA20만 봄)
      2) 4h MA10 > MA20
      3) 1d MA10 > MA20 > MA50  (full bull_stack)
      4) 1d fresh (60일 누적 +50% 이하 + 60일내 +10% 큰양봉 1개 이하)

    점수 컴포넌트 (게이트 통과 시):
      (a) 1h MA10 bounce 횟수 (48h)         : 2~3회 +60, 1회 +20, 4+회 +30
      (b) 현재 1h close > MA10               : +20
      (c) 1h MA10 slope > 0 (5봉 변화율)     : +10
      (d) 4h close > MA10                    : +10
      → max 100, 게이트 통과 시 실효 분포 ≈ 20~100

    Returns: pd.Series, 1h DatetimeIndex.
    """
    if df_1h is None or df_1h.empty:
        return pd.Series(dtype="float64")

    # Schema normalize
    df_1h_kr = to_kr_schema(df_1h) if "Close" not in df_1h.columns else df_1h
    df_4h_kr = to_kr_schema(df_4h) if "Close" not in df_4h.columns else df_4h
    df_1d_kr = to_kr_schema(df_1d) if "Close" not in df_1d.columns else df_1d

    # 데이터 길이 컷
    if len(df_1h_kr) < 100 or len(df_4h_kr) < 50 or len(df_1d_kr) < 70:
        return pd.Series(0.0, index=df_1h_kr.index)

    # 지표 add
    df_1h_ind = compute_indicators(df_1h_kr)
    df_4h_ind = compute_indicators(df_4h_kr)
    df_1d_ind = compute_indicators(df_1d_kr)

    # 게이트 — 1h+4h+1d 정배열
    bull_1h = (df_1h_ind["ma10"] > df_1h_ind["ma20"]).fillna(False)
    bull_4h = (df_4h_ind["ma10"] > df_4h_ind["ma20"]).fillna(False) \
              .reindex(df_1h_ind.index, method="ffill").fillna(False)
    bull_1d = (df_1d_ind["bull_stack"] == 1).fillna(False) \
              .reindex(df_1h_ind.index, method="ffill").fillna(False)

    # 게이트 — 1d fresh
    fresh_1d = _fresh_gate_1d(df_1d_ind) \
               .reindex(df_1h_ind.index, method="ffill").fillna(False)

    gates_pass = bull_1h & bull_4h & bull_1d & fresh_1d

    # 컴포넌트 점수
    bounces = _ma10_bounces_1h(df_1h_ind, lookback_bars=bounce_lookback_1h)
    sc = pd.Series(0.0, index=df_1h_ind.index)

    # (a) bounce 카운트 — 2~3회 sweet, 1회 약함, 4+회는 횡보 가능성
    sc = sc + np.where(bounces.between(2, 3), 60, 0)
    sc = sc + np.where(bounces == 1, 20, 0)
    sc = sc + np.where(bounces >= 4, 30, 0)

    # (b) 현재 close > 1h MA10 (지금 위에 있나)
    sc = sc + np.where(df_1h_ind["Close"] > df_1h_ind["ma10"], 20, 0)

    # (c) 1h MA10 slope 상승
    sc = sc + np.where(df_1h_ind["ma10_slope"] > 0, 10, 0)

    # (d) 4h close > 4h MA10
    above_ma10_4h = (df_4h_ind["Close"] > df_4h_ind["ma10"]).fillna(False) \
                    .reindex(df_1h_ind.index, method="ffill").fillna(False)
    sc = sc + np.where(above_ma10_4h, 10, 0)

    # 하드 게이트 적용
    sc = sc.where(gates_pass, 0.0)
    return sc.clip(lower=0).fillna(0)


# 점수 max (페널티 X)
CH_MTF_MAX = 100


# ═════════════════════════════════════════════════════════════════════════════
# v2 — 1h primary entry timing 점수 (사용자 의도: "지금 타기 좋은 타점")
# ═════════════════════════════════════════════════════════════════════════════
# 위의 score_chase_crypto (1d primary) 는 백테스트 / D+N hold 평가용으로 보존.
# 추천 (현재 시점 진입) 은 1h 봉 시점에 평가해야 함 — 사용자 (2026-05-26) 명시:
#   "crypto 는 1h 와 4h 기준으로 계산되어야 함. 추천은 결국 타기 좋은 타점에
#    지금 있냐가 중요"
# ─────────────────────────────────────────────────────────────────────────────


def _compute_1h_indicators(df_1h_kr: pd.DataFrame) -> pd.DataFrame:
    """1h df 에 1h-scale 지표 add. KR compute_indicators 의 1h 버전.

    시간 단위 (KR 일봉 → crypto 1h 매핑):
      MA10/20/50 (10h/20h/50h)  ≈  KR MA5/10/25 (5d/10d/25d)
      ret_24h / ret_72h / ret_168h  ≈  KR ret_5d / ret_15d / ret_30d 정도
      vol_24h_vs_72h               ≈  KR vol_recent_vs_prior (10d/30d)
    """
    df = df_1h_kr.copy()
    c = df["Close"]
    o = df["Open"]
    v = df["Volume"]

    # MA + slope (slope = 10시간 전 대비 변화)
    df["ma10_1h"] = c.rolling(10).mean()
    df["ma20_1h"] = c.rolling(20).mean()
    df["ma50_1h"] = c.rolling(50).mean()
    df["ma10_slope_1h"] = df["ma10_1h"].pct_change(10)
    df["ma20_slope_1h"] = df["ma20_1h"].pct_change(20)

    df["dist_ma10_1h"] = c / df["ma10_1h"] - 1
    df["dist_ma20_1h"] = c / df["ma20_1h"] - 1

    df["bull_stack_1h"] = ((df["ma10_1h"] > df["ma20_1h"]) & (df["ma20_1h"] > df["ma50_1h"])).astype(int)
    df["bear_stack_1h"] = ((df["ma10_1h"] < df["ma20_1h"]) & (df["ma20_1h"] < df["ma50_1h"])).astype(int)

    # ret 시간 단위
    df["ret_4h"] = c.pct_change(4)
    df["ret_24h"] = c.pct_change(24)
    df["ret_72h"] = c.pct_change(72)
    df["ret_168h"] = c.pct_change(168)   # 1주

    # 거래량 burst (24h 합 vs 직전 72h 평균-72h 환산)
    df["vol_24h_vs_72h"] = v.rolling(24).sum() / v.shift(24).rolling(72).sum()

    # 캔들 body + 분위
    df["body_1h"] = (c - o) / o
    df["vol_rank_72h"] = v.rolling(72).rank(pct=True)

    # MA10 riding (1h): 직전 12h 안에 1h MA10 가까이 닿은 적이 있는지
    df["ma10_touch_recent_12h"] = (df["dist_ma10_1h"].abs() < 0.02).rolling(12).max().fillna(0)
    df["ma10_strong_up_1h"] = (df["ma10_slope_1h"] > 0.02).astype(int)

    # MA20 riding (1h): 더 깊은 풀백 진입 자리. 24h 안에 MA20 ±3% 터치 + slope up
    df["ma20_touch_recent_24h"] = (df["dist_ma20_1h"].abs() < 0.03).rolling(24).max().fillna(0)
    df["ma20_strong_up_1h"] = (df["ma20_slope_1h"] > 0.015).astype(int)
    # nearest-MA distance — MA10 또는 MA20 둘 중 가까운 것까지의 절대거리
    df["dist_nearest_ma_1h"] = np.minimum(df["dist_ma10_1h"].abs(), df["dist_ma20_1h"].abs())

    # 강양봉 + holding (1h)
    df["strong_bull_1h"] = ((df["body_1h"] > 0.02) & (df["vol_rank_72h"] > 0.85)).astype(int)
    df["recent_strong_bull_24h"] = df["strong_bull_1h"].rolling(24).max().fillna(0)
    df["bullish_holding_1h"] = ((df["recent_strong_bull_24h"] == 1) & (c > df["ma10_1h"])).astype(int)

    # 4h 알라인먼트 (1h 봉의 trailing 4 bars 종합)
    df["close_4h_close"] = c                 # 4h close = 1h close
    df["high_4h"] = c.rolling(4).max()
    df["low_4h"] = c.rolling(4).min()

    return df


def _last_4h_alignment(df_1h: pd.DataFrame) -> tuple[float, float, float]:
    """1h cache 를 4h 리샘플 → last bar 의 bull_stack_4h, ma10_slope_4h, ret_60_4h."""
    if df_1h is None or df_1h.empty:
        return 0.0, 0.0, 0.0
    if not isinstance(df_1h.index, pd.DatetimeIndex):
        df_1h = to_kr_schema(df_1h)
    r = df_1h[["Close"]].resample("4h").agg({"Close": "last"}).dropna()
    if len(r) < 60:
        return 0.0, 0.0, 0.0
    c = r["Close"]
    ma10 = c.rolling(10).mean()
    ma20 = c.rolling(20).mean()
    ma50 = c.rolling(50).mean()
    bull = 1.0 if (ma10.iloc[-1] > ma20.iloc[-1] > ma50.iloc[-1]) else 0.0
    slope = float(ma10.pct_change(5).iloc[-1])
    ret60 = float(c.pct_change(60).iloc[-1])
    return bull, slope, ret60


def _last_1d_alignment(df_1d: pd.DataFrame) -> tuple[float, float, float, float]:
    """1d 마지막 봉 시점에서 1d 추세 confirm 값."""
    if df_1d is None or df_1d.empty:
        return 0.0, 0.0, 0.0, 0.0
    if "Close" not in df_1d.columns:
        df_1d = to_kr_schema(df_1d)
    if len(df_1d) < 60:
        return 0.0, 0.0, 0.0, 0.0
    c = df_1d["Close"]
    ma10 = c.rolling(10).mean()
    ma20 = c.rolling(20).mean()
    ma50 = c.rolling(50).mean()
    bull = 1.0 if (ma10.iloc[-1] > ma20.iloc[-1] > ma50.iloc[-1]) else 0.0
    ret30 = float(c.pct_change(30).iloc[-1])
    ret90 = float(c.pct_change(90).iloc[-1]) if len(df_1d) >= 90 else 0.0
    from_high = float(c.iloc[-1] / c.rolling(252).max().iloc[-1] - 1) if len(df_1d) >= 252 else 0.0
    return bull, ret30, ret90, from_high


def score_chase_entry_1h(
    df_1h: pd.DataFrame,
    df_1d: Optional[pd.DataFrame] = None,
) -> tuple[float, dict]:
    """**현재 시점 진입 점수** — 1h 봉 last row 기준 (사용자 의도: "지금 타점").

    KR v5.1 의 두 패턴 (MA10 riding + 강양봉 holding) 을 1h 봉으로 변환.
    4h 알라인먼트 + 1d 추세 confirm + 진입 시점 페널티 포함.

    Args:
      df_1h : 1h OHLCV (필수). KR 스타일 (대문자) 또는 crypto 원본 (소문자) 둘 다 OK.
      df_1d : 1d OHLCV (선택, alignment confirm 용).

    Returns:
      (score, components_dict)
      score : float (페널티 제외 max ≈ 115)
      components : 디버깅용 — last 1h row 의 indicator 값 + 부분 점수
    """
    df_1h_kr = to_kr_schema(df_1h) if "Close" not in df_1h.columns else df_1h
    df_1h_ind = _compute_1h_indicators(df_1h_kr)

    if len(df_1h_ind) < 168:
        return 0.0, {"reason": "1h data < 168 (1주) bars"}

    last = df_1h_ind.iloc[-1]
    sc = 0.0
    parts = {}

    # ─── 1h primary score (40+) ─────────────────────────────────────────
    # 1) 1h 정배열 + 추세 강도
    if last["bull_stack_1h"] == 1 and last["Close"] > last["ma10_1h"]:
        sc += 12; parts["bull_stack_1h"] = 12
    all_up_1h = (last["ma10_slope_1h"] > 0) and (last["ma20_slope_1h"] > 0)
    if all_up_1h:
        sc += 8; parts["all_up_1h"] = 8

    # 2) ret_24h / ret_72h (단기 추세 — crypto 변동성 1h ≈ 1%, 24h ≈ 4%)
    r24, r72 = float(last["ret_24h"] or 0), float(last["ret_72h"] or 0)
    if r24 > 0.20: sc += 10
    elif r24 > 0.10: sc += 7
    elif r24 > 0.05: sc += 5
    elif r24 > 0.02: sc += 3
    elif r24 < -0.05: sc -= 10
    parts["ret_24h_pts"] = sc - sum(parts.values())

    if r72 > 0.50: sc += 10
    elif r72 > 0.30: sc += 8
    elif r72 > 0.15: sc += 5
    elif r72 > 0.05: sc += 3
    elif r72 < 0: sc -= 8
    parts["ret_72h_pts"] = sc - sum(parts.values())

    # 3) 거래량 burst (1h 단위) — 추격의 핵심
    vb = float(last["vol_24h_vs_72h"] or 0)
    if vb > 3.0: sc += 12
    elif vb > 2.0: sc += 8
    elif vb > 1.5: sc += 5
    elif vb > 1.2: sc += 2
    elif vb < 0.7: sc -= 5
    parts["vol_burst_pts"] = sc - sum(parts.values())

    # ─── 패턴 1 — 1h MA riding (MA10 OR MA20 — 둘 다 valid 진입 자리) ────
    # MA10 (단기 풀백 — 강한 추세 위)
    if last["ma10_strong_up_1h"] == 1 and last["Close"] > last["ma10_1h"]:
        sc += 6; parts["ma10_strong_up_1h"] = 6
    if last["ma10_touch_recent_12h"] == 1:
        sc += 8; parts["ma10_touch_recent_12h"] = 8
    dist_10 = float(last["dist_ma10_1h"] or 0)
    if 0 <= dist_10 <= 0.05:
        sc += 5; parts["dist_ma10_sweet"] = 5

    # MA20 (깊은 풀백 — 추세 유지 중 더 멀리 조정 후 진입)
    if last["ma20_strong_up_1h"] == 1 and last["Close"] > last["ma20_1h"]:
        sc += 5; parts["ma20_strong_up_1h"] = 5
    if last["ma20_touch_recent_24h"] == 1:
        sc += 7; parts["ma20_touch_recent_24h"] = 7
    dist_20 = float(last["dist_ma20_1h"] or 0)
    if 0 <= dist_20 <= 0.08:
        sc += 4; parts["dist_ma20_sweet"] = 4

    # 진입 페널티: **가장 가까운 MA** 까지의 거리가 너무 크면 (둘 다 멀어진 자리)
    dist_nearest = float(last["dist_nearest_ma_1h"] or 0)
    if dist_nearest > 0.20:
        sc -= 18; parts["dist_nearest_too_far"] = -18
    elif dist_nearest > 0.12:
        sc -= 10; parts["dist_nearest_far"] = -10
    elif dist_nearest > 0.08:
        sc -= 4; parts["dist_nearest_warm"] = -4

    # ─── 패턴 2 — 1h 강양봉 후 매도세 X ─────────────────────────────────
    if last["strong_bull_1h"] == 1:
        sc += 10; parts["strong_bull_1h"] = 10
    if last["bullish_holding_1h"] == 1:
        sc += 8; parts["bullish_holding_1h"] = 8

    # ─── 4h alignment confirm ──────────────────────────────────────────
    bull_4h, slope_4h, ret60_4h = _last_4h_alignment(df_1h_kr)
    if bull_4h == 1 and slope_4h > 0:
        sc += 6; parts["bull_4h_alignment"] = 6
    if ret60_4h > 0.20:
        sc += 4; parts["ret60_4h"] = 4

    # ─── 1d 추세 confirm ────────────────────────────────────────────────
    if df_1d is not None and not df_1d.empty:
        bull_1d, ret30_1d, ret90_1d, fh_1d = _last_1d_alignment(df_1d)
        if bull_1d == 1:
            sc += 4; parts["bull_1d"] = 4
        if ret30_1d > 0.30:
            sc += 4; parts["ret30_1d_strong"] = 4
        elif ret30_1d < -0.05:
            sc -= 8; parts["ret30_1d_neg"] = -8
        if ret90_1d > 1.0:
            sc += 4; parts["ret90_1d_strong"] = 4
        elif ret90_1d < 0:
            sc -= 10; parts["ret90_1d_neg"] = -10
        # 신고가 근접 (1d 1y)
        if fh_1d > -0.05:
            sc += 4; parts["near_1y_high"] = 4
        elif fh_1d < -0.30:
            sc -= 5; parts["deep_drawdown"] = -5

    # ─── 진입 시점 페널티 (1h 봉) ────────────────────────────────────────
    ret4h_last = float(last["ret_4h"] or 0)
    if ret4h_last > 0.10:
        sc -= 12; parts["ret_4h_pump"] = -12
    elif ret4h_last > 0.05:
        sc -= 5; parts["ret_4h_warm"] = -5
    if r24 > 0.30:
        sc -= 15; parts["ret_24h_overheated"] = -15

    # 페널티: 1h 역배열
    if last["bear_stack_1h"] == 1:
        sc -= 20; parts["bear_stack_1h"] = -20
    if last["Close"] < last["ma10_1h"]:
        sc -= 8; parts["below_ma10_1h"] = -8

    # 디버깅용 핵심 row 값 add
    parts["_last_ts"] = df_1h_ind.index[-1]
    parts["_close"] = float(last["Close"])
    parts["_dist_ma10_1h"] = round(dist_10, 4)
    parts["_dist_ma20_1h"] = round(dist_20, 4)
    parts["_dist_nearest_1h"] = round(dist_nearest, 4)
    parts["_ret_4h"] = round(ret4h_last, 4)
    parts["_ret_24h"] = round(r24, 4)
    parts["_ret_72h"] = round(r72, 4)
    parts["_vol_burst"] = round(vb, 2)
    parts["_bull_stack_1h"] = int(last["bull_stack_1h"])
    parts["_bull_4h_align"] = int(bull_4h)
    parts["_ma10_strong_up_1h"] = int(last["ma10_strong_up_1h"])
    parts["_ma20_strong_up_1h"] = int(last["ma20_strong_up_1h"])

    return round(sc, 1), parts


# entry score 최대값 (페널티 제외)
# 1h: 정배열(20)+ret(30)+volburst(12)+MA10(19)+MA20(16)+패턴2(18)+4h(10)+1d(16) = ~141
CH_ENTRY_MAX = 130


# ═════════════════════════════════════════════════════════════════════════════
# v2 — 4h primary entry timing 점수
# ═════════════════════════════════════════════════════════════════════════════
# 같은 KR v5.1 패턴을 4h 봉 단위로. 1h cache 를 내부에서 4h 리샘플.
# 시간 horizon 은 동일하게 24h/72h/168h 유지 (bar count = horizon/4h).
# ─────────────────────────────────────────────────────────────────────────────


def _resample_1h_to_4h(df_1h_kr: pd.DataFrame) -> pd.DataFrame:
    """1h KR-style df → 4h OHLCV."""
    if not isinstance(df_1h_kr.index, pd.DatetimeIndex):
        df_1h_kr = to_kr_schema(df_1h_kr)
    return df_1h_kr[["Open", "High", "Low", "Close", "Volume"]].resample("4h").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
    }).dropna()


def _compute_4h_indicators(df_4h: pd.DataFrame) -> pd.DataFrame:
    """4h 봉 entry indicators. 1h 의 시간 horizon 유지, bar count = horizon/4.

    매핑 (시간 단위 동일, bar count 만 다름):
      ret_24h  = 6 bars
      ret_72h  = 18 bars
      ret_168h = 42 bars
      ma10_touch_recent_12h = 3 bars (12h)
      vol_24h_vs_72h = rolling(6).sum() / shift(6).rolling(18).sum()
    MA10/20/50 (4h × 10/20/50 = 40h/80h/200h) — 1h 의 10h/20h/50h 보다 더 긴 trend.
    """
    df = df_4h.copy()
    c = df["Close"]
    o = df["Open"]
    v = df["Volume"]

    df["ma10_4h"] = c.rolling(10).mean()
    df["ma20_4h"] = c.rolling(20).mean()
    df["ma50_4h"] = c.rolling(50).mean()
    df["ma10_slope_4h"] = df["ma10_4h"].pct_change(10)
    df["ma20_slope_4h"] = df["ma20_4h"].pct_change(20)

    df["dist_ma10_4h"] = c / df["ma10_4h"] - 1
    df["dist_ma20_4h"] = c / df["ma20_4h"] - 1

    df["bull_stack_4h"] = ((df["ma10_4h"] > df["ma20_4h"]) & (df["ma20_4h"] > df["ma50_4h"])).astype(int)
    df["bear_stack_4h"] = ((df["ma10_4h"] < df["ma20_4h"]) & (df["ma20_4h"] < df["ma50_4h"])).astype(int)

    df["ret_1bar"] = c.pct_change(1)   # 1 bar = 4h (1h 의 ret_4h 와 같음)
    df["ret_24h"] = c.pct_change(6)
    df["ret_72h"] = c.pct_change(18)
    df["ret_168h"] = c.pct_change(42)

    df["vol_24h_vs_72h"] = v.rolling(6).sum() / v.shift(6).rolling(18).sum()

    df["body_4h"] = (c - o) / o
    df["vol_rank_30bars"] = v.rolling(30).rank(pct=True)   # 30×4h = 5일

    df["ma10_touch_recent_12h"] = (df["dist_ma10_4h"].abs() < 0.02).rolling(3).max().fillna(0)
    df["ma10_strong_up_4h"] = (df["ma10_slope_4h"] > 0.02).astype(int)

    # MA20 riding (4h): 24h = 6 bars 안에 MA20 ±3% 터치
    df["ma20_touch_recent_24h"] = (df["dist_ma20_4h"].abs() < 0.03).rolling(6).max().fillna(0)
    df["ma20_strong_up_4h"] = (df["ma20_slope_4h"] > 0.015).astype(int)
    df["dist_nearest_ma_4h"] = np.minimum(df["dist_ma10_4h"].abs(), df["dist_ma20_4h"].abs())

    df["strong_bull_4h"] = ((df["body_4h"] > 0.04) & (df["vol_rank_30bars"] > 0.85)).astype(int)
    df["recent_strong_bull_24h"] = df["strong_bull_4h"].rolling(6).max().fillna(0)
    df["bullish_holding_4h"] = ((df["recent_strong_bull_24h"] == 1) & (c > df["ma10_4h"])).astype(int)

    return df


def score_chase_entry_4h(
    df_1h: pd.DataFrame,
    df_1d: Optional[pd.DataFrame] = None,
) -> tuple[float, dict]:
    """4h 봉 primary entry score. 1h cache 를 내부에서 4h 로 리샘플.

    score_chase_entry_1h 와 동일한 가중치 패턴이지만:
      - 4h 봉 자체의 정배열/추세 강도 (더 긴 시간 의미)
      - dist_ma10_4h, ret_1bar(=4h ret) 페널티 임계는 4h σ ≈ 2% 고려
    """
    df_1h_kr = to_kr_schema(df_1h) if "Close" not in df_1h.columns else df_1h
    df_4h = _resample_1h_to_4h(df_1h_kr)
    df_4h_ind = _compute_4h_indicators(df_4h)

    if len(df_4h_ind) < 42:
        return 0.0, {"reason": "4h data < 42 bars (1주)"}

    last = df_4h_ind.iloc[-1]
    sc = 0.0
    parts = {}

    # 1) 4h 정배열 + 추세 강도
    if last["bull_stack_4h"] == 1 and last["Close"] > last["ma10_4h"]:
        sc += 12; parts["bull_stack_4h"] = 12
    all_up = (last["ma10_slope_4h"] > 0) and (last["ma20_slope_4h"] > 0)
    if all_up:
        sc += 8; parts["all_up_4h"] = 8

    # 2) ret_24h / ret_72h (KR v5.1 의 1h 버전과 임계 동일 — 같은 시간 horizon)
    r24, r72 = float(last["ret_24h"] or 0), float(last["ret_72h"] or 0)
    if r24 > 0.20: sc += 10
    elif r24 > 0.10: sc += 7
    elif r24 > 0.05: sc += 5
    elif r24 > 0.02: sc += 3
    elif r24 < -0.05: sc -= 10
    parts["ret_24h_pts"] = sc - sum(parts.values())

    if r72 > 0.50: sc += 10
    elif r72 > 0.30: sc += 8
    elif r72 > 0.15: sc += 5
    elif r72 > 0.05: sc += 3
    elif r72 < 0: sc -= 8
    parts["ret_72h_pts"] = sc - sum(parts.values())

    # 3) 거래량 폭증
    vb = float(last["vol_24h_vs_72h"] or 0)
    if vb > 3.0: sc += 12
    elif vb > 2.0: sc += 8
    elif vb > 1.5: sc += 5
    elif vb > 1.2: sc += 2
    elif vb < 0.7: sc -= 5
    parts["vol_burst_pts"] = sc - sum(parts.values())

    # 패턴 1: 4h MA riding (MA10 OR MA20)
    if last["ma10_strong_up_4h"] == 1 and last["Close"] > last["ma10_4h"]:
        sc += 6; parts["ma10_strong_up_4h"] = 6
    if last["ma10_touch_recent_12h"] == 1:
        sc += 8; parts["ma10_touch_recent_12h"] = 8
    dist_10 = float(last["dist_ma10_4h"] or 0)
    if 0 <= dist_10 <= 0.05:
        sc += 5; parts["dist_ma10_sweet"] = 5

    if last["ma20_strong_up_4h"] == 1 and last["Close"] > last["ma20_4h"]:
        sc += 5; parts["ma20_strong_up_4h"] = 5
    if last["ma20_touch_recent_24h"] == 1:
        sc += 7; parts["ma20_touch_recent_24h"] = 7
    dist_20 = float(last["dist_ma20_4h"] or 0)
    if 0 <= dist_20 <= 0.08:
        sc += 4; parts["dist_ma20_sweet"] = 4

    dist_nearest = float(last["dist_nearest_ma_4h"] or 0)
    if dist_nearest > 0.20:
        sc -= 18; parts["dist_nearest_too_far"] = -18
    elif dist_nearest > 0.12:
        sc -= 10; parts["dist_nearest_far"] = -10
    elif dist_nearest > 0.08:
        sc -= 4; parts["dist_nearest_warm"] = -4

    # 패턴 2: 4h 강양봉 + holding (body 4% 가 threshold — 4h σ ≈ 2% 의 2배)
    if last["strong_bull_4h"] == 1:
        sc += 10; parts["strong_bull_4h"] = 10
    if last["bullish_holding_4h"] == 1:
        sc += 8; parts["bullish_holding_4h"] = 8

    # 1d 추세 confirm
    if df_1d is not None and not df_1d.empty:
        bull_1d, ret30_1d, ret90_1d, fh_1d = _last_1d_alignment(df_1d)
        if bull_1d == 1:
            sc += 4; parts["bull_1d"] = 4
        if ret30_1d > 0.30:
            sc += 4; parts["ret30_1d_strong"] = 4
        elif ret30_1d < -0.05:
            sc -= 8; parts["ret30_1d_neg"] = -8
        if ret90_1d > 1.0:
            sc += 4; parts["ret90_1d_strong"] = 4
        elif ret90_1d < 0:
            sc -= 10; parts["ret90_1d_neg"] = -10
        if fh_1d > -0.05:
            sc += 4; parts["near_1y_high"] = 4
        elif fh_1d < -0.30:
            sc -= 5; parts["deep_drawdown"] = -5

    # 진입 시점 페널티 (4h 봉의 1 bar ret = 4h ret)
    ret_1bar = float(last["ret_1bar"] or 0)
    if ret_1bar > 0.10:
        sc -= 12; parts["ret_4h_pump"] = -12
    elif ret_1bar > 0.05:
        sc -= 5; parts["ret_4h_warm"] = -5
    if r24 > 0.30:
        sc -= 15; parts["ret_24h_overheated"] = -15

    if last["bear_stack_4h"] == 1:
        sc -= 20; parts["bear_stack_4h"] = -20
    if last["Close"] < last["ma10_4h"]:
        sc -= 8; parts["below_ma10_4h"] = -8

    parts["_last_ts"] = df_4h_ind.index[-1]
    parts["_close"] = float(last["Close"])
    parts["_dist_ma10_4h"] = round(dist_10, 4)
    parts["_dist_ma20_4h"] = round(dist_20, 4)
    parts["_dist_nearest_4h"] = round(dist_nearest, 4)
    parts["_ret_4h_1bar"] = round(ret_1bar, 4)
    parts["_ret_24h"] = round(r24, 4)
    parts["_ret_72h"] = round(r72, 4)
    parts["_vol_burst"] = round(vb, 2)
    parts["_bull_stack_4h"] = int(last["bull_stack_4h"])
    parts["_ma10_strong_up_4h"] = int(last["ma10_strong_up_4h"])
    parts["_ma20_strong_up_4h"] = int(last["ma20_strong_up_4h"])

    return round(sc, 1), parts


