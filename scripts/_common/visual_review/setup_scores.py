"""Visual review setup scoring — facts에서 chase / pullback 셋업 점수 추출.

`facts.compute_facts_all_tfs` 의 단일 TF 출력(`tf_1d` 등)을 입력으로 받아,
같은 데이터를 **두 가지 다른 관점**(chase / pullback) 으로 점수화한다.

설계 의도
---------
`backtest/strategies/trend_chase.py` · `trend_pullback.py` 와는 별개 모듈:

- 백테스트 strategies:
    OHLCV → strict binary signal, 시간축 전체, no-lookahead, recs.parquet 용
- setup_scores (이 파일):
    facts(단일 시점 스냅샷) → soft 점수 0~1, 마지막 1봉만,
    visual_review context 보강 / 추천 ranking 용

같은 코인에서 두 점수가 다르게 나올 수 있고, **그 불일치 자체가 시그널**.

권장 TF
-------
**1d 입력 권장.** `last_candle.accumulation_candle_score` 는 1d 전용이고,
ADX/ATR/MA 패턴이 가장 안정적이다. 1w/1m TF 입력도 동작은 하지만
1차 상승 detector(accumulation_candle_score) 가 0으로 떨어진다.

레퍼런스
--------
- Minervini Trend Template: 정배열 + MA20 상승 + 52w 고점 25% 이내 + 매집
- Wilder ADX: ≥ 25 = 강한 추세 (추세 추종 트레이드의 표준 임계)
- VCP / Stage 2: tight MA spread + 거래량 감소 후 확장

사용 예
-------
    from scripts._common.visual_review.facts import compute_facts_all_tfs
    from scripts._common.visual_review.setup_scores import trend_chase, trend_pullback

    facts = compute_facts_all_tfs("BTCUSDT", asset="crypto", tfs=["1d"])
    risk_flags = facts.get("auto_risk_flags", [])

    print(trend_chase(facts["tf_1d"], risk_flags=risk_flags))
    print(trend_pullback(facts["tf_1d"], risk_flags=risk_flags))
"""
from __future__ import annotations
from typing import Optional, Sequence


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────

def _get(d, key, default=None):
    if not isinstance(d, dict):
        return default
    v = d.get(key)
    return default if v is None else v


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _tiered(value: float, tiers: Sequence[tuple]) -> float:
    """value 에 대해 [(threshold, points), ...] 단계 점수.

    tiers 는 threshold 오름차순. value >= threshold 인 가장 큰 단계의 points 반환.
    """
    out = 0.0
    for th, pts in tiers:
        if value >= th:
            out = pts
    return out


# ── chase: 장대양봉 + 거래량 폭증 추격 셋업 ───────────────────────────

