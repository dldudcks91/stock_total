"""trend_chase — visual_review 라벨 + fresh facts 결합 점수 (dict-based).

scripts/kr/recommend_all.py (구 kr_recommend_split.py) 의 CHASE 점수 시스템.

점수 구성 (최대값 CH_MAX = 112):
  state 25 + 20 + 5 + micro 14 + 12 + ret 16 + vol 10 + vol_flag 10 = 112

차이점 (pullback 대비):
  - state 가중치: A5/A2/A3 우선 (강한 추세)
  - micro 가중치: acceleration/breaking/breakout 우선
  - 추세 강도 보너스: ret_30d / ret_90d 양수 가산
  - vol_ratio_today (당일 거래량 폭증) 가산

페널티:
  - distribution / pump_dump / blowoff / drawdown_deep risk_flags 강감점
  - from_high < -40% + ret_30d > 10% (의심스러운 반등) 감점
  - B1/B2 state cut
"""
from __future__ import annotations


CH_STATE_W_1W = {"A5": 25, "A2": 22, "A3": 20, "A1": 14, "A4": 16, "B5": 14, "B4": 8, "B3": 4, "C1": 2, "B2": 0, "B1": 0}
CH_STATE_W_1D = {"A5": 20, "A2": 18, "A3": 16, "A1": 12, "A4": 14, "B5": 11, "B4": 6, "B3": 3, "C1": 2, "B2": -5, "B1": -10}
CH_STATE_W_1M_BONUS = {"A5": 5, "A4": 5, "A3": 5, "A2": 4, "A1": 2, "B5": 3, "B1": -20, "B2": -15, "C1": -5}

CH_MICRO_W_1W = {"acceleration": 14, "breaking": 12, "breakout": 12, "riding": 10,
                 "bounce_ma10": 10, "bounce_ma20": 9, "pullback_ma10": 9, "pullback_ma20": 7,
                 "pullback_ma50": 4, "consolidating": 3}
CH_MICRO_W_1D = {"acceleration": 12, "breaking": 10, "breakout": 10, "riding": 8,
                 "bounce_ma10": 8, "bounce_ma20": 7, "pullback_ma10": 7, "pullback_ma20": 5,
                 "pullback_ma50": 3, "consolidating": 2}

CH_VOL_FLAG_W = {"breakout_volume": 10, "accumulation": 6, "accumulation_suspect": 4, "normal": 3,
                 "distribution_suspect": -12, "distribution": -25}

CH_MAX = 25 + 20 + 5 + 14 + 12 + 16 + 10 + 10  # = 112


def score_chase_label(label: dict, fresh: dict, vol_ratio_today: float) -> dict:
    """visual label + fresh facts + 당일 거래량 비율 → chase 점수 dict.

    Args:
      label           : visual_review JSON
      fresh           : multi-TF facts dict
      vol_ratio_today : 당일 거래량 / 직전 20일 평균 (load_fresh_facts 의 today.vol_ratio)

    Returns:
      ``{"ch_score": float, "ch_pct": float, "cut_ch": bool}``
    """
    s_1m = (label.get("tf_1m") or {}).get("state")
    s_1w = (label.get("tf_1w") or {}).get("state")
    s_1d = (label.get("tf_1d") or {}).get("state")
    m_1w = (label.get("tf_1w") or {}).get("micro_action")
    m_1d = (label.get("tf_1d") or {}).get("micro_action")
    v_1w = (label.get("tf_1w") or {}).get("volume_flag")
    verdict = label.get("verdict")
    risk_flags = label.get("risk_flags", []) or []

    tf_1d = fresh.get("tf_1d", {}) or {}
    ret30 = tf_1d.get("ret_30d", 0) or 0
    ret90 = tf_1d.get("ret_90d", 0) or 0
    from_high = tf_1d.get("from_period_high_pct", 0) or 0

    sc = 0
    sc += CH_STATE_W_1W.get(s_1w, 0)
    sc += CH_STATE_W_1D.get(s_1d, 0)
    sc += CH_STATE_W_1M_BONUS.get(s_1m, 0)
    sc += CH_MICRO_W_1W.get(m_1w, 0)
    sc += CH_MICRO_W_1D.get(m_1d, 0)
    sc += CH_VOL_FLAG_W.get(v_1w, 0)

    # 추세 강도 보너스
    ret_score = 0
    if ret30 > 0.3:
        ret_score += 8
    elif ret30 > 0.15:
        ret_score += 5
    elif ret30 > 0.05:
        ret_score += 2
    elif ret30 < -0.05:
        ret_score -= 5
    if ret90 > 0.5:
        ret_score += 8
    elif ret90 > 0.3:
        ret_score += 5
    elif ret90 > 0.1:
        ret_score += 2
    elif ret90 < 0:
        ret_score -= 5
    sc += ret_score

    # 당일 거래량 폭증 (추격은 오늘 vol 중요)
    if vol_ratio_today >= 3:
        sc += 10
    elif vol_ratio_today >= 2:
        sc += 6
    elif vol_ratio_today >= 1.5:
        sc += 3

    # 페널티 — 추격하면 안 되는 신호
    for f in risk_flags:
        if f in ("distribution",):
            sc -= 25
        elif f == "distribution_suspect":
            sc -= 12
        elif f == "drawdown_deep":
            sc -= 15
        elif f in ("pump_dump", "blowoff"):
            sc -= 25
        # parabolic 은 chase 에서는 페널티 X (자체가 추격 자리)
    # 깊은 drawdown 후 양의 ret = 의심스러운 반등
    if from_high < -0.4 and ret30 > 0.1:
        sc -= 12

    # 컷
    cut = (verdict == "reject")
    if s_1m in ("B1", "B2") and s_1d in ("B1", "B2"):
        cut = True
    if s_1d in ("B1", "B2"):
        cut = True

    return {
        "ch_score": round(sc, 1),
        "ch_pct": round(100 * sc / CH_MAX, 1),
        "cut_ch": cut,
    }
