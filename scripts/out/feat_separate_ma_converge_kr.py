"""KR 전체 — 수렴자리(fresh_Z) 진입 + 5개 후보 피처 분리력 백테스트.

목적: "오르는 중(눌림)" vs "고점 찍고 하락(천장)" 을 가르는 피처 탐색.
엔진은 close 게이트 없이 순수 Z (정배열+수렴+close>MA20+주봉정배열+유동성).
각 fresh_Z 진입에 5개 피처를 붙여 실제 거래수익률(STOP/★T/TIMEOUT 10봉)과의
분리력(quintile)을 측정.

후보 피처 (전부 신호일 t까지만 — 룩어헤드 없음):
  1 ma60_slope     = (MA60[t]-MA60[t-20])/MA60[t-20]*100   장기추세 방향
  2 ma20_slope_atr = (MA20[t]-MA20[t-10])/ATR20             중기추세 방향(조기 꺾임)
  3 dd_from_high   = (max(high,20봉)-close)/ATR20           고점 대비 낙폭(롤오버)
  4 rsi14          = RSI(14)                                모멘텀 과열/소진
  5 vol_dist       = 최근10봉 음봉vol/양봉vol                분배 vs 매집
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.mtf_loader import load_normalized_daily, resample_multi_tf
from scripts._common.recommend_runner import discover_universe

ATR_WIN = 20
GAP_IN_ATR_MAX = 0.5
INTRA_MIN = 0.05
MAX_HOLD_BARS = 10
MIN_TRADE_VAL = 1e9
START = pd.Timestamp("2025-09-01")
END = pd.Timestamp("2026-06-15")

FEATS = ["ma60_slope", "ma20_slope_atr", "dd_from_high", "rsi14", "vol_dist"]


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def compute(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["gap_abs"] = df["ma10"] - df["ma20"]
    df["tr"] = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = df["tr"].rolling(ATR_WIN).mean()
    df["gap_in_atr"] = df["gap_abs"] / df["atr"]
    df["close_ma_atr"] = (df["close"] - df["ma20"]) / df["atr"]
    df["intra"] = (df["close"] - df["open"]) / df["open"]
    df["tval20"] = (df["close"] * df["volume"]).rolling(20).median()

    # --- 5개 피처 ---
    df["ma60_slope"] = (df["ma60"] - df["ma60"].shift(20)) / df["ma60"].shift(20) * 100
    df["ma20_slope_atr"] = (df["ma20"] - df["ma20"].shift(10)) / df["atr"]
    df["dd_from_high"] = (df["high"].rolling(20).max() - df["close"]) / df["atr"]
    df["rsi14"] = rsi(df["close"], 14)
    up_day = df["close"] > df["close"].shift(1)
    up_vol = df["volume"].where(up_day, 0.0).rolling(10).sum()
    dn_vol = df["volume"].where(~up_day, 0.0).rolling(10).sum()
    df["vol_dist"] = dn_vol / up_vol.replace(0, np.nan)

    # 주봉 정배열
    mtf = resample_multi_tf(df)
    w = mtf["1W"].copy()
    w["m10"] = w["close"].rolling(10).mean()
    w["m20"] = w["close"].rolling(20).mean()
    w["wal"] = (w["m10"] > w["m20"]) & w["m10"].notna() & w["m20"].notna()
    df["weekly_align"] = w["wal"].reindex(df.index, method="ffill").fillna(False).astype(bool)

    df["Z"] = (
        (df["ma10"] > df["ma20"])
        & (df["gap_in_atr"].abs() <= GAP_IN_ATR_MAX)
        & (df["close"] > df["ma20"])
        & df["weekly_align"]
        & (df["tval20"] >= MIN_TRADE_VAL)
    )
    df["T_star"] = df["Z"] & (df["intra"] >= INTRA_MIN) & (df["close"] > df["open"])
    df["fresh_Z"] = df["Z"] & (~df["Z"].shift(1).fillna(False).astype(bool))
    return df


def simulate(sym: str, df: pd.DataFrame) -> list[dict]:
    df = compute(df)
    scan = df[(df.index >= START) & (df.index <= END)]
    fresh_idxs = scan.index[scan["fresh_Z"]]
    closes = df["close"]
    out = []
    for entry_date in fresh_idxs:
        entry_idx = df.index.get_loc(entry_date)
        entry_row = df.iloc[entry_idx]
        entry_close = entry_row["close"]
        if any(pd.isna(entry_row[f]) for f in FEATS):
            continue
        exit_reason = exit_close = None
        bars_held = 0
        for j in range(1, MAX_HOLD_BARS + 1):
            if entry_idx + j >= len(df):
                break
            cur = df.iloc[entry_idx + j]
            bars_held = j
            if (not (cur["ma10"] > cur["ma20"])) or (cur["close"] <= cur["ma20"]):
                exit_reason, exit_close = "STOP", cur["close"]
                break
            if cur["T_star"]:
                exit_reason, exit_close = "T_star", cur["close"]
                break
        else:
            j = min(MAX_HOLD_BARS, len(df) - 1 - entry_idx)
            if j > 0:
                exit_reason, exit_close, bars_held = "TIMEOUT", df.iloc[entry_idx + j]["close"], j
        if exit_reason is None or exit_close is None:
            continue
        rec = {
            "Symbol": sym, "entry_date": entry_date.date(),
            "entry_close": entry_close, "bars_held": bars_held,
            "ret_pct": (exit_close / entry_close - 1) * 100, "exit_reason": exit_reason,
            "close_ma_atr": float(entry_row["close_ma_atr"]),
        }
        for f in FEATS:
            rec[f] = float(entry_row[f])
        out.append(rec)
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
        if len(df) < 90:
            continue
        rows.extend(simulate(sym, df))
        if i % 200 == 0:
            print(f"  [{i}/{len(symbols)}] trades={len(rows)}  {time.time()-t0:.0f}s", file=sys.stderr)

    rdf = pd.DataFrame(rows)
    listing = pd.read_csv(_ROOT / "data" / "cache" / "kr" / "_listing.csv", dtype={"Symbol": str})
    rdf["Name"] = rdf["Symbol"].map(dict(zip(listing["Symbol"], listing["Name"])))

    print(f"\n[5피처 분리력 — 순수 Z, 유동성≥10억, {START.date()}~{END.date()}]")
    s = rdf["ret_pct"]
    print(f"전체: {len(rdf)} 거래 / {rdf['Symbol'].nunique()} 종목 | 평균 {s.mean():+.2f}% | 중앙값 {s.median():+.2f}% | "
          f"승률 {(s>0).mean()*100:.1f}% | STOP {(rdf['exit_reason']=='STOP').mean()*100:.1f}%")

    print(f"\n{'='*70}\n각 피처 5분위(quintile)별 거래 결과  (분리력 = 1분위↔5분위 승률 차)\n{'='*70}")
    sep = {}
    for f in FEATS:
        rdf["q"] = pd.qcut(rdf[f], 5, labels=["Q1(낮음)", "Q2", "Q3", "Q4", "Q5(높음)"], duplicates="drop")
        g = rdf.groupby("q", observed=True).agg(
            n=("ret_pct", "count"), mean=("ret_pct", "mean"), median=("ret_pct", "median"),
            win=("ret_pct", lambda x: (x > 0).mean() * 100),
            stop=("exit_reason", lambda x: (x == "STOP").mean() * 100),
            f_lo=(f, "min"), f_hi=(f, "max"),
        )
        wins = g["win"]
        sep[f] = abs(wins.iloc[-1] - wins.iloc[0])
        print(f"\n--- {f} ---")
        print(g.to_string(float_format=lambda v: f"{v:.2f}"))

    print(f"\n{'='*70}\n피처 분리력 랭킹 (|Q5승률 − Q1승률|, 클수록 잘 가름)\n{'='*70}")
    for f, v in sorted(sep.items(), key=lambda kv: -kv[1]):
        print(f"  {f:>16}: {v:5.1f}%p")

    # 상관(피처끼리 중복 확인)
    print(f"\n=== 피처 상관행렬 (중복 점검) ===")
    print(rdf[FEATS].corr().to_string(float_format=lambda v: f"{v:.2f}"))

    # 새너티 체크 — 한미 좋은 자리 vs 알려진 천장
    print(f"\n=== 새너티 체크: 한미(042700) 진입별 피처 ===")
    hm = rdf[rdf["Symbol"] == "042700"]
    cols = ["entry_date", "ret_pct", "exit_reason", "close_ma_atr"] + FEATS
    if len(hm):
        print(hm[cols].to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    out_csv = Path(__file__).parent / "_feat_separate_ma_converge_kr.csv"
    rdf.drop(columns=["q"], errors="ignore").to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
