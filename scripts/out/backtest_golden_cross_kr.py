"""KR 전체 — Fresh Z 진입 + ★T 익절 / STOP / TIMEOUT 출구 백테스트.

룰 (최종):
  진입 = fresh Z = "오늘 Z 통과 AND 어제 Z 아님"
    Z = MA10 > MA20  AND  close > MA20  AND  |gap_abs|/ATR20 ≤ 0.5

  출구 (우선순위):
    A. STOP  = 정배열 깨짐 (MA10 ≤ MA20  OR  close ≤ MA20)
    B. ★T    = Z 유지 중 장대양봉 (intra ≥ 5%, close > open)
    C. TIMEOUT = 10봉 안 ★T 안 나오면 그날 종가

스캔: 2025-09-01 ~ 2026-06-15
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.mtf_loader import load_normalized_daily
from scripts._common.recommend_runner import discover_universe

ATR_WIN = 20
GAP_IN_ATR_MAX = 0.5
INTRA_MIN = 0.05
MAX_HOLD_BARS = 10

START = pd.Timestamp("2025-09-01")
END = pd.Timestamp("2026-06-15")


def simulate(sym: str, df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["gap_abs"] = df["ma10"] - df["ma20"]
    df["tr"] = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = df["tr"].rolling(ATR_WIN).mean()
    df["gap_in_atr"] = df["gap_abs"] / df["atr"]
    df["intra"] = (df["close"] - df["open"]) / df["open"]
    df["Z"] = (df["ma10"] > df["ma20"]) & (df["gap_in_atr"].abs() <= GAP_IN_ATR_MAX) & (df["close"] > df["ma20"])
    df["T_star"] = df["Z"] & (df["intra"] >= INTRA_MIN) & (df["close"] > df["open"])
    df["fresh_Z"] = df["Z"] & (~df["Z"].shift(1).fillna(False).astype(bool))

    scan = df[(df.index >= START) & (df.index <= END)]
    fresh_idxs = scan.index[scan["fresh_Z"]]

    out = []
    for entry_date in fresh_idxs:
        entry_row = df.loc[entry_date]
        entry_close = entry_row["close"]
        entry_idx = df.index.get_loc(entry_date)

        exit_reason = None
        exit_date = None
        exit_close = None
        bars_held = 0

        for j in range(1, MAX_HOLD_BARS + 1):
            if entry_idx + j >= len(df):
                break
            cur = df.iloc[entry_idx + j]
            bars_held = j
            # 손절
            if (not (cur["ma10"] > cur["ma20"])) or (cur["close"] <= cur["ma20"]):
                exit_reason = "STOP"
                exit_date = df.index[entry_idx + j]
                exit_close = cur["close"]
                break
            # 익절
            if cur["T_star"]:
                exit_reason = "T_star"
                exit_date = df.index[entry_idx + j]
                exit_close = cur["close"]
                break
        else:
            j = min(MAX_HOLD_BARS, len(df) - 1 - entry_idx)
            if j > 0:
                exit_reason = "TIMEOUT"
                exit_date = df.index[entry_idx + j]
                exit_close = df.iloc[entry_idx + j]["close"]
                bars_held = j

        if exit_reason is None or exit_close is None:
            continue   # 진입 후 데이터 부족
        ret_pct = (exit_close / entry_close - 1) * 100
        out.append({
            "Symbol": sym,
            "entry_date": entry_date.date(),
            "entry_close": entry_close,
            "exit_date": exit_date.date(),
            "exit_close": exit_close,
            "bars_held": bars_held,
            "ret_pct": ret_pct,
            "exit_reason": exit_reason,
        })
    return out


def main():
    asset = "kr"
    symbols = discover_universe(asset)
    print(f"universe={len(symbols)}", file=sys.stderr)

    rows = []
    t0 = time.time()
    for i, sym in enumerate(symbols, 1):
        try:
            df = load_normalized_daily(asset, sym)
        except Exception:
            continue
        if len(df) < 60:
            continue
        rows.extend(simulate(sym, df))
        if i % 200 == 0:
            print(f"  [{i}/{len(symbols)}] entries={len(rows)}  elapsed={time.time()-t0:.0f}s", file=sys.stderr)

    listing = pd.read_csv(_ROOT / "data" / "cache" / "kr" / "_listing.csv", dtype={"Symbol": str})
    name_map = dict(zip(listing["Symbol"], listing["Name"]))

    rdf = pd.DataFrame(rows)
    rdf["Name"] = rdf["Symbol"].map(name_map)

    print(f"\n총 진입 횟수: {len(rdf)} ({rdf['Symbol'].nunique()} 종목)")
    s = rdf["ret_pct"]
    print(f"\n=== 전체 통계 ===")
    print(f"  평균    : {s.mean():+.2f}%")
    print(f"  중앙값  : {s.median():+.2f}%")
    print(f"  std     : {s.std():.2f}%")
    print(f"  승률    : {(s>0).mean()*100:.1f}%")
    print(f"  max     : {s.max():+.2f}%")
    print(f"  min     : {s.min():+.2f}%")
    print(f"  평균 보유봉: {rdf['bars_held'].mean():.1f}봉")

    print(f"\n=== 출구 사유별 ===")
    by = rdf.groupby("exit_reason").agg(
        n=("ret_pct", "count"),
        mean=("ret_pct", "mean"),
        median=("ret_pct", "median"),
        win=("ret_pct", lambda s: (s > 0).mean() * 100),
        avg_bars=("bars_held", "mean"),
    )
    by["pct"] = by["n"] / by["n"].sum() * 100
    print(by.to_string(float_format=lambda v: f"{v:.2f}"))

    print(f"\n=== 월별 진입 분포 ===")
    rdf["entry_month"] = pd.to_datetime(rdf["entry_date"]).dt.to_period("M").astype(str)
    by_m = rdf.groupby("entry_month").agg(
        n=("ret_pct", "count"),
        mean=("ret_pct", "mean"),
        win=("ret_pct", lambda s: (s > 0).mean() * 100),
    )
    print(by_m.to_string(float_format=lambda v: f"{v:.2f}"))

    print(f"\n=== 상위 15 ===")
    top = rdf.sort_values("ret_pct", ascending=False).head(15)
    print(top[["entry_date","Symbol","Name","entry_close","exit_close","bars_held","ret_pct","exit_reason"]].to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    print(f"\n=== 하위 15 ===")
    bot = rdf.sort_values("ret_pct").head(15)
    print(bot[["entry_date","Symbol","Name","entry_close","exit_close","bars_held","ret_pct","exit_reason"]].to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    out_csv = Path(__file__).parent / "_backtest_golden_cross_kr.csv"
    rdf.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
