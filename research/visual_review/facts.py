"""Visual review v2: 객관적 사실 자동 계산 (schema v2 의 context block).

차트 PNG 와 함께 `_facts.json` 으로 저장. Claude 가 채점할 때 그대로 review.context 에 복사.

7단계 차트 분석 중 단계 1, 2, 3-자동, 6-자동 결과를 자동 추출.

지원 TF
-------
crypto : 1h / 4h / 1d / 1w / 1m   (1h 는 raw 캐시, 4h 는 1h 에서 리샘플)
kr/us  : 1d / 1w / 1m              (1h/4h 캐시 없음 — 자동 필터)

review 용 (큰 그림 정성):    1m / 1w / 1d
entry 용  (진입 트리거 정량): 1d / 4h / 1h

사용 예:

    from research.visual_review.facts import compute_facts_all_tfs
    # review 용
    facts = compute_facts_all_tfs("BTCUSDT", asset="crypto", tfs=["1m","1w","1d"])
    # entry 용
    facts = compute_facts_all_tfs("BTCUSDT", asset="crypto", tfs=["1d","4h","1h"])
    # 풀
    facts = compute_facts_all_tfs("BTCUSDT", asset="crypto", tfs=["1m","1w","1d","4h","1h"])
"""
from __future__ import annotations
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from data.loader import load_ohlcv

# TF 별 리샘플 룰
INTRADAY_TFS = {"1h", "4h"}
DAILY_TFS = {"1d", "1w", "1m"}
RESAMPLE_RULE = {"4h": "4h", "1w": "W-MON", "1m": "ME"}

# 강양봉 lookback (recent_strong_bull)
LOOKBACK_BARS = {"1h": 48, "4h": 24, "1d": 10, "1w": 6, "1m": 3}

# range_position 윈도우 (박스 폭 기준)
RANGE_WINDOW = {"1h": 120, "4h": 60, "1d": 60, "1w": 30, "1m": 12}

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


# ── 추세·MA ────────────────────────────────────────────────────────────

def _slope_sign(values: pd.Series, n: int = 10) -> str:
    s = values.dropna().tail(n)
    if len(s) < 3:
        return "flat"
    x = np.arange(len(s))
    slope = np.polyfit(x, s.values, 1)[0]
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


def _dist_from_ma_atr(close: float, ma_val: float, atr_val: float) -> float:
    """ATR 정규화 MA 거리. 양수=MA 위, 음수=MA 아래. 1 ATR 단위."""
    if pd.isna(ma_val) or pd.isna(atr_val) or atr_val == 0:
        return 0.0
    return float((close - ma_val) / atr_val)


def _nearest_ma(close: float, ma10: float, ma20: float, ma50: float) -> dict:
    cands = []
    for name, val in (("ma10", ma10), ("ma20", ma20), ("ma50", ma50)):
        if not pd.isna(val):
            cands.append((name, _dist_from_ma(close, val)))
    if not cands:
        return {"ma": None, "dist_pct": None}
    name, dist = min(cands, key=lambda x: abs(x[1]))
    return {"ma": name, "dist_pct": round(dist, 4)}


# ── 변동성 / 추세 강도 ──────────────────────────────────────────────────