def trend_chase(facts_tf: dict, risk_flags: Optional[Sequence[str]] = None) -> dict:
    """장대양봉 + 거래량 폭증 추격 셋업 점수 (0~1).

    Components (가능 최대 1.00, 페널티 후 [0,1] 클립):

        bull_body            0~0.25  ret_chase tiers 정렬: body ≥ 3/5/7% → 0.10/0.18/0.25
        volume               0~0.25  vol_rank_30d ≥ 0.70/0.85/0.95 → 0.10/0.18/0.25
        clean_breakout       0~0.10  bull + upper_wick < 15% (깨끗한 돌파)
        range_breakout       0~0.10  range_position ≥ 0.85 (박스 상단 돌파)
        trend                0~0.15  정배열 + above_all
        adx                  0~0.10  ADX ≥ 25/40 → 0.05/0.10
        breakout_anomaly     0~0.05  vol_anomaly == "breakout"

    Penalties:
        overextension       0~-0.25  ret_30d 크고 MA50 멀음 (이미 가버린 추세)
        far_from_high       0~-0.15  from_period_high < -0.20/-0.40 → -0.08/-0.15
        parabolic_flag        -0.20  auto_risk_flags 에 "parabolic"
        spike_at_top          -0.10  vol_anomaly == "spike" + range_position 높음 (churn)
    """
    lc = _get(facts_tf, "last_candle", {}) or {}
    flags = set(risk_flags or [])
    comp: "dict[str, float]" = {}

    # 1) 오늘 봉이 강한 양봉?
    is_bull = lc.get("type") == "bull"
    body = _f(lc.get("body_pct"))
    comp["bull_body"] = _tiered(body, [(0.03, 0.10), (0.05, 0.18), (0.07, 0.25)]) if is_bull else 0.0

    # 2) 거래량 분위
    vr = _f(lc.get("vol_rank_30d"))
    comp["volume"] = _tiered(vr, [(0.70, 0.10), (0.85, 0.18), (0.95, 0.25)])

    # 3) 깨끗한 돌파 — 양봉 + 윗꼬리 적음 (체결 후 매도세 적음)
    upper = _f(lc.get("upper_wick_pct"))
    if is_bull and body >= 0.02 and upper < 0.15:
        comp["clean_breakout"] = 0.10
    elif is_bull and body >= 0.02 and upper < 0.30:
        comp["clean_breakout"] = 0.05
    else:
        comp["clean_breakout"] = 0.0

    # 4) 박스 상단 돌파 — range_position 높음
    rp = _f(facts_tf.get("range_position"), 0.5)
    if rp >= 0.95:
        comp["range_breakout"] = 0.10
    elif rp >= 0.85:
        comp["range_breakout"] = 0.06
    else:
        comp["range_breakout"] = 0.0

    # 5) 추세 정합성
    stack_ok = facts_tf.get("ma_stack") == "정배열"
    above_all = facts_tf.get("price_pos") == "above_all"
    if stack_ok and above_all:
        comp["trend"] = 0.15
    elif stack_ok or above_all:
        comp["trend"] = 0.08
    else:
        comp["trend"] = 0.0

    # 6) ADX — 강한 추세 확인
    adx = _f(facts_tf.get("adx"))
    if adx >= 40:
        comp["adx"] = 0.10
    elif adx >= 25:
        comp["adx"] = 0.05
    else:
        comp["adx"] = 0.0

    # 7) vol_anomaly = "breakout" (실체 큰 거래량 폭증 — 자동 분류)
    comp["breakout_anomaly"] = 0.05 if lc.get("vol_anomaly") == "breakout" else 0.0

    # ── 페널티 ──────────────────────────────────────────────────────

    # 8) Overextension — 이미 멀리 와서 추격 위험
    dist_ma50 = _f(_get(facts_tf, "dist_from_ma", {}).get("ma50_pct"))
    ret30 = _f(facts_tf.get("ret_30d"))
    if ret30 > 0.5 and dist_ma50 > 0.30:
        comp["overextension_penalty"] = -0.25
    elif ret30 > 0.3 and dist_ma50 > 0.20:
        comp["overextension_penalty"] = -0.12
    else:
        comp["overextension_penalty"] = 0.0

    # 9) 52w 고점에서 멀음 — chase 자질 X (Minervini: 25% 이내가 이상적)
    fph = _f(facts_tf.get("from_period_high_pct"))
    if fph < -0.40:
        comp["far_from_high_penalty"] = -0.15
    elif fph < -0.20:
        comp["far_from_high_penalty"] = -0.08
    else:
        comp["far_from_high_penalty"] = 0.0

    # 10) 시스템 risk_flag
    comp["parabolic_penalty"] = -0.20 if "parabolic" in flags else 0.0

    # 11) 고점에서 churn (vol spike + 무실체) — 분배 직전 위험
    if lc.get("vol_anomaly") == "spike" and rp >= 0.80:
        comp["spike_at_top_penalty"] = -0.10
    else:
        comp["spike_at_top_penalty"] = 0.0

    raw = sum(comp.values())
    return {
        "score": round(max(0.0, min(1.0, raw)), 3),
        "components": {k: round(v, 3) for k, v in comp.items()},
    }


# ── pullback: 1차 상승 후 MA 비비기 ────────────────────────────────────

