"""한미반도체(042700) — 2026-01-01~오늘 일별 ma_touch + 0.5°+80% 필터 통과 여부.

각 거래일에 대해:
  - cutoff 까지 mtf 빌드
  - 통과 TF (있으면 angle 가장 큰 것) 노출
  - 그 날 종가, 일변동, angle, residence 같이 표시
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.mtf_loader import load_normalized_daily, resample_multi_tf
from scripts._common.mtf_indicators import compute_mtf_indicators
from scripts._common.signals import _compute_range_threshold, PARTIAL_CONSEC_BARS
from scripts._common.tf_selector import determine_eval_kind, select_eval_tfs
from scripts._common.recommend_runner import EVAL_TFS, MIN_DAILY_BARS

SYM = "042700"  # 한미반도체
ANGLE_MIN = 0.5
RES_MIN = 0.80
RES_WINDOW = 20

START = pd.Timestamp("2026-01-01")
END = pd.Timestamp("2026-06-15")


def evaluate_one(df_full, cutoff: pd.Timestamp):
    df_d = df_full[df_full.index <= cutoff]
    if len(df_d) < MIN_DAILY_BARS or cutoff not in df_d.index:
        return None
    mtf = resample_multi_tf(df_d)
    allowed = set(select_eval_tfs(mtf))
    today_low = float(df_d["low"].iloc[-1])
    th = _compute_range_threshold(df_d)
    if pd.isna(th):
        return None

    best = None
    for tf in EVAL_TFS:
        df_tf = mtf[tf]
        kind = determine_eval_kind(df_tf)
        if (tf not in allowed) or kind == "skip":
            continue
        df_ind = compute_mtf_indicators(df_tf, kind)
        if len(df_ind) < 1:
            continue
        last = df_ind.iloc[-1]
        close = last["close"]
        ma10 = last["ma10"]
        sl10 = last["slope_pct_ma10"]
        if pd.isna(ma10) or pd.isna(sl10):
            continue

        if kind == "full":
            ma20 = last["ma20"]
            sl20 = last["slope_pct_ma20"]
            if pd.isna(ma20) or pd.isna(sl20):
                continue
            if not ((ma10 > ma20) and (close > ma20) and sl10 > 0 and sl20 > 0):
                continue
            d10 = abs(today_low - ma10)
            d20 = abs(today_low - ma20)
            if not (d10 <= th or d20 <= th):
                continue
            angle = float(last.get("angle_ma20_deg", float("nan")))
            tail = df_ind.tail(RES_WINDOW)
            if len(tail) < RES_WINDOW:
                continue
            residence = float((tail["close"] > tail["ma20"]).mean())
        else:
            if not (close > ma10 and sl10 > 0):
                continue
            d10 = abs(today_low - ma10)
            if not (d10 <= th):
                continue
            tail3 = df_ind.tail(PARTIAL_CONSEC_BARS)
            if not (tail3["close"] > tail3["ma10"]).all():
                continue
            angle = float(last.get("angle_ma10_deg", float("nan")))
            tail = df_ind.tail(RES_WINDOW)
            if len(tail) < RES_WINDOW:
                continue
            residence = float((tail["close"] > tail["ma10"]).mean())

        if pd.isna(angle):
            continue
        if angle < ANGLE_MIN or residence < RES_MIN:
            continue
        if best is None or angle > best["angle_deg"]:
            best = {"tf": tf, "angle_deg": angle, "residence_20": residence}
    return best


def main():
    df_full = load_normalized_daily("kr", SYM)
    dates = df_full.index[(df_full.index >= START) & (df_full.index <= END)]
    print(f"한미반도체(042700) — 평가 거래일: {len(dates)} 개", file=sys.stderr)

    rows = []
    for d in dates:
        c = float(df_full.loc[d, "close"])
        prev_idx = df_full.index.searchsorted(d) - 1
        if prev_idx < 0:
            day_ret = float("nan")
        else:
            prev_c = float(df_full.iloc[prev_idx]["close"])
            day_ret = (c - prev_c) / prev_c * 100

        res = evaluate_one(df_full, d)
        row = {"date": d.date(), "close": c, "day_ret_pct": day_ret,
               "pass": res is not None,
               "tf": res["tf"] if res else None,
               "angle_deg": res["angle_deg"] if res else None,
               "residence_20": res["residence_20"] if res else None}
        rows.append(row)

    df = pd.DataFrame(rows)
    passed = df[df["pass"]]

    print(f"\n[042700 한미반도체]  2026-01-01 ~ {END.date()}")
    print(f"  평가 거래일: {len(df)}")
    print(f"  통과 횟수  : {len(passed)}")
    print(f"  통과 비율  : {len(passed)/len(df)*100:.1f}%")
    print()
    print(f"=== 일별 통과 ({len(passed)}건) ===")
    if len(passed):
        print(passed.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    else:
        print("(통과 없음)")

    print()
    print("=== 전체 일별 (요약 — 통과만) ===")
    print(df.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    out_csv = Path(__file__).parent / "_probe_042700_daily_signal.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
