"""trend_pullback — visual_review 라벨 + fresh facts 결합 점수 (dict-based).

scripts/kr/recommend_all.py (구 kr_recommend_split.py) 의 PULLBACK 점수 시스템.
visual_review 5/21 라벨 + cutoff 시점 facts 둘 다 받아 점수 dict 를 반환한다.

점수 구성 (최대값 PB_MAX = 113):
  state 25 + 20 + 5 + micro 14+12 + acc 12+10 + vol 10 = 113

페널티:
  - parabolic / distribution / pump_dump / blowoff / drawdown_deep risk_flags
  - ret_30d 폭등 (+50% 페널티), drawdown (-20% 페널티)
  - 신고가 / 깊은 하락 페널티

컷:
  - verdict == "reject"
  - 1m state ∈ {B1, B2} 면서 1w 미회복
"""
from __future__ import annotations


# state 가중치 — pullback 은 A4 (1차 상승 후 휴식) 최고
PB_STATE_W_1W = {"A4": 25, "B5": 22, "A3": 22, "B4": 18, "B3": 14, "A5": 15, "A2": 6, "C1": 4, "B2": 0, "B1": 0, "A1": 8}
PB_STATE_W_1D = {"A4": 20, "B5": 18, "A3": 18, "B4": 15, "B3": 12, "A5": 12, "A2": 5, "C1": 3, "B2": 0, "B1": 0, "A1": 6}
PB_STATE_W_1M_BONUS = {"A5": 5, "A4": 5, "B5": 5, "A3": 3, "B4": 2, "A2": 1, "B1": -25, "B2": -20, "C1": -10}

# micro_action 가중치 — bounce_ma10/20 / pullback_ma10/20 우선
PB_MICRO_W_1W = {"bounce_ma10": 14, "bounce_ma20": 12, "pullback_ma10": 10, "pullback_ma20": 10,
                 "pullback_ma50": 7, "breaking": 8, "breakout": 6, "riding": 4,
                 "acceleration": 2, "consolidating": 3}
PB_MICRO_W_1D = {"bounce_ma10": 12, "bounce_ma20": 10, "pullback_ma10": 8, "pullback_ma20": 8,
                 "pullback_ma50": 6, "breaking": 7, "breakout": 5, "riding": 3,
                 "acceleration": 2, "consolidating": 3}

PB_VOL_FLAG_W = {"accumulation": 10, "accumulation_suspect": 6, "normal": 2,
                 "breakout_volume": 4, "distribution_suspect": -8, "distribution": -15}

PB_MAX = 25 + 20 + 5 + 14 + 12 + 12 + 10 + 10  # = 113


def score_pullback_label(label: dict, fresh: dict) -> dict:
    """visual label + fresh facts → pullback 점수 dict.

    Args:
      label : visual_review JSON (load_visual_label 결과)
      fresh : ``{"tf_1d": {...}, "tf_1w": {...}, "tf_1m": {...}}`` (load_fresh_facts 결과)

    Returns:
      ``{"pb_score": float, "pb_pct": float, "cut_pb": bool}``
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
    tf_1w = fresh.get("tf_1w", {}) or {}
    acc_d = (tf_1d.get("accumulation") or {}).get("accumulation_score", 0) or 0
    acc_w = (tf_1w.get("accumulation") or {}).get("accumulation_score", 0) or 0
    ret30 = tf_1d.get("ret_30d", 0) or 0
    from_high = tf_1d.get("from_period_high_pct", 0) or 0

    sc = 0
    sc += PB_STATE_W_1W.get(s_1w, 0)
    sc += PB_STATE_W_1D.get(s_1d, 0)
    sc += PB_STATE_W_1M_BONUS.get(s_1m, 0)
    sc += PB_MICRO_W_1W.get(m_1w, 0)
    sc += PB_MICRO_W_1D.get(m_1d, 0)
    sc += acc_w * 12
    sc += acc_d * 10
    sc += PB_VOL_FLAG_W.get(v_1w, 0)

    # 페널티 — 눌림목 진입 자리 아닌 신호
    for f in risk_flags:
        if f == "parabolic":
            sc -= 15
        elif f in ("distribution", "distribution_suspect", "pump_dump", "blowoff"):
            sc -= 12
        elif f == "drawdown_deep":
            sc -= 8
    if ret30 > 0.5:
        sc -= 15
    elif ret30 > 0.3:
        sc -= 8
    if from_high > -0.03:
        sc -= 5
    if from_high < -0.5:
        sc -= 10
    if ret30 < -0.2:
        sc -= 10

    # 컷
    cut = (verdict == "reject")
    if s_1m in ("B1", "B2") and s_1w not in ("A3", "A4", "A5", "B4", "B5"):
        cut = True

    return {
        "pb_score": round(sc, 1),
        "pb_pct": round(100 * sc / PB_MAX, 1),
        "cut_pb": cut,
    }
