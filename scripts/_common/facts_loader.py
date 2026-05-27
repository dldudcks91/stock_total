"""visual_review.facts 캐시 wrapper — 임의 cutoff 시점 facts + today metrics.

`scripts/_common/visual_review/facts.compute_facts_tf` 를 1d/1w/1m TF 에 호출해
(facts dict by TF, today metrics) 를 반환. cutoff 까지 자른 캐시 기준.

사용처:
  - scripts/kr/recommend_all.py        (split 인계 — pb/ch label-based 점수)
  - scripts/kr/trend_pullback/recommend.py
  - scripts/kr/trend_chase/recommend.py

자산별 캐시 경로 / 컬럼 스키마 차이는 호출자가 흡수
(KR/US 대문자 → scripts._common.visual_review.facts._normalize 가 받아 처리).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from scripts._common.visual_review.facts import (  # type: ignore
    compute_facts_tf,
    _resample,
    _normalize,
    RESAMPLE_RULE,
)


def load_fresh_facts(
    parquet_path: Path,
    cutoff: pd.Timestamp,
    *,
    min_bars: int = 60,
    bars: int = 200,
    tfs: tuple = ("1d", "1w", "1m"),
) -> tuple[dict, dict]:
    """cutoff 시점까지의 OHLCV 로 multi-TF facts 와 today metrics 계산.

    Returns:
      facts   : ``{"tf_1d": {...}, "tf_1w": {...}, "tf_1m": {...}}`` (실패한 TF 는 누락)
      today   : ``{"close": float, "change": float, "vol_ratio": float,
                   "amount": float}`` (계산 불가 시 NaN)
                vol_ratio = today_volume / mean(last 20 prior volumes)
                amount    = today_volume × today_close (KR 원, US 달러)

    cutoff 일 이전 바 수가 ``min_bars`` 미만이면 ``({}, today_with_nans)`` 반환.
    """
    nan = float("nan")
    today_empty = {"close": nan, "change": nan, "vol_ratio": nan, "amount": nan}

    if not parquet_path.exists():
        return {}, today_empty

    df_raw = pd.read_parquet(parquet_path)
    df = df_raw[df_raw.index <= cutoff]
    if len(df) < min_bars:
        return {}, today_empty

    last_row = df.iloc[-1]
    last_close = float(last_row["Close"])
    today_chg = float(last_row.get("Change", 0))
    today_vol = float(last_row["Volume"])
    today_amount = today_vol * last_close
    prior_vol = df.iloc[-21:-1]["Volume"].mean()
    today_vol_ratio = float(today_vol / prior_vol) if prior_vol and prior_vol > 0 else nan
    today = {
        "close": last_close,
        "change": today_chg,
        "vol_ratio": today_vol_ratio,
        "amount": today_amount,
    }

    df_n = _normalize(df)
    facts: dict = {}
    if "1d" in tfs:
        try:
            facts["tf_1d"] = compute_facts_tf(df_n, bars=bars, tf_label="1d")
        except Exception:
            return {}, today  # 1d 실패면 의미 없음
    if "1w" in tfs:
        try:
            facts["tf_1w"] = compute_facts_tf(_resample(df_n, RESAMPLE_RULE["1w"]), bars=bars, tf_label="1w")
        except Exception:
            pass
    if "1m" in tfs:
        try:
            facts["tf_1m"] = compute_facts_tf(_resample(df_n, RESAMPLE_RULE["1m"]), bars=bars, tf_label="1m")
        except Exception:
            pass
    return facts, today


def load_visual_label(reviews_dir: Path, sym: str, label_date: str) -> dict:
    """visual_review JSON 라벨 로드 (없거나 파싱 실패 시 빈 dict).

    Args:
      reviews_dir : data/cache/{asset}/visual_review/reviews 같은 base dir
      sym         : 종목 코드 (KR 6자리 / crypto SYMBOLUSDT)
      label_date  : "20260521" 형식
    """
    import json
    f = reviews_dir / sym / f"{label_date}.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}
