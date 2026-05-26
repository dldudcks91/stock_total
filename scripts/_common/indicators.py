"""주식 일봉 row 단위 지표 — KR/US (대문자 OHLCV) 공통.

`compute_indicators(df)` 가 df 에 MA/slope/ret/from_high/accumulation/캔들/거래량
지표 컬럼들을 add 한다. `compute_weekly_acc(df)` 는 주봉 acc_score 를 일봉 index 에
forward-fill 해 반환.

자산 무관 (input: Open/High/Low/Close/Volume + Change[optional]).
사용처:
  - scripts/kr/trend_pullback/scoring.py   (score_pullback_v3)
  - scripts/kr/trend_chase/scoring.py      (score_chase_v3/v4/v5/v5_1)
  - scripts/kr/backtest_all.py             (양쪽 동시 채점 백테스트)
  - 향후 scripts/us/ 도 동일 인터페이스.

Crypto 는 컬럼이 소문자 (close/volume/...) 이므로 호출 전 별도 normalize 필요.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """일봉 df 에 모든 row 단위 지표 column 을 add. 원본 보존을 위해 copy 후 반환.

    추가 컬럼:
      MA / slope            : ma10, ma20, ma50, ma{N}_slope (5일 pct_change)
      dist_from_ma          : dist_ma10/20/50
      stack                 : bull_stack, bear_stack (정/역배열 binary)
      returns               : ret_30d, ret_90d
      window high           : high_1y (252봉 max), from_high_1y
      accumulation (1d)     : vol_5_vs_30, acc_d
      volume ratio          : vol_recent_vs_prior (10/30)
      candle                : body, range_pct, vol_rank_30
      strong bull           : recent_strong_bull_10d (body>5% & vol_rank>0.7 in last 10 bars)
      v5 chase patterns     : ma10_touch_recent_5d, ma10_strong_up,
                              today_strong_bull, bullish_holding, today_chg
    """
    df = df.copy()
    c = df["Close"]
    v = df["Volume"]

    df["ma10"] = c.rolling(10).mean()
    df["ma20"] = c.rolling(20).mean()
    df["ma50"] = c.rolling(50).mean()
    df["ma10_slope"] = df["ma10"].pct_change(5)
    df["ma20_slope"] = df["ma20"].pct_change(5)
    df["ma50_slope"] = df["ma50"].pct_change(5)

    df["dist_ma10"] = c / df["ma10"] - 1
    df["dist_ma20"] = c / df["ma20"] - 1
    df["dist_ma50"] = c / df["ma50"] - 1

    df["bull_stack"] = ((df["ma10"] > df["ma20"]) & (df["ma20"] > df["ma50"])).astype(int)
    df["bear_stack"] = ((df["ma10"] < df["ma20"]) & (df["ma20"] < df["ma50"])).astype(int)

    df["ret_30d"] = c.pct_change(30)
    df["ret_90d"] = c.pct_change(90)

    df["high_1y"] = c.rolling(252).max()
    df["from_high_1y"] = c / df["high_1y"] - 1

    vol_5 = v.rolling(5).mean()
    vol_30 = v.rolling(30).mean()
    df["vol_5_vs_30"] = vol_5 / vol_30
    range_5 = (c.rolling(5).max() - c.rolling(5).min()) / c.rolling(5).mean()
    acc_d = pd.Series(0.0, index=df.index)
    acc_d += np.where((df["vol_5_vs_30"].between(1.0, 3.0)) & (range_5 < 0.10), 0.5, 0)
    acc_d += np.where((df["vol_5_vs_30"] > 1.5) & (range_5 < 0.07), 0.3, 0)
    acc_d += np.where((df["vol_5_vs_30"] > 2.0) & (range_5 < 0.05), 0.2, 0)
    df["acc_d"] = acc_d.clip(0, 1)

    df["vol_recent_vs_prior"] = v.rolling(10).mean() / v.rolling(30).mean()

    df["body"] = (df["Close"] - df["Open"]) / df["Open"]
    df["range_pct"] = (df["High"] - df["Low"]) / df["Open"]
    df["vol_rank_30"] = v.rolling(30).rank(pct=True)

    strong = ((df["body"] > 0.05) & (df["vol_rank_30"] > 0.7)).astype(int)
    df["recent_strong_bull_10d"] = strong.rolling(10).max()

    df["ma10_touch_recent_5d"] = (df["dist_ma10"].abs() < 0.03).rolling(5).max().fillna(0)
    df["ma10_strong_up"] = (df["ma10_slope"] > 0.05).astype(int)
    df["today_strong_bull"] = ((df["body"] > 0.05) & (df["vol_rank_30"] > 0.7)).astype(int)
    df["bullish_holding"] = ((df["recent_strong_bull_10d"] == 1) & (df["Close"] > df["ma10"])).astype(int)
    df["today_chg"] = df.get("Change", pd.Series(0, index=df.index)).fillna(0)

    return df


def compute_weekly_acc(df: pd.DataFrame) -> pd.Series:
    """주봉 acc_score 를 일봉 index 에 forward-fill 해 반환.

    주봉(W-FRI) 으로 Close last / Volume sum 리샘플 후 1d 와 같은 acc_score 공식 적용.
    데이터가 짧으면(<35 주봉) 전부 0.
    """
    wk = df[["Close", "Volume"]].resample("W-FRI").agg({"Close": "last", "Volume": "sum"}).dropna()
    if len(wk) < 35:
        return pd.Series(0.0, index=df.index)
    vol_5 = wk["Volume"].rolling(5).mean()
    vol_30 = wk["Volume"].rolling(30).mean()
    range_5 = (wk["Close"].rolling(5).max() - wk["Close"].rolling(5).min()) / wk["Close"].rolling(5).mean()
    acc_w = pd.Series(0.0, index=wk.index)
    acc_w += np.where((vol_5 / vol_30).between(1.0, 3.0) & (range_5 < 0.15), 0.5, 0)
    acc_w += np.where((vol_5 / vol_30 > 1.5) & (range_5 < 0.10), 0.3, 0)
    acc_w += np.where((vol_5 / vol_30 > 2.0) & (range_5 < 0.07), 0.2, 0)
    acc_w = acc_w.clip(0, 1)
    return acc_w.reindex(df.index, method="ffill").fillna(0)