def _true_range(df: pd.DataFrame) -> pd.Series:
    h, l, c_prev = df["High"], df["Low"], df["Close"].shift(1)
    return pd.concat([h - l, (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    """Wilder ATR(14). 부족하면 NaN → None 으로 처리."""
    if len(df) < period + 1:
        return float("nan")
    tr = _true_range(df)
    atr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    val = atr.iloc[-1]
    return float(val) if not pd.isna(val) else float("nan")


def _adx(df: pd.DataFrame, period: int = 14) -> float:
    """ADX(14). 추세 강도 (방향 무관). 0~100."""
    if len(df) < period * 2 + 1:
        return float("nan")
    h, l = df["High"], df["Low"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = up.where((up > dn) & (up > 0), 0.0)
    minus_dm = dn.where((dn > up) & (dn > 0), 0.0)

    tr = _true_range(df)
    atr_s = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / atr_s.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / atr_s.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    val = adx.iloc[-1]
    return float(val) if not pd.isna(val) else float("nan")


def _range_position(df_full: pd.DataFrame, tf_label: str) -> float:
    """최근 N봉 박스 내 현재가 위치 (0=박스 하단, 1=박스 상단)."""
    window = RANGE_WINDOW.get(tf_label, 60)
    recent = df_full.tail(window)
    if len(recent) < 5:
        return 0.5
    rh = float(recent["High"].max())
    rl = float(recent["Low"].min())
    if rh == rl:
        return 0.5
    close = float(df_full["Close"].iloc[-1])
    pos = (close - rl) / (rh - rl)
    return float(max(0.0, min(1.0, pos)))


# ── 단일봉 패턴 ────────────────────────────────────────────────────────

def _accumulation_candle_score(vol_rank: float, close_in_bar: float, lower_wick_pct: float,
                                range_position: float, from_high: float) -> float:
    """매집봉 단일봉 점수. vol_rank≥0.85 필수, 나머지 패턴/위치 조합."""
    if vol_rank < 0.85:
        return 0.0
    pattern = sum((close_in_bar >= 0.5, lower_wick_pct >= 0.3))   # 0~2
    bonus = sum((range_position < 0.4, from_high < -0.10))         # 0~2
    if pattern == 2 and bonus == 2:
        return 1.0
    if pattern == 2 and bonus >= 1:
        return 0.6
    if pattern >= 1:
        return 0.3
    return 0.0


def _distribution_candle_score(vol_rank: float, close_in_bar: float, upper_wick_pct: float,
                                range_position: float, from_high: float) -> float:
    """분배봉 단일봉 점수. vol_rank≥0.85 필수, 매집의 거울."""
    if vol_rank < 0.85:
        return 0.0
    pattern = sum((close_in_bar <= 0.5, upper_wick_pct >= 0.3))
    bonus = sum((range_position > 0.6, from_high > -0.05))
    if pattern == 2 and bonus == 2:
        return 1.0
    if pattern == 2 and bonus >= 1:
        return 0.6
    if pattern >= 1:
        return 0.3
    return 0.0


def _last_candle(df: pd.DataFrame, df_full: pd.DataFrame, tf_label: str, range_pos: float) -> dict:
    """마지막 봉 정보. 매집·분배 점수 자동 포함."""
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

    upper_wick = max(h - max(o, c), 0.0)
    lower_wick = max(min(o, c) - l, 0.0)
    upper_wick_pct = float(upper_wick / rng)
    lower_wick_pct = float(lower_wick / rng)
    close_in_bar = float((c - l) / rng)  # 0=봉 저점, 1=봉 고점

    recent_vols = df["Volume"].tail(30).dropna()
    if len(recent_vols) >= 5 and v is not None and not pd.isna(v):
        rank = float((recent_vols < v).sum() / len(recent_vols))
    else:
        rank = 0.5

    vol_anomaly = None
    if rank > 0.85:
        if body_pct < 0.01:
            vol_anomaly = "spike"
        elif body_pct > 0.03:
            vol_anomaly = "breakout"

    period_high = float(df["High"].max())
    from_high = float(c / period_high - 1) if period_high > 0 else 0.0

    acc = _accumulation_candle_score(rank, close_in_bar, lower_wick_pct, range_pos, from_high)
    dist = _distribution_candle_score(rank, close_in_bar, upper_wick_pct, range_pos, from_high)

    return {
        "type": ctype,
        "body_pct": round(body_pct, 4),
        "upper_wick_pct": round(upper_wick_pct, 3),
        "lower_wick_pct": round(lower_wick_pct, 3),
        "vol_rank_30d": round(rank, 3),
        "vol_anomaly": vol_anomaly,
        "accumulation_candle_score": acc,
        "distribution_candle_score": dist,
    }


def _accumulation_signals(df: pd.DataFrame) -> dict:
    """5봉 multi-bar 매집 패턴 (기존)."""
    if len(df) < 35:
        return {"vol_5bar_vs_30bar": 1.0, "price_range_5bar_pct": 0.0, "accumulation_score": 0.0}
    vol_5 = df["Volume"].tail(5).mean()
    vol_30 = df["Volume"].iloc[-35:-5].mean()
    vol_ratio = float(vol_5 / max(vol_30, 1e-9))
    high_5 = df["High"].tail(5).max()
    low_5 = df["Low"].tail(5).min()
    last_close = float(df["Close"].iloc[-1])
    price_range = float((high_5 - low_5) / max(abs(last_close), 1e-9))
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


def _recent_strong_bull(
    df_full: pd.DataFrame,
    tf_label: str,
    body_min: float = 0.02,
    vol_rank_min: float = 0.7,
) -> Optional[dict]:
    """최근 lookback 봉 안의 강양봉 + 이후 retrace 정보.

    강양봉 정의:
        - type=bull (body/range > 0.4 AND close > open)
        - body_pct >= body_min (default 2%)
        - vol_rank (직전 30봉 대비) >= vol_rank_min (default 0.7)

    retrace 정보 (강양봉 발견 시):
        - max_retrace_pct      : 강양봉 종가 대비 이후 최저점까지 하락폭
        - current_retrace_pct  : 강양봉 종가 대비 현재가 하락폭
        - holding              : 현재 retrace<5% AND max retrace<10%
    """
    lookback = LOOKBACK_BARS.get(tf_label, 10)
    if len(df_full) < 32:
        return None
    df_recent = df_full.tail(lookback)

    n = len(df_recent)
    for offset in range(n):
        i = n - 1 - offset
        bar = df_recent.iloc[i]
        o, h, l, c, v = bar["Open"], bar["High"], bar["Low"], bar["Close"], bar["Volume"]
        rng = max(h - l, 1e-9)
        body = abs(c - o)
        body_pct = float(body / max(abs(c), 1e-9))
        if not (c > o and body / rng > 0.4):
            continue
        if body_pct < body_min:
            continue
        global_pos = df_full.index.get_loc(df_recent.index[i])
        if isinstance(global_pos, slice):
            global_pos = global_pos.start
        prior = df_full["Volume"].iloc[max(0, global_pos - 30):global_pos]
        if len(prior) < 5 or v is None or pd.isna(v):
            continue
        rank = float((prior < v).sum() / len(prior))
        if rank < vol_rank_min:
            continue

        # retrace — 강양봉 종가 vs 이후 봉들
        bull_close = float(c)
        if offset == 0:
            max_retrace = 0.0
            current_retrace = 0.0
        else:
            since = df_full.iloc[global_pos + 1:]
            if len(since) > 0 and bull_close > 0:
                min_low = float(since["Low"].min())
                max_retrace = float((bull_close - min_low) / bull_close)
                current_close = float(df_full["Close"].iloc[-1])
                current_retrace = float((bull_close - current_close) / bull_close)
            else:
                max_retrace = 0.0
                current_retrace = 0.0
        holding = (current_retrace < 0.05) and (max_retrace < 0.10)

        return {
            "bars_ago": offset,
            "body_pct": round(body_pct, 4),
            "vol_rank": round(rank, 3),
            "close": round(bull_close, 6),
            "max_retrace_pct": round(max_retrace, 4),
            "current_retrace_pct": round(current_retrace, 4),
            "holding": holding,
        }
    return None


# ── 빅픽처 보조 ─────────────────────────────────────────────────────────

def _ret(df: pd.DataFrame, n: int) -> float:
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
    prior = vols.iloc[-window * 2: -window].mean()
    if prior <= 0:
        return 1.0
    return float(round(recent / prior, 3))


# ── 메인 ────────────────────────────────────────────────────────────────

def compute_facts_tf(df_full: pd.DataFrame, bars: int = 200, tf_label: str = "1d") -> dict:
    """단일 TF DataFrame → context block 사실."""
    df = df_full.tail(bars)
    ma10_series = df_full["Close"].rolling(10).mean()
    ma20_series = df_full["Close"].rolling(20).mean()
    ma50_series = df_full["Close"].rolling(50).mean()
    close = float(df["Close"].iloc[-1])
    ma10 = float(ma10_series.iloc[-1]) if not pd.isna(ma10_series.iloc[-1]) else float("nan")
    ma20 = float(ma20_series.iloc[-1]) if not pd.isna(ma20_series.iloc[-1]) else float("nan")
    ma50 = float(ma50_series.iloc[-1]) if not pd.isna(ma50_series.iloc[-1]) else float("nan")

    # 변동성 / 추세 강도
    atr_val = _atr(df_full, period=14)
    adx_val = _adx(df_full, period=14)
    atr_pct = float(atr_val / close) if (close > 0 and not pd.isna(atr_val)) else None
    range_pos = _range_position(df_full, tf_label)

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
        "dist_from_ma_atr": {
            "ma10_atr": round(_dist_from_ma_atr(close, ma10, atr_val), 3),
            "ma20_atr": round(_dist_from_ma_atr(close, ma20, atr_val), 3),
            "ma50_atr": round(_dist_from_ma_atr(close, ma50, atr_val), 3),
        },
        "nearest_ma": _nearest_ma(close, ma10, ma20, ma50),
        # 변동성 / 추세 강도
        "atr": round(atr_val, 6) if not pd.isna(atr_val) else None,
        "atr_pct": round(atr_pct, 4) if atr_pct is not None else None,
        "adx": round(adx_val, 2) if not pd.isna(adx_val) else None,
        "range_position": round(range_pos, 3),
        # 단계 3 — 미시 행동 (객관 부분)
        "last_candle": _last_candle(df, df_full, tf_label, range_pos),
        "accumulation": _accumulation_signals(df_full),
        "recent_strong_bull": _recent_strong_bull(df_full, tf_label),
        # 단계 1 보충
        "ret_30d": round(_ret(df_full, 30), 4),
        "ret_90d": round(_ret(df_full, 90), 4),
        "from_period_high_pct": round(_from_period_high_pct(df), 4),
        "vol_avg_recent_vs_prior": _vol_avg_recent_vs_prior(df_full),
    }


def auto_risk_flags(facts_per_tf: dict[str, dict], asset: str = "crypto") -> list[str]:
    """단계 6-자동: facts 만으로 도출되는 위험 태그."""
    flags: list[str] = []
    tf_1d = facts_per_tf.get("1d")
    tf_1w = facts_per_tf.get("1w")

    if tf_1d:
        if tf_1d.get("ret_30d", 0) > 0.5 or tf_1d.get("ret_90d", 0) > 1.0:
            flags.append("parabolic")

    base_dd = tf_1w or tf_1d
    if base_dd and base_dd.get("from_period_high_pct", 0) < -0.3:
        flags.append("drawdown_deep")

    min_bars = {"1d": 100, "1w": 50, "1m": 24, "1h": 200, "4h": 100} if asset == "crypto" else {"1d": 60, "1w": 30, "1m": 12}
    low_hist = False
    for tf_key, f in facts_per_tf.items():
        if f.get("bars", 0) < min_bars.get(tf_key, 0):
            low_hist = True
            break
    if low_hist:
        flags.append("low_history")

    if tf_1d:
        vol_ratio = tf_1d.get("vol_avg_recent_vs_prior", 1.0)
        ret90 = tf_1d.get("ret_90d", 0)
        if vol_ratio < 0.3 and abs(ret90) < 0.1:
            flags.append("zombie")

    return flags


def _global_nearest_ma(facts_per_tf: dict[str, dict]) -> dict:
    best = None
    for tf, f in facts_per_tf.items():
        nm = f.get("nearest_ma") or {}
        if nm.get("dist_pct") is None:
            continue
        if best is None or abs(nm["dist_pct"]) < abs(best["dist_pct"]):
            best = {"tf": tf, "ma": nm["ma"], "dist_pct": nm["dist_pct"]}
    return best or {}


def compute_facts_all_tfs(
    symbol: str,
    asset: str = "crypto",
    tfs: Sequence[str] = ("1m", "1w", "1d", "4h", "1h"),
    bars: int = 200,
) -> dict:
    """모든 TF facts 한 번에 계산."""
    tfs_lower = [t.lower() for t in tfs]

    if asset != "crypto":
        tfs_lower = [t for t in tfs_lower if t in DAILY_TFS]

    df_1d = None
    df_1h = None
    if any(t in DAILY_TFS for t in tfs_lower):
        df_1d = _normalize(load_ohlcv(asset, symbol, "1d"))
    if any(t in INTRADAY_TFS for t in tfs_lower):
        df_1h = _normalize(load_ohlcv(asset, symbol, "1h"))

    out: dict = {"symbol": symbol, "asset": asset, "tfs": list(tfs_lower)}
    per_tf: dict[str, dict] = {}
    for tf in tfs_lower:
        if tf == "1h":
            df_full = df_1h
        elif tf == "4h":
            df_full = _resample(df_1h, RESAMPLE_RULE["4h"]) if df_1h is not None else None
        elif tf == "1d":
            df_full = df_1d
        elif tf == "1w":
            df_full = _resample(df_1d, RESAMPLE_RULE["1w"]) if df_1d is not None else None
        elif tf == "1m":
            df_full = _resample(df_1d, RESAMPLE_RULE["1m"]) if df_1d is not None else None
        else:
            continue
        if df_full is None or len(df_full) < 5:
            continue
        f = compute_facts_tf(df_full, bars=bars, tf_label=tf)
        out[f"tf_{tf}"] = f
        per_tf[tf] = f
    out["auto_risk_flags"] = auto_risk_flags(per_tf, asset=asset)
    out["global_nearest_ma"] = _global_nearest_ma(per_tf)
    return out
