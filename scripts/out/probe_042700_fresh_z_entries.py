"""한미반도체 — Fresh Z 진입 시점 + ★T 출구 시뮬레이션.

룰:
  진입 = fresh Z = "오늘 Z통과 AND 어제 Z 아님"
  보유 = Z 유지 중
  출구:
    A. ★T 발동 (intra ≥ 5% AND close > open) → 그날 종가에 익절
    B. 손절 = 정배열 깨짐 (close ≤ MA20 OR MA10 ≤ MA20)
    C. 시간초과 = MAX_HOLD_BARS 봉 안 ★T 안 나오면 그날 종가에 청산

스캔: 2025-09-01 ~ 2026-06-15
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.mtf_loader import load_normalized_daily

SYM = "042700"
ATR_WIN = 20
GAP_IN_ATR_MAX = 0.5
INTRA_MIN = 0.05
MAX_HOLD_BARS = 10

START = pd.Timestamp("2025-09-01")
END = pd.Timestamp("2026-06-15")


def main():
    df = load_normalized_daily("kr", SYM).sort_index().copy()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["gap_abs"] = df["ma10"] - df["ma20"]
    df["tr"] = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs()
    ], axis=1).max(axis=1)
    df["atr"] = df["tr"].rolling(ATR_WIN).mean()
    df["gap_in_atr"] = df["gap_abs"] / df["atr"]
    df["intra"] = (df["close"] - df["open"]) / df["open"]
    df["Z"] = (df["ma10"] > df["ma20"]) & (df["gap_in_atr"].abs() <= GAP_IN_ATR_MAX) & (df["close"] > df["ma20"])
    df["T_star"] = df["Z"] & (df["intra"] >= INTRA_MIN) & (df["close"] > df["open"])

    # fresh Z = 오늘 Z AND 어제 Z 아님
    df["fresh_Z"] = df["Z"] & (~df["Z"].shift(1).fillna(False))

    scan = df.loc[START:END]
    fresh = scan[scan["fresh_Z"]]

    print(f"=== 한미반도체 fresh Z 진입 시점 ({len(fresh)}회) ===\n")

    records = []
    for entry_date, entry_row in fresh.iterrows():
        entry_close = entry_row["close"]
        entry_idx = df.index.get_loc(entry_date)

        exit_reason = None
        exit_date = None
        exit_close = None
        bars_held = 0
        days_to_T = None

        # 진입 다음 봉부터 검사
        for j in range(1, MAX_HOLD_BARS + 1):
            if entry_idx + j >= len(df):
                break
            cur = df.iloc[entry_idx + j]
            bars_held = j
            # 손절: 정배열 깨짐
            if not (cur["ma10"] > cur["ma20"]) or cur["close"] <= cur["ma20"]:
                exit_reason = "STOP (정배열 깨짐)"
                exit_date = df.index[entry_idx + j]
                exit_close = cur["close"]
                break
            # ★T 트리거: 그날 익절
            if cur["T_star"]:
                exit_reason = "★T (장대양봉 익절)"
                exit_date = df.index[entry_idx + j]
                exit_close = cur["close"]
                days_to_T = j
                break
        else:
            # 시간초과
            j = min(MAX_HOLD_BARS, len(df) - 1 - entry_idx)
            exit_reason = f"TIMEOUT ({MAX_HOLD_BARS}봉)"
            exit_date = df.index[entry_idx + j]
            exit_close = df.iloc[entry_idx + j]["close"]
            bars_held = j

        ret_pct = (exit_close / entry_close - 1) * 100
        records.append({
            "entry_date": entry_date.date(),
            "entry_close": entry_close,
            "intra_at_entry": entry_row["intra"] * 100,
            "gap_in_atr": entry_row["gap_in_atr"],
            "exit_date": exit_date.date() if exit_date else None,
            "exit_close": exit_close,
            "bars_held": bars_held,
            "ret_pct": ret_pct,
            "exit_reason": exit_reason,
        })

    rdf = pd.DataFrame(records)
    print(rdf.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))

    print()
    print("=== 요약 ===")
    s = rdf["ret_pct"]
    print(f"진입 횟수: {len(rdf)}")
    print(f"평균 수익률: {s.mean():+.2f}%  중앙값: {s.median():+.2f}%  승률: {(s>0).mean()*100:.0f}%")

    by_reason = rdf.groupby("exit_reason").agg(n=("ret_pct","count"), mean=("ret_pct","mean"))
    print("\n=== 출구 사유별 ===")
    print(by_reason.to_string(float_format=lambda v: f"{v:.2f}"))

    out_csv = Path(__file__).parent / "_probe_042700_fresh_z_entries.csv"
    rdf.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
