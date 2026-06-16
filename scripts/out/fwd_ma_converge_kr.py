"""KR 전체 — 수렴자리(Z) 모든 날 기준 D+1~D+7 forward 수익률 (최근 한 달).

수렴자리 Z (close 게이트 없음, 일별 나열과 동일 기준):
    MA10 > MA20  AND  |MA10-MA20|/ATR20 ≤ 0.5  AND  close > MA20  AND  주봉 MA10>MA20

신호일 = 윈도우 내 모든 Z 날 (fresh 여부 무관 — 구간 중복 카운트).
forward[k] = close[D+k] / close[D] - 1   (close-to-close, k=1..7)
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
MAX_FWD = 7
WIN_DAYS = 31  # 최근 한 달 (캘린더 일)
MIN_TRADE_VAL = float(sys.argv[1]) if len(sys.argv) > 1 else 1e9   # 거래대금 20일 중앙값 최소 (기본 10억원)


def per_symbol(sym: str, df: pd.DataFrame, win_start: pd.Timestamp) -> list[dict]:
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
    df["close_ma_atr"] = (df["close"] - df["ma20"]) / df["atr"]
    df["tval20"] = (df["close"] * df["volume"]).rolling(20).median()  # 거래대금 20일 중앙값

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
        & (df["tval20"] >= MIN_TRADE_VAL)   # 유동성 필터 (잡주/펌프 제외)
    )

    closes = df["close"].to_numpy()
    n = len(df)
    out = []
    z_idx = np.where(df["Z"].to_numpy() & (df.index >= win_start))[0]
    for i in z_idx:
        c0 = closes[i]
        rec = {
            "Symbol": sym, "date": df.index[i].date(),
            "close": c0, "close_ma_atr": float(df["close_ma_atr"].iloc[i]),
            "gap_in_atr": float(df["gap_in_atr"].iloc[i]),
        }
        for k in range(1, MAX_FWD + 1):
            rec[f"fwd{k}"] = (closes[i + k] / c0 - 1) * 100 if i + k < n else np.nan
        out.append(rec)
    return out


def main():
    asset = "kr"
    symbols = discover_universe(asset)
    print(f"universe={len(symbols)}", file=sys.stderr)

    # 윈도우 시작 = 최신 거래일 - WIN_DAYS
    sample = load_normalized_daily(asset, symbols[0])
    max_date = sample.index.max()
    for s in symbols[:50]:
        try:
            d = load_normalized_daily(asset, s)
            max_date = max(max_date, d.index.max())
        except Exception:
            pass
    win_start = max_date - pd.Timedelta(days=WIN_DAYS)
    print(f"window: {win_start.date()} ~ {max_date.date()}", file=sys.stderr)

    rows = []
    t0 = time.time()
    for i, sym in enumerate(symbols, 1):
        try:
            df = load_normalized_daily(asset, sym)
        except Exception:
            continue
        if len(df) < 60:
            continue
        rows.extend(per_symbol(sym, df, win_start))
        if i % 300 == 0:
            print(f"  [{i}/{len(symbols)}] signals={len(rows)}  {time.time()-t0:.0f}s", file=sys.stderr)

    rdf = pd.DataFrame(rows)
    listing = pd.read_csv(_ROOT / "data" / "cache" / "kr" / "_listing.csv", dtype={"Symbol": str})
    rdf["Name"] = rdf["Symbol"].map(dict(zip(listing["Symbol"], listing["Name"])))

    print(f"\n[수렴자리 Z forward — KR 전체, {win_start.date()}~{max_date.date()}]")
    print(f"총 신호(Z 날): {len(rdf)}  ({rdf['Symbol'].nunique()} 종목)")

    print(f"\n=== forward 수익률 (close-to-close, %) ===")
    hdr = f"{'horizon':>8} {'n':>6} {'mean':>8} {'trim_mean':>10} {'median':>8} {'win%':>7} {'std':>7} {'p10':>7} {'p90':>8}"
    print(hdr)
    for k in range(1, MAX_FWD + 1):
        s = rdf[f"fwd{k}"].dropna()
        lo, hi = s.quantile(.01), s.quantile(.99)
        trim = s[(s >= lo) & (s <= hi)].mean()  # 1%/99% winsor 후 평균
        print(f"{'D+'+str(k):>8} {len(s):>6} {s.mean():>8.2f} {trim:>10.2f} {s.median():>8.2f} "
              f"{(s>0).mean()*100:>7.1f} {s.std():>7.2f} {s.quantile(.1):>7.2f} {s.quantile(.9):>8.2f}")

    print(f"\n=== close_ma_atr 버킷별 D+5 ===")
    rdf["cma_b"] = pd.cut(rdf["close_ma_atr"], bins=[-100, 0.5, 1.0, 1.5, 2.0, 2.5, 100],
                          labels=["≤0.5", "0.5~1.0", "1.0~1.5", "1.5~2.0", "2.0~2.5", ">2.5"])
    by = rdf.groupby("cma_b", observed=True).agg(
        n=("fwd5", "count"), mean=("fwd5", "mean"), median=("fwd5", "median"),
        win=("fwd5", lambda s: (s.dropna() > 0).mean() * 100),
    )
    print(by.to_string(float_format=lambda v: f"{v:.2f}"))

    out_csv = Path(__file__).parent / "_fwd_ma_converge_kr.csv"
    rdf.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