def trend_pullback(facts_tf: dict, risk_flags: Optional[Sequence[str]] = None) -> dict:
    """1차 상승 후 MA10/MA20(MA50) 비비기 셋업 점수 (0~1).

    Components:

        prior_run            0~0.30  1차 상승 발견 (accumulation_candle_score 우선,
                                     recent_strong_bull.holding 보조)
        ma_proximity         0~0.20  nearest_ma 거리 가까움 (MA10/20 우선, MA50 보조)
        atr_proximity        0~0.10  MA20 까지 ≤ 1 ATR (실효 비비기)
        trend_health         0~0.15  정배열 + MA20 slope=up
        adx                  0~0.10  ADX ≥ 20/30 → 0.05/0.10
        consolidation        0~0.15  5봉 tight (accumulation_score) + ma_spread=tight
        volume_dry           0~0.10  vol_avg_recent_vs_prior < 0.80/0.65 (Minervini)
        lower_wick_reject    0~0.05  근처에서 아랫꼬리로 저점 거부

    Penalties:
        overextension         -0.15  ret_30d > 50% (이미 추격 영역)
        distribution_today    -0.20  오늘 분배봉
        drawdown_deep_flag    -0.20  risk_flag 에 "drawdown_deep" (트렌드 깨짐 의심)
    """
    rsb = _get(facts_tf, "recent_strong_bull", {}) or {}
    nm = _get(facts_tf, "nearest_ma", {}) or {}
    lc = _get(facts_tf, "last_candle", {}) or {}
    flags = set(risk_flags or [])
    comp: "dict[str, float]" = {}

    # 1) 1차 상승 detector
    #    우선순위: (a) 60봉 매집봉 발견 (1d facts 한정) > (b) recent_strong_bull
    #    accumulation_bars_ago > 0 이어야 — 오늘 봉은 "후 pullback" 아님
    acc_score = _f(lc.get("accumulation_candle_score"))
    acc_bars_ago = _f(lc.get("accumulation_bars_ago"), -1)
    has_rsb = isinstance(rsb, dict) and bool(rsb)

    if acc_score >= 0.6 and acc_bars_ago >= 2:
        # 매집봉 발견 + 이미 며칠 지남 = 1차 상승 후 비비기 영역
        comp["prior_run"] = 0.30
    elif acc_score >= 0.3 and acc_bars_ago >= 2:
        comp["prior_run"] = 0.20
    elif has_rsb and rsb.get("holding"):
        comp["prior_run"] = 0.20
    elif has_rsb and _f(rsb.get("max_retrace_pct"), 1.0) < 0.15 and _f(rsb.get("bars_ago"), 0) >= 2:
        comp["prior_run"] = 0.12
    else:
        comp["prior_run"] = 0.0

    # 2) MA 근접 — MA10/20 우선, MA50 보조
    near_ma = nm.get("ma")
    dist = abs(_f(nm.get("dist_pct"), 1.0))
    if near_ma in ("ma10", "ma20") and dist < 0.02:
        comp["ma_proximity"] = 0.20
    elif near_ma in ("ma10", "ma20") and dist < 0.04:
        comp["ma_proximity"] = 0.12
    elif near_ma == "ma50" and dist < 0.03:
        comp["ma_proximity"] = 0.08
    else:
        comp["ma_proximity"] = 0.0

    # 3) ATR 정규화 MA20 거리
    dist_atr_ma20 = abs(_f(_get(facts_tf, "dist_from_ma_atr", {}).get("ma20_atr"), 99.0))
    if dist_atr_ma20 <= 1.0:
        comp["atr_proximity"] = 0.10
    elif dist_atr_ma20 <= 2.0:
        comp["atr_proximity"] = 0.05
    else:
        comp["atr_proximity"] = 0.0

    # 4) 추세 건강도
    slopes = _get(facts_tf, "ma_slopes", {}) or {}
    stack_ok = facts_tf.get("ma_stack") == "정배열"
    ma20_up = slopes.get("ma20") == "up"
    if stack_ok and ma20_up:
        comp["trend_health"] = 0.15
    elif stack_ok or ma20_up:
        comp["trend_health"] = 0.08
    else:
        comp["trend_health"] = 0.0

    # 5) ADX — pullback 은 추세 안에서만 의미 (chase 보다 약간 낮은 임계)
    adx = _f(facts_tf.get("adx"))
    if adx >= 30:
        comp["adx"] = 0.10
    elif adx >= 20:
        comp["adx"] = 0.05
    else:
        comp["adx"] = 0.0

    # 6) Consolidation — VCP 압축 신호 (tight range + tight MA)
    acc5 = _f(_get(facts_tf, "accumulation", {}).get("accumulation_score"))
    ma_spread = facts_tf.get("ma_spread")
    consol_pts = 0.0
    if acc5 >= 0.6:
        consol_pts += 0.10
    elif acc5 >= 0.3:
        consol_pts += 0.05
    if ma_spread == "tight":
        consol_pts += 0.05
    comp["consolidation"] = min(consol_pts, 0.15)

    # 7) Volume drying (Minervini: pullback = 거래량 감소)
    vol_ratio = _f(facts_tf.get("vol_avg_recent_vs_prior"), 1.0)
    if vol_ratio < 0.65:
        comp["volume_dry"] = 0.10
    elif vol_ratio < 0.80:
        comp["volume_dry"] = 0.05
    else:
        comp["volume_dry"] = 0.0

    # 8) MA 근처에서 아랫꼬리로 저점 거부
    lower_wick = _f(lc.get("lower_wick_pct"))
    near_ma_now = near_ma in ("ma10", "ma20", "ma50") and dist < 0.05
    if near_ma_now and lower_wick >= 0.35:
        comp["lower_wick_reject"] = 0.05
    else:
        comp["lower_wick_reject"] = 0.0

    # ── 페널티 ──────────────────────────────────────────────────────

    # 9) Overextension — 너무 많이 올랐으면 눌림 아니라 추격 영역
    ret30 = _f(facts_tf.get("ret_30d"))
    comp["overextension_penalty"] = -0.15 if ret30 > 0.5 else 0.0

    # 10) 오늘 분배봉
    dist_score = _f(lc.get("distribution_candle_score"))
    comp["distribution_penalty"] = -0.20 if dist_score >= 0.6 else 0.0

    # 11) 깊은 drawdown — 트렌드 자체가 깨진 의심
    comp["drawdown_deep_penalty"] = -0.20 if "drawdown_deep" in flags else 0.0

    raw = sum(comp.values())
    return {
        "score": round(max(0.0, min(1.0, raw)), 3),
        "components": {k: round(v, 3) for k, v in comp.items()},
    }


