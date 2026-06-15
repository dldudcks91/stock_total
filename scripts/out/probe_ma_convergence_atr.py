"""MA 수렴 패턴 — ATR20 정규화 버전.

  Z' (수렴자리): MA10 > MA20 + close > MA20 + |gap_abs| / ATR20 ≤ 0.5
  T' (Z' + 장대양봉): + intraday ≥ 5% + close > open

전 KR 종목 × 2025-09~2026-06 스캔. 후행 수익률 5d/20d/60d.
"""
from __future__ import annotations

import sys
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
    df["gap_abs"] = df["ma10"] - df["ma20"]
    df["tr"] = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs()
    ], axis=1).max(axis=1)
    df["atr"] = df["tr"].rolling(ATR_WIN).mean()
    df["gap_in_atr"] = df["gap_abs"] / df["atr"]
    df["intra"] = (df["close"] - df["open"]) / df["open"]

    pat_z = (df["ma10"] > df["ma20"]) & (df["gap_in_atr"].abs() <= GAP_IN_ATR_MAX) & (df["close"] > df["ma20"])
    pat_t = pat_z & (df["intra"] >= INTRA_MIN) & (df["close"] > df["open"])

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
            "intra_pct": row["intra"] * 100,
            "gap_in_atr": row["gap_in_atr"],
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
    df["Name"] = df["Symbol"].map(dict(zip(listing["Symbol"], listing["Name"])))

    pat_z = df
    pat_t = df[df["pattern_T"]]

    print(f"\n[ATR{ATR_WIN} 정규화, gap_in_atr ≤ {GAP_IN_ATR_MAX}, intra ≥ {int(INTRA_MIN*100)}%]")
    print(f"  Z' (수렴자리)          : {len(pat_z)} 건 ({pat_z['Symbol'].nunique()} 종목)")
    print(f"  T' (Z' + 장대양봉)     : {len(pat_t)} 건 ({pat_t['Symbol'].nunique()} 종목)")

    def stats(s, label):
        s = s.dropna()
        if len(s) == 0:
            print(f"  {label:15s} n=0")
            return
        print(f"  {label:15s} n={len(s):5d}  mean={s.mean():+.2f}%  median={s.median():+.2f}%  win={(s>0).mean()*100:.0f}%  max={s.max():+.1f}%  min={s.min():+.1f}%")

    print(f"\n=== Z' (수렴자리) 후행 수익률 ===")
    for k in ["fwd_5d","fwd_20d","fwd_60d"]:
        stats(pat_z[k], k)

    print(f"\n=== T' (Z' + 장대양봉) 후행 수익률 ===")
    for k in ["fwd_5d","fwd_20d","fwd_60d"]:
        stats(pat_t[k], k)

    # 한미반도체 검증
    print(f"\n=== 한미반도체(042700) 매칭 ===")
    hm = df[df["Symbol"] == "042700"]
    if len(hm):
        print(hm[["date","close","intra_pct","gap_in_atr","pattern_T","fwd_5d","fwd_20d","fwd_60d"]].to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    else:
        print("  매칭 없음")

    print(f"\n=== T' fwd_60d 상위 15 ===")
    tt = pat_t.dropna(subset=["fwd_60d"]).sort_values("fwd_60d", ascending=False)
    print(tt.head(15)[["date","Symbol","Name","close","intra_pct","gap_in_atr","fwd_5d","fwd_20d","fwd_60d"]].to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    print(f"\n=== T' fwd_60d 하위 10 ===")
    print(tt.tail(10).iloc[::-1][["date","Symbol","Name","close","intra_pct","gap_in_atr","fwd_5d","fwd_20d","fwd_60d"]].to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    out_csv = Path(__file__).parent / "_probe_ma_convergence_atr.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
