"""대시보드 추천 컬럼 — 종목별 최신 봉 기준 전략 점수.

각 종목의 1d / 1w 데이터에 대해 4 전략 점수를 계산해 가장 강한 추천 1개를
표 한 칸에 표시한다. 자동매매가 아닌 추천 도구 — score >= 80 인 신호만 켬.

전략 매핑:
  - trend_chase  (1d, 1w) — "추격"  : 장대양봉 + 거래량 폭증
  - trend_pullback (1d, 1w) — "눌림" : MA10/MA20 터치 + 반응 (각도)
  - quiet_bottom (1w only) — "바닥" : 조용한 바닥 (binary, 활성 시 100점)

표시 형식:  "추격d 95" / "눌림w 85" / "바닥w 100"
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pandas as pd

from backtest.strategies import quiet_bottom, trend_chase, trend_pullback

# (label, code, interval, mod, min_bars, kind)
#   kind = "score"  → score(df).iloc[-1] 점수 그대로
#   kind = "binary" → signal(df).iloc[-1] == 1 이면 100 점
_STRATEGY_SPECS: list[tuple[str, str, str, object, int, str]] = [
    ("추격", "chase", "1d", trend_chase, 30, "score"),
    ("추격", "chase", "1w", trend_chase, 30, "score"),
    ("눌림", "pullback", "1d", trend_pullback, 70, "score"),
    ("눌림", "pullback", "1w", trend_pullback, 30, "score"),
    ("바닥", "quiet", "1w", quiet_bottom, 120, "binary"),
]

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


def _last_score(mod, df: pd.DataFrame, kind: str) -> float:
    """전략의 마지막 봉 점수. 실패 시 NaN."""
    try:
        if kind == "score":
            s = mod.score(df.reset_index(drop=True), {})
            v = float(s.iloc[-1])
            return v if np.isfinite(v) else np.nan
        # binary
        sig = mod.signal(df.reset_index(drop=True), {})
        return 100.0 if int(sig.iloc[-1]) == 1 else 0.0
    except Exception:
        return np.nan


def compute_recommendations(
    asset: str,
    symbols: list[str],
    daily_loader: Callable[[str], Optional[pd.DataFrame]],
    weekly_loader: Callable[[str], Optional[pd.DataFrame]],
) -> pd.DataFrame:
    """심볼 리스트 → 추천 DataFrame (symbol, rec_label, rec_score, rec_detail).

    rec_label  : "추격d", "눌림w", "바닥w" 같은 짧은 라벨 (활성 신호 중 최고점)
    rec_score  : 활성 신호의 최고점 (>=80 만 표시, 그 외 NaN)
    rec_detail : 활성 신호 모두 ("추격d 95 / 눌림w 85" 같은 멀티-시그널 표시)
    rec_kind   : "chase" / "pullback" / "quiet" — 색상 구분용
    """
    is_stock = asset in ("kr", "us")
    norm = _norm_stock_df if is_stock else _norm_crypto_df

    rows = []
    for sym in symbols:
        result = {
            "symbol": sym,
            "rec_label": None, "rec_score": np.nan,
            "rec_detail": None, "rec_kind": None,
        }
        try:
            df_d_raw = daily_loader(sym)
            df_w_raw = weekly_loader(sym)
        except Exception:
            rows.append(result)
            continue
        df_d = norm(df_d_raw)
        df_w = norm(df_w_raw)

        candidates: list[tuple[str, str, float, str]] = []  # (label, code, score, kind_name)
        for label, code, interval, mod, min_bars, kind in _STRATEGY_SPECS:
            df = df_d if interval == "1d" else df_w
            if df is None or df.empty or len(df) < min_bars:
                continue
            s = _last_score(mod, df, kind)
            if not np.isfinite(s) or s < SCORE_THRESHOLD:
                continue
            iv_suffix = "d" if interval == "1d" else "w"
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
