"""오늘 코인 추천: coin_state(오늘 review) + fresh entry facts (1d/4h/1h) 결합 스코어링."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np
from scripts._common.visual_review.facts import compute_facts_all_tfs

REVIEW_DATE = "2026-05-21"

STOCK_TOKENS = {
    "AAPLUSDT", "AMDUSDT", "AMZNUSDT", "ARMUSDT", "COINUSDT", "COPPERUSDT",
    "COSTUSDT", "GOOGLUSDT", "INTCUSDT", "JDUSDT", "METAUSDT", "MRVLUSDT",
    "MSFTUSDT", "NFLXUSDT", "NVDAUSDT", "QQQUSDT", "SPYUSDT", "TSLAUSDT", "UNHUSDT",
}

state_score_map = {
    "A1": 0.85, "A2": 1.00, "A3": 0.10, "A4": -0.30, "A5": -0.50,
    "B1": -0.40, "B2": -0.20, "B3": 0.30, "B4": 0.55, "B5": 0.95,
    "C1": -0.50,
}
vol_score_map = {
    "normal": 0.0, "accumulation_suspect": 0.30,
    "distribution_suspect": -0.40, "dry": -0.20, "pump_dump_trace": -1.0,
    None: 0.0,
}
risk_pen = {
    "parabolic": -0.30,
    "pump_dump_trace": -1.0,
    "low_history": -0.10,
    "drawdown_deep": 0.0,  # buy zone 코인엔 자연스러움, 페널티 X
    "zombie": -0.50,
    "distribution_suspect": -0.30,
    "accumulation_suspect": 0.0,
}

def review_score(row) -> float:
    s = 0.0
    # weight: 1m 0.3, 1w 0.4, 1d 0.3
    for tf, w in (("1m", 0.3), ("1w", 0.4), ("1d", 0.3)):
        s += state_score_map.get(row[f"state_{tf}"], 0.0) * w
        s += vol_score_map.get(row[f"volume_flag_{tf}"], 0.0) * w * 0.3
    if row["verdict_confidence"] == "high":
        s += 0.10
    elif row["verdict_confidence"] == "low":
        s -= 0.10
    if row["tf_consistency"] == "정합":
        s += 0.10
    elif row["tf_consistency"] == "충돌":
        s -= 0.15
    # risk flags
    rf = str(row["risk_flags"] or "")
    for k, v in risk_pen.items():
        if k in rf:
            s += v
    return s

def entry_score(facts: dict) -> tuple[float, dict]:
    """1d+4h+1h facts → 진입 트리거 점수."""
    if facts is None:
        return -10.0, {}
    s = 0.0
    info = {}
    # 1d: nearest_ma 가까울수록 + ma_stack 정배열 + slope up
    f1d = facts.get("tf_1d", {})
    f4h = facts.get("tf_4h", {})
    f1h = facts.get("tf_1h", {})
    if not f1d:
        return -10.0, {}

    # 1d ma stack + slope
    if f1d.get("ma_stack") == "정배열": s += 0.30
    elif f1d.get("ma_stack") == "역배열": s -= 0.30
    if f1d.get("ma_slopes", {}).get("ma20") == "up": s += 0.20
    elif f1d.get("ma_slopes", {}).get("ma20") == "down": s -= 0.20

    # nearest_ma distance (1d, ATR 단위) — MA10/MA20에 닿아있을수록 좋음
    nma = f1d.get("nearest_ma", {})
    info["1d_near_ma"] = nma.get("ma")
    info["1d_near_dist_pct"] = nma.get("dist_pct")
    atr_dist = abs(f1d.get("dist_from_ma_atr", {}).get(f"{nma.get('ma','ma10')}_atr", 99) or 99)
    info["1d_near_atr"] = atr_dist
    if nma.get("ma") in ("ma10", "ma20") and atr_dist < 1.0:
        s += 0.40 * (1.0 - atr_dist)  # 1ATR 안일수록 +
    elif nma.get("ma") == "ma50" and atr_dist < 0.5:
        s += 0.20 * (0.5 - atr_dist)

    # recent strong bull on 1d (holding)
    rsb_1d = f1d.get("recent_strong_bull")
    if rsb_1d and rsb_1d.get("holding"):
        bars = rsb_1d.get("bars_ago", 99) or 99
        info["1d_bull_ago"] = bars
        info["1d_bull_body"] = rsb_1d.get("body_pct")
        if bars <= 5:
            s += 0.40
        elif bars <= 10:
            s += 0.20

    # 1d acc / dist score
    lc = f1d.get("last_candle", {})
    acc_s = lc.get("accumulation_candle_score", 0.0) or 0.0
    dist_s = lc.get("distribution_candle_score", 0.0) or 0.0
    s += acc_s * 0.30
    s -= dist_s * 0.30

    # 1d ADX (추세 강도)
    adx = f1d.get("adx") or 0
    info["1d_adx"] = adx
    if 25 <= adx <= 50:
        s += 0.15
    elif adx > 75:  # 페러볼릭
        s -= 0.15

    # 4h/1h MA20 슬로프 일치 보너스
    for tf_facts, w in ((f4h, 0.10), (f1h, 0.05)):
        if not tf_facts: continue
        if tf_facts.get("ma_slopes", {}).get("ma20") == "up": s += w
        if tf_facts.get("ma_stack") == "정배열": s += w * 0.5

    # 1h recent_strong_bull holding (단기 모멘텀)
    rsb_1h = f1h.get("recent_strong_bull") if f1h else None
    if rsb_1h and rsb_1h.get("holding"):
        bars = rsb_1h.get("bars_ago", 99) or 99
        if bars <= 12:
            s += 0.10

    return s, info


def main():
    state = pd.read_parquet("data/cache/crypto/visual_review/coin_state.parquet")
    state = state[state["last_review_date"].astype(str) == REVIEW_DATE].copy()
    print(f"today review: {len(state)} symbols")

    # 나스닥 토큰화 주식/ETF 제외
    state = state[~state["symbol"].isin(STOCK_TOKENS)]

    # 펌프&덤프, zombie, reject 컷
    state = state[state["verdict"] != "reject"]
    rf = state["risk_flags"].fillna("").astype(str)
    state = state[~rf.str.contains("pump_dump_trace")]
    state = state[~rf.str.contains("zombie")]
    print(f"after reject/pump/stock cut: {len(state)}")

    # review score 계산
    state["rev_score"] = state.apply(review_score, axis=1)

    # 상위 60개에 대해 fresh entry facts 계산 (시간 절약)
    top = state.sort_values("rev_score", ascending=False).head(80).copy()
    print(f"computing entry facts for top {len(top)} ...")

    rows = []
    for i, r in enumerate(top.itertuples(index=False), 1):
        sym = r.symbol
        try:
            facts = compute_facts_all_tfs(sym, asset="crypto", tfs=["1d","4h","1h"])
        except Exception as e:
            facts = None
        e_score, info = entry_score(facts)
        rows.append({
            "symbol": sym,
            "rev_score": r.rev_score,
            "ent_score": e_score,
            "total": r.rev_score + e_score,
            "state_1w": r.state_1w,
            "state_1d": r.state_1d,
            "micro_1d": r.micro_action_1d,
            "vol_1d": r.volume_flag_1d,
            "tf_cons": r.tf_consistency,
            "vconf": r.verdict_confidence,
            "verdict": r.verdict,
            **info,
            "risks": r.risk_flags,
        })
        if i % 20 == 0:
            print(f"  {i}/{len(top)}")

    out = pd.DataFrame(rows).sort_values("total", ascending=False)
    out_path = Path("data/cache/crypto/visual_review/_rec_now.parquet")
    out.to_parquet(out_path, index=False)
    print(f"\nsaved {out_path}")
    print()
    print("=== TOP 20 ===")
    cols = ["symbol","total","rev_score","ent_score","state_1w","state_1d","micro_1d","vol_1d","tf_cons","vconf","verdict","1d_near_ma","1d_near_dist_pct","1d_near_atr","1d_bull_ago","1d_adx","risks"]
    print(out.head(20)[cols].to_string(index=False))


if __name__ == "__main__":
    main()
