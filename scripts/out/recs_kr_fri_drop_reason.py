"""금요일 탈락 73 종목 — 어떤 게이트에서 컷됐는지 분해.

각 종목은 5 TF 중 어떤 TF든 통과하면 OK. 탈락 = 모든 TF 의 모든 게이트 중 적어도 하나가 fail.
각 TF 별로 어떤 게이트가 fail 했는지 추적, **목요일엔 어떤 TF 로 통과했던지** 도 함께 표시.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.mtf_loader import load_normalized_daily, resample_multi_tf
from scripts._common.mtf_indicators import compute_mtf_indicators
from scripts._common.signals import (
    K_DIST_THRESHOLD, N_ATR_WINDOW, _compute_range_threshold,
)
from scripts._common.tf_selector import determine_eval_kind, select_eval_tfs
from scripts._common.recommend_runner import EVAL_TFS, MIN_DAILY_BARS

THU = pd.Timestamp("2026-06-11")
FRI = pd.Timestamp("2026-06-12")


def gate_state(df_tf: pd.DataFrame, df_daily: pd.DataFrame, kind: str, today_low: float) -> Optional[dict]:
    """단일 TF 의 모든 게이트 상태를 raw 로 반환. skip / 데이터부족이면 None."""
    if kind == "skip" or len(df_tf) < 1:
        return None
    last = df_tf.iloc[-1]
    close = last["close"]
    ma10 = last["ma10"]
    ma20 = last.get("ma20")
    slope10 = last["slope_pct_ma10"]
    slope20 = last.get("slope_pct_ma20")

    th = _compute_range_threshold(df_daily)
    if pd.isna(th):
        return None

    state = {"kind": kind, "th": th, "close": close, "low": today_low,
             "ma10": ma10, "ma20": ma20, "slope10": slope10, "slope20": slope20}

    if kind == "full":
        if any(pd.isna(x) for x in (ma10, ma20, slope10, slope20)):
            return None
        state["g_align"] = (ma10 > ma20) and (close > ma20)
        state["g_slope"] = (slope10 > 0) and (slope20 > 0)
        d10 = abs(today_low - ma10)
        d20 = abs(today_low - ma20)
        state["d10"] = d10
        state["d20"] = d20
        state["g_touch"] = (d10 <= th) or (d20 <= th)
        state["near_dist"] = min(d10, d20) / th if th > 0 else float("inf")  # 1.0 이면 정확히 임계
    else:  # partial
        if any(pd.isna(x) for x in (ma10, slope10)):
            return None
        state["g_align"] = close > ma10
        state["g_slope"] = slope10 > 0
        d10 = abs(today_low - ma10)
        state["d10"] = d10
        state["g_touch"] = d10 <= th
        state["near_dist"] = d10 / th if th > 0 else float("inf")
        # partial 의 consec 게이트는 별도
        from scripts._common.signals import PARTIAL_CONSEC_BARS
        tail = df_tf.tail(PARTIAL_CONSEC_BARS)
        state["g_consec"] = bool((tail["close"] > tail["ma10"]).all())
    state["passed"] = state["g_align"] and state["g_slope"] and state["g_touch"] and (state.get("g_consec", True) if kind == "partial" else True)
    return state


def classify_fri_fail(states: dict) -> str:
    """전 TF state dict → 가장 'aspirational' 한 TF 의 fail reason 한 단어 분류.

    'aspirational' = 정배열 + slope 다 통과, touch 만 깬 TF (가장 아까운 케이스).
    그 외 패턴 fall-through.
    """
    align_slope_ok = [(tf, st) for tf, st in states.items() if st and st["g_align"] and st["g_slope"]]
    if align_slope_ok:
        # touch 만 깨졌다 — 가장 가까운 TF 의 near_dist 로 분류
        touch_fail = [(tf, st) for tf, st in align_slope_ok if not st["g_touch"]]
        if touch_fail:
            tf, st = min(touch_fail, key=lambda x: x[1]["near_dist"])
            # low 가 MA 위로 멀어졌는지 / 아래로 깊이 깨졌는지
            d_signed_10 = st["low"] - st["ma10"]
            d_signed_20 = st["low"] - st.get("ma20", st["ma10"])
            # MA20 기준이 보통 더 robust — MA20 위면 '위로 갭', 아래면 '아래 이탈'
            side = "위로 갭(MA 멀어짐)" if d_signed_20 > 0 else "아래로 이탈"
            return f"touch fail [{tf}, {side}, near={st['near_dist']:.2f}]"
        # touch 통과한 게 있는데 왜 안 됐지? align/slope 도 다 ok 면 passed=True 라 여기 안 옴
        return "unknown"
    align_ok = [(tf, st) for tf, st in states.items() if st and st["g_align"] and not st["g_slope"]]
    if align_ok:
        return "slope 깨짐 (정배열은 ok)"
    slope_ok = [(tf, st) for tf, st in states.items() if st and st["g_slope"] and not st["g_align"]]
    if slope_ok:
        return "정배열 깨짐 (slope+은 ok)"
    return "정배열 + slope 둘 다 깨짐"


def evaluate_symbol_at(asset: str, sym: str, cutoff: pd.Timestamp) -> Optional[dict]:
    try:
        df_d = load_normalized_daily(asset, sym)
    except Exception:
        return None
    df_d = df_d[df_d.index <= cutoff]
    if len(df_d) < MIN_DAILY_BARS:
        return None
    mtf = resample_multi_tf(df_d)
    allowed = set(select_eval_tfs(mtf))
    today_low = float(df_d["low"].iloc[-1])
    states: dict = {}
    for tf in EVAL_TFS:
        if tf not in allowed:
            states[tf] = None
            continue
        df_tf = mtf[tf]
        kind = determine_eval_kind(df_tf)
        if kind == "skip":
            states[tf] = None
            continue
        df_ind = compute_mtf_indicators(df_tf, kind)
        states[tf] = gate_state(df_ind, df_d, kind, today_low)
    return states


def main():
    asset = "kr"
    drop_csv = Path(__file__).parent / "_recs_kr_fri_drop.csv"
    df = pd.read_csv(drop_csv, dtype={"Symbol": str})

    rows = []
    for sym, name in zip(df["Symbol"], df["Name"]):
        thu_states = evaluate_symbol_at(asset, sym, THU)
        fri_states = evaluate_symbol_at(asset, sym, FRI)
        if not thu_states or not fri_states:
            continue
        # 목요일 통과 TF (참고)
        thu_pass_tfs = [tf for tf, st in thu_states.items() if st and st["passed"]]
        # 금요일 fail 사유
        reason = classify_fri_fail(fri_states)
        rows.append({
            "Symbol": sym, "Name": name,
            "thu_pass_TF": ",".join(thu_pass_tfs),
            "fri_fail_reason": reason,
        })

    out = pd.DataFrame(rows)
    cat = out["fri_fail_reason"].str.extract(r"^(touch fail|slope 깨짐|정배열 깨짐|정배열 \+ slope|unknown)")[0]
    cat = cat.fillna("기타")
    out["category"] = cat

    summary = out["category"].value_counts()
    print("=== 금요일 탈락 사유 분류 ===")
    for k, v in summary.items():
        print(f"  {k:30s}  {v}")

    # touch fail 의 세부 (위로 갭 vs 아래로 이탈)
    touch_fail = out[out["category"] == "touch fail"]
    if len(touch_fail) > 0:
        side = touch_fail["fri_fail_reason"].str.extract(r", (위로 갭\(MA 멀어짐\)|아래로 이탈),")[0]
        side_summary = side.value_counts()
        print("\n=== touch fail 세부 ===")
        for k, v in side_summary.items():
            print(f"  {k:30s}  {v}")

    out_csv = Path(__file__).parent / "_recs_kr_fri_drop_reason.csv"
    out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n총 {len(out)} 종목 분류")
    print(f"CSV: {out_csv.relative_to(_ROOT)}")

    # 샘플 — touch fail 상위 5 (가까웠던)
    print("\n=== touch fail 샘플 (15) ===")
    print(touch_fail.head(15)[["Symbol", "Name", "thu_pass_TF", "fri_fail_reason"]].to_string(index=False))


if __name__ == "__main__":
    main()
