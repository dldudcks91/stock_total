"""Visual review v2: 객관적 사실 자동 계산 (schema v2 의 context block).

차트 PNG 와 함께 `_facts.json` 으로 저장. Claude 가 채점할 때 그대로 review.context 에 복사.

7단계 차트 분석 중 단계 1, 2, 3-자동, 6-자동 결과를 자동 추출.

사용 예:

    from research.visual_review.facts import compute_facts_all_tfs
    facts = compute_facts_all_tfs("BTCUSDT", asset="crypto", tfs=["1m","1w","1d"])
"""
from __future__ import annotations
from typing import Sequence

import numpy as np
import pandas as pd

from data.loader import load_ohlcv

RULE_MAP = {"1d": None, "1w": "W-MON", "1m": "ME"}
_AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV 컬럼명 정규화 (crypto lowercase / stocks uppercase 모두 처리)."""
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for need in ("open", "high", "low", "close", "volume"):
        if need in cols:
            rename[cols[need]] = need.capitalize()
    df = df.rename(columns=rename)
    if "timestamp" in df.columns:
        idx = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
        df = df.set_index(idx)
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    return df[["Open", "High", "Low", "Close", "Volume"]]


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df.resample(rule).agg(_AGG).dropna()


def _slope_sign(values: pd.Series, n: int = 10) -> str:
    """최근 n 봉 회귀 기울기 부호 → up / flat / down."""
    s = values.dropna().tail(n)
    if len(s) < 3:
        return "flat"
    x = np.arange(len(s))
    slope = np.polyfit(x, s.values, 1)[0]
    # 기준선: 평균값의 0.1% / 봉
    threshold = abs(s.mean()) * 0.001
    if slope > threshold:
        return "up"
    if slope < -threshold:
        return "down"
    return "flat"


def _ma_stack(ma10: float, ma20: float, ma50: float) -> str:
    if pd.isna(ma10) or pd.isna(ma20) or pd.isna(ma50):
        return "혼합"
    if ma10 > ma20 > ma50:
        return "정배열"
    if ma10 < ma20 < ma50:
        return "역배열"
    return "혼합"


def _ma_spread(ma10: float, ma20: float, ma50: float) -> str:
    """MA 간격 → tight / normal / spread."""
    if pd.isna(ma10) or pd.isna(ma20) or pd.isna(ma50):
        return "normal"
    g1 = abs(ma10 - ma20) / max(abs(ma20), 1e-9)
    g2 = abs(ma20 - ma50) / max(abs(ma50), 1e-9)
    avg = (g1 + g2) / 2
    if avg < 0.02:
        return "tight"
    if avg > 0.08:
        return "spread"
    return "normal"


def _price_pos(close: float, ma10: float, ma20: float, ma50: float) -> str:
    """현재가 위치 → above_all / between / below_all."""
    mas = [m for m in (ma10, ma20, ma50) if not pd.isna(m)]
    if not mas:
        return "between"
    if close > max(mas):
        return "above_all"
    if close < min(mas):
        return "below_all"
    return "between"


def _dist_from_ma(close: float, ma_val: float) -> float:
    if pd.isna(ma_val) or ma_val == 0:
        return 0.0
    return float((close - ma_val) / ma_val)


def _last_candle(df: pd.DataFrame) -> dict:
    """마지막 봉 정보 (단계 3 객관 부분).

    vol_anomaly 자동 감지:
        - "spike"    : body < 1% + 거래량 상위 15% (도지 + 폭증 → 매집/분배 의심)
        - "breakout" : body > 3% + 거래량 상위 15% (큰 봉 + 폭증)
        - null       : 이상 없음
    """
    last = df.iloc[-1]
    o, h, l, c, v = last["Open"], last["High"], last["Low"], last["Close"], last["Volume"]
    rng = max(h - l, 1e-9)
    body = abs(c - o)
    body_pct = float(body / max(abs(c), 1e-9))
    if c > o and body / rng > 0.4:
        ctype = "bull"
    elif c < o and body / rng > 0.4:
        ctype = "bear"
    else:
        ctype = "doji"
    # 거래량 백분위 (최근 30봉 대비)
    recent_vols = df["Volume"].tail(30).dropna()
    if len(recent_vols) >= 5 and v is not None and not pd.isna(v):
        rank = float((recent_vols < v).sum() / len(recent_vols))
    else:
        rank = 0.5
    # vol_anomaly 자동 감지
    vol_anomaly = None
    if rank > 0.85:
        if body_pct < 0.01:
            vol_anomaly = "spike"
        elif body_pct > 0.03:
            vol_anomaly = "breakout"
    return {
        "type": ctype,
        "body_pct": round(body_pct, 4),
        "vol_rank_30d": round(rank, 3),
        "vol_anomaly": vol_anomaly,
    }


def _accumulation_signals(df: pd.DataFrame) -> dict:
    """최근 5봉의 매집 가능성 점수 (multi-bar 패턴).

    매집 정의 (조용한 흡수):
        - 최근 5봉 평균 거래량 / 직전 30봉 평균 > 1.3 (거래량 증가)
        - 최근 5봉 가격 폭 < 5% (좁은 박스)
    score 0~1.0
    """
    if len(df) < 35:
        return {"vol_5bar_vs_30bar": 1.0, "price_range_5bar_pct": 0.0, "accumulation_score": 0.0}
    vol_5 = df["Volume"].tail(5).mean()
    vol_30 = df["Volume"].iloc[-35:-5].mean()
    vol_ratio = float(vol_5 / max(vol_30, 1e-9))
    high_5 = df["High"].tail(5).max()
    low_5 = df["Low"].tail(5).min()
    last_close = float(df["Close"].iloc[-1])
    price_range = float((high_5 - low_5) / max(abs(last_close), 1e-9))
    # accumulation score
    if vol_ratio >= 1.5 and price_range < 0.05:
        score = 1.0
    elif vol_ratio >= 1.2 and price_range < 0.08:
        score = 0.6
    elif vol_ratio >= 1.0 and price_range < 0.1:
        score = 0.3
    else:
        score = 0.0
    return {
        "vol_5bar_vs_30bar": round(vol_ratio, 3),
        "price_range_5bar_pct": round(price_range, 4),
        "accumulation_score": round(score, 2),
    }


def _ret(df: pd.DataFrame, n: int) -> float:
    """최근 n 봉 수익률."""
    if len(df) < n + 1:
        return 0.0
    return float(df["Close"].iloc[-1] / df["Close"].iloc[-n - 1] - 1)


def _from_period_high_pct(df: pd.DataFrame) -> float:
    high = df["High"].max()
    if pd.isna(high) or high == 0:
        return 0.0
    return float(df["Close"].iloc[-1] / high - 1)


def _vol_avg_recent_vs_prior(df: pd.DataFrame, window: int = 30) -> float:
    vols = df["Volume"].dropna()
    if len(vols) < window * 2:
        return 1.0
    recent = vols.tail(window).mean()
    prior = vols.iloc[-window * 2 : -window].mean()
    if prior <= 0:
        return 1.0
    return float(round(recent / prior, 3))


def compute_facts_tf(df_full: pd.DataFrame, bars: int = 200) -> dict:
    """단일 TF DataFrame (이미 리샘플된) → context block 사실.

    단계 1, 2, 3-자동 결과를 담은 dict 반환.
    """
    df = df_full.tail(bars)
    ma10_series = df_full["Close"].rolling(10).mean()
    ma20_series = df_full["Close"].rolling(20).mean()
    ma50_series = df_full["Close"].rolling(50).mean()
    close = float(df["Close"].iloc[-1])
    ma10 = float(ma10_series.iloc[-1]) if not pd.isna(ma10_series.iloc[-1]) else float("nan")
    ma20 = float(ma20_series.iloc[-1]) if not pd.isna(ma20_series.iloc[-1]) else float("nan")
    ma50 = float(ma50_series.iloc[-1]) if not pd.isna(ma50_series.iloc[-1]) else float("nan")

    return {
        # 단계 1 — 빅픽처
        "last_close": round(close, 6),
        "bars": int(len(df)),
        "date_range": f"{df.index[0].date()} ~ {df.index[-1].date()}",
        # 단계 2 — 추세 해부
        "ma10": round(ma10, 6) if not pd.isna(ma10) else None,
        "ma20": round(ma20, 6) if not pd.isna(ma20) else None,
        "ma50": round(ma50, 6) if not pd.isna(ma50) else None,
        "ma_stack": _ma_stack(ma10, ma20, ma50),
        "ma_slopes": {
            "ma10": _slope_sign(ma10_series),
            "ma20": _slope_sign(ma20_series),
            "ma50": _slope_sign(ma50_series),
        },
        "ma_spread": _ma_spread(ma10, ma20, ma50),
        "price_pos": _price_pos(close, ma10, ma20, ma50),
        "dist_from_ma": {
            "ma10_pct": round(_dist_from_ma(close, ma10), 4),
            "ma20_pct": round(_dist_from_ma(close, ma20), 4),
            "ma50_pct": round(_dist_from_ma(close, ma50), 4),
        },
        # 단계 3 — 미시 행동 (객관 부분)
        "last_candle": _last_candle(df),
        "accumulation": _accumulation_signals(df_full),
        # 단계 1 보충 — 수익률 / 드로우다운 / 거래량 변화
        "ret_30d": round(_ret(df_full, 30), 4),
        "ret_90d": round(_ret(df_full, 90), 4),
        "from_period_high_pct": round(_from_period_high_pct(df), 4),
        "vol_avg_recent_vs_prior": _vol_avg_recent_vs_prior(df_full),
    }


def auto_risk_flags(facts_per_tf: dict[str, dict], asset: str = "crypto") -> list[str]:
    """단계 6-자동: facts 만으로 도출되는 위험 태그.

    parabolic / drawdown_deep / low_history / zombie

    - parabolic / zombie : 1D 기준 (ret_30d / ret_90d 가 일 단위일 때만 의미 있음)
    - drawdown_deep      : 1W 기준 (가장 큰 TF 중 의미 있는 것, 1M 은 history 부족 빈번)
    - low_history        : TF 별 최소 봉수 부족 시
    """
    flags: list[str] = []
    tf_1d = facts_per_tf.get("1d")
    tf_1w = facts_per_tf.get("1w")
    tf_1m = facts_per_tf.get("1m")

    # parabolic — 1D 기준
    if tf_1d:
        if tf_1d.get("ret_30d", 0) > 0.5 or tf_1d.get("ret_90d", 0) > 1.0:
            flags.append("parabolic")

    # drawdown_deep — 1W 우선, 없으면 1D
    base_dd = tf_1w or tf_1d
    if base_dd and base_dd.get("from_period_high_pct", 0) < -0.3:
        flags.append("drawdown_deep")

    # low_history — TF 별 최소 봉수
    min_bars = {"1d": 100, "1w": 50, "1m": 24} if asset == "crypto" else {"1d": 60, "1w": 30, "1m": 12}
    low_hist = False
    for tf_key, f in facts_per_tf.items():
        if f.get("bars", 0) < min_bars.get(tf_key, 0):
            low_hist = True
            break
    if low_hist:
        flags.append("low_history")

    # zombie — 1D 기준 거래량 -70% + 횡보 ±10%
    if tf_1d:
        vol_ratio = tf_1d.get("vol_avg_recent_vs_prior", 1.0)
        ret90 = tf_1d.get("ret_90d", 0)
        if vol_ratio < 0.3 and abs(ret90) < 0.1:
            flags.append("zombie")

    return flags


def compute_facts_all_tfs(
    symbol: str,
    asset: str = "crypto",
    tfs: Sequence[str] = ("1m", "1w", "1d"),
    bars: int = 200,
) -> dict:
    """모든 TF 의 facts + auto_risk_flags 한 번에 계산.

    Returns
    -------
    {
        "symbol": ..., "asset": ..., "tfs": [...],
        "tf_1m": {...}, "tf_1w": {...}, "tf_1d": {...},
        "auto_risk_flags": [...],
    }
    """
    df_1d = _normalize(load_ohlcv(asset, symbol, "1d"))
    out: dict = {"symbol": symbol, "asset": asset, "tfs": list(tfs)}
    per_tf = {}
    for tf in tfs:
        tf_l = tf.lower()
        rule = RULE_MAP.get(tf_l)
        df_full = df_1d if rule is None else _resample(df_1d, rule)
        if len(df_full) < 5:
            continue
        f = compute_facts_tf(df_full, bars=bars)
        out[f"tf_{tf_l}"] = f
        per_tf[tf_l] = f
    out["auto_risk_flags"] = auto_risk_flags(per_tf, asset=asset)
    return out