# ── 동시 호출 헬퍼 ────────────────────────────────────────────────────

def score_both(facts_tf: dict, risk_flags: Optional[Sequence[str]] = None) -> dict:
    """trend_chase + trend_pullback 동시 계산."""
    return {
        "trend_chase": trend_chase(facts_tf, risk_flags=risk_flags),
        "trend_pullback": trend_pullback(facts_tf, risk_flags=risk_flags),
    }


def score_from_full(facts: dict, tf: str = "1d") -> dict:
    """`compute_facts_all_tfs` 의 전체 출력에서 자동으로 tf + risk_flags 추출.

    Args:
        facts: compute_facts_all_tfs 반환값
        tf: 어느 TF 점수 매길지 (기본 1d)

    Returns:
        score_both 와 동일 구조 + "tf" 필드.
    """
    f_tf = facts.get(f"tf_{tf}")
    if not f_tf:
        return {"trend_chase": None, "trend_pullback": None, "tf": tf, "error": f"no tf_{tf} in facts"}
    rf = facts.get("auto_risk_flags", [])
    out = score_both(f_tf, risk_flags=rf)
    out["tf"] = tf
    return out


def dominant_setup(
    facts_tf: dict,
    risk_flags: Optional[Sequence[str]] = None,
    min_score: float = 0.4,
    margin: float = 0.15,
) -> dict:
    """두 점수 중 어느 셋업이 우세한지 라벨링.

    Returns:
        {
          "label": "trend_chase" | "trend_pullback" | "both" | "none",
          "trend_chase": float,
          "trend_pullback": float,
        }

        - 둘 다 min_score 미만 → "none"
        - 둘 다 min_score 이상 & |diff| < margin → "both" (혼합)
        - 한쪽이 다른쪽보다 margin 이상 크면 그쪽 라벨
        - tie-break: 큰 쪽
    """
    s = score_both(facts_tf, risk_flags=risk_flags)
    c, p = s["trend_chase"]["score"], s["trend_pullback"]["score"]
    if c < min_score and p < min_score:
        label = "none"
    elif c >= min_score and p >= min_score and abs(c - p) < margin:
        label = "both"
    elif c >= p + margin:
        label = "trend_chase"
    elif p >= c + margin:
        label = "trend_pullback"
    else:
        label = "trend_chase" if c >= p else "trend_pullback"
    return {"label": label, "trend_chase": c, "trend_pullback": p}
