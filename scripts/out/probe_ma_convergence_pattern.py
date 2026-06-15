"""MA10·MA20 정배열 + 수렴 패턴 스크리너 (일봉 단위).

KR 전 종목 × 최근 6개월. 두 패턴:
  Pattern Z (수렴자리): MA10 > MA20  AND  |MA10-MA20|/MA20 ≤ 2%
  Pattern T (수렴+출발): Z  AND  intraday_ret ≥ 5%  AND close > open

각 매치에 대해 5d / 20d / 60d 후행 수익률 기록.
한미반도체 1/2 자리가 잡히는지 검증.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.mtf_loader import load_normalized_daily
from scripts._common.recommend_runner import discover_universe

GAP_MAX = 0.02       # MA10·MA20 갭 ≤ 2%
INTRA_MIN = 0.05     # 장대양봉 ≥ 5%
SCAN_START = pd.Timestamp("2025-09-01")
SCAN_END = pd.Timestamp("2026-06-15")


def scan_symbol(asset: str, sym: str):
    try:
        df = load_normalized_daily(asset, sym)
    except Exception:
        return []
    if len(df) < 30:
        return []
    df = df.copy()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["gap_pct"] = (df["ma10"] - df["ma20"]) / df["ma20"]
    df["intraday_ret"] = (df["close"] - df["open"]) / df["open"]

    # 패턴 Z = 정배열 + 수렴
    pat_z = (df["ma10"] > df["ma20"]) & (df["gap_pct"].abs() <= GAP_MAX) & (df["close"] > df["ma20"])
    # 패턴 T = Z + 장대양봉
    pat_t = pat_z & (df["intraday_ret"] >= INTRA_MIN) & (df["close"] > df["open"])

    matches = df[pat_z & (df.index >= SCAN_START) & (df.index <= SCAN_END)].copy()
    out = []
    for d, row in matches.iterrows():
        entry_close = row["close"]
        idx = df.index.get_loc(d)
        def fwd(k):
            j = idx + k
            if j >= len(df):
                return float("nan")
            return (df.iloc[j]["close"] / entry_close - 1) * 100
        out.append({
            "Symbol": sym,
            "date": d.date(),
            "close": entry_close,
            "intraday_ret_pct": row["intraday_ret"] * 100,
            "gap_pct": row["gap_pct"] * 100,
            "pattern_T": bool(pat_t.loc[d]),
            "fwd_5d": fwd(5),
            "fwd_20d": fwd(20),
            "fwd_60d": fwd(60),
        })
    return out


def main():
    asset = "kr"
    symbols = discover_universe(asset)
    print(f"universe={len(symbols)}", file=sys.stderr)

    rows = []
    for i, sym in enumerate(symbols, 1):
        rows.extend(scan_symbol(asset, sym))
        if i % 200 == 0:
            print(f"  [{i}/{len(symbols)}] rows={len(rows)}", file=sys.stderr)

    df = pd.DataFrame(rows)
    listing = pd.read_csv(_ROOT / "data" / "cache" / "kr" / "_listing.csv", dtype={"Symbol": str})
    name_map = dict(zip(listing["Symbol"], listing["Name"]))
    df["Name"] = df["Symbol"].map(name_map)

    pat_z = df
    pat_t = df[df["pattern_T"]]

    print(f"\n=== 패턴 발생 빈도 (2025-09 ~ 2026-06) ===")
    print(f"  Z (정배열 + 수렴, gap≤{int(GAP_MAX*100)}%)            : {len(pat_z)} 건  ({pat_z['Symbol'].nunique()} 종목)")
    print(f"  T (Z + 장대양봉 intraday≥{int(INTRA_MIN*100)}%)        : {len(pat_t)} 건  ({pat_t['Symbol'].nunique()} 종목)")

    def stats(s, label):
        s = s.dropna()
        if len(s) == 0:
            print(f"  {label:15s} n=0")
            return
        print(f"  {label:15s} n={len(s):5d}  mean={s.mean():+.2f}%  median={s.median():+.2f}%  win={(s>0).mean()*100:.0f}%  max={s.max():+.1f}%  min={s.min():+.1f}%")

    print(f"\n=== Z 패턴 후행 수익률 ===")
    stats(pat_z["fwd_5d"], "fwd_5d")
    stats(pat_z["fwd_20d"], "fwd_20d")
    stats(pat_z["fwd_60d"], "fwd_60d")

    print(f"\n=== T 패턴 후행 수익률 ===")
    stats(pat_t["fwd_5d"], "fwd_5d")
    stats(pat_t["fwd_20d"], "fwd_20d")
    stats(pat_t["fwd_60d"], "fwd_60d")

    # 한미반도체 검증
    print(f"\n=== 한미반도체(042700) 매칭 ===")
    hm = df[df["Symbol"] == "042700"]
    if len(hm):
        print(hm[["date","close","intraday_ret_pct","gap_pct","pattern_T","fwd_5d","fwd_20d","fwd_60d"]].to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    else:
        print("  매칭 없음 — gap 임계 풀어야 잡힐 수도")

    # T 패턴 후행 60d 상위 종목 (룰 검증)
    print(f"\n=== T 패턴 — fwd_60d 상위 15 ===")
    tt = pat_t.dropna(subset=["fwd_60d"]).sort_values("fwd_60d", ascending=False)
    print(tt.head(15)[["date","Symbol","Name","close","intraday_ret_pct","gap_pct","fwd_5d","fwd_20d","fwd_60d"]].to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    print(f"\n=== T 패턴 — fwd_60d 하위 15 ===")
    print(tt.tail(15).iloc[::-1][["date","Symbol","Name","close","intraday_ret_pct","gap_pct","fwd_5d","fwd_20d","fwd_60d"]].to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    out_csv = Path(__file__).parent / "_probe_ma_convergence_pattern.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
