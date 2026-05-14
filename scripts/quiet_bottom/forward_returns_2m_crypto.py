"""크립토 전종목 — ma_slope_turn_up 진입 시점 후 1~8주 주간 수익률.

출력:
  scripts/out/forward_2m_crypto.csv  — 진입 1건/행, +1w~+8w 수익률 (%)
  콘솔 — 자산 평균/승률, 종목별 진입 횟수 Top, 단일 진입 best/worst
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import ma_slope_turn_up  # noqa: E402
from scripts.quiet_bottom.count_slope_turn_signals import (  # noqa: E402
    load_crypto_weekly, crypto_symbol_from_file, CRYPTO_DIR, SINCE,
)

OUT_DIR = ROOT / "scripts" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HORIZONS = list(range(1, 9))  # +1 ~ +8 weeks
RET_COLS = [f"+{h}w_%" for h in HORIZONS]


def main():
    files = sorted(CRYPTO_DIR.glob("bitget_*_1h.parquet"))
    rows = []
    n = len(files)
    print(f"crypto: {n} symbols", flush=True)
    for i, p in enumerate(files, 1):
        symbol = crypto_symbol_from_file(p)
        try:
            df_w = load_crypto_weekly(p)
            if df_w is None or df_w.empty or len(df_w) < 120:
                continue
            sig = ma_slope_turn_up.signal(df_w.reset_index(drop=True), {})
            sig.index = df_w.index
            entries = (sig.diff() == 1)
            entries = entries & (entries.index >= SINCE)
            close = df_w["close"].to_numpy()
            for pos in np.where(entries.to_numpy())[0]:
                entry_close = close[pos]
                row = {
                    "symbol": symbol,
                    "entry_dt": df_w.index[pos].date().isoformat(),
                    "entry_$": round(float(entry_close), 6),
                }
                for h in HORIZONS:
                    fp = pos + h
                    row[f"+{h}w_%"] = (
                        round(float(close[fp] / entry_close - 1.0) * 100, 1)
                        if fp < len(close) else np.nan
                    )
                rows.append(row)
        except Exception as e:
            print(f"  ! {symbol}: {type(e).__name__}: {e}", flush=True)
        if i % 100 == 0 or i == n:
            print(f"  {i}/{n}", flush=True)

    df = pd.DataFrame(rows)
    out_csv = OUT_DIR / "forward_2m_crypto.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nsaved: {out_csv}  (rows={len(df)})")

    # 자산 전체 통계 (horizon별)
    print("\n=== Crypto: 1~8주 horizon 통계 (시그널 단위) ===")
    stats = []
    for h in HORIZONS:
        s = df[f"+{h}w_%"].dropna()
        stats.append({
            "h": f"+{h}w",
            "n": len(s),
            "mean_%": s.mean(),
            "median_%": s.median(),
            "win_%": (s > 0).mean() * 100,
            "p25_%": s.quantile(0.25),
            "p75_%": s.quantile(0.75),
            "max_%": s.max(),
            "min_%": s.min(),
        })
    sdf = pd.DataFrame(stats)
    with pd.option_context("display.float_format", "{:.1f}".format,
                            "display.width", 160, "display.max_columns", None):
        print(sdf.to_string(index=False))

    # 8주 누적 최대 수익률(in-window peak) 통계 — "단기 폭등권" 가설 검증
    print("\n=== 8주 윈도우 내 최고점 수익률 분포 ===")
    peak = df[RET_COLS].max(axis=1)
    print(f"  n={peak.notna().sum()}, mean={peak.mean():.1f}%, median={peak.median():.1f}%, "
          f"hit>+20%: {(peak>20).mean()*100:.1f}%, hit>+50%: {(peak>50).mean()*100:.1f}%, "
          f"hit>+100%: {(peak>100).mean()*100:.1f}%")

    # 종목별 평균 (진입 횟수 ≥ 2)
    print("\n=== 종목별 평균 (진입 ≥ 2회만, 진입수 내림차순 상위 25) ===")
    agg = (
        df.groupby("symbol")
        .agg(n=("entry_dt", "count"),
             m1=("+1w_%", "mean"), m4=("+4w_%", "mean"), m8=("+8w_%", "mean"),
             peak8=("+8w_%", "mean"))  # placeholder
    )
    agg["peak8"] = df.groupby("symbol").apply(lambda d: d[RET_COLS].max(axis=1).mean())
    agg = agg[agg["n"] >= 2].sort_values("n", ascending=False).head(25)
    with pd.option_context("display.float_format", "{:.1f}".format,
                            "display.width", 160, "display.max_columns", None):
        print(agg.to_string())

    # 단일 진입 best 10 (+8w 기준 peak)
    print("\n=== 단일 진입 — 8주 윈도우 최고점 Top 10 ===")
    df["peak8_%"] = df[RET_COLS].max(axis=1)
    top = df.sort_values("peak8_%", ascending=False).head(10)
    print(top[["symbol", "entry_dt", "entry_$", "peak8_%"] + RET_COLS]
          .to_string(index=False, float_format=lambda x: f"{x:.1f}"))

    # 단일 진입 worst 10 (+8w 기준 최저점)
    print("\n=== 단일 진입 — 8주 윈도우 최저점 Top 10 ===")
    df["trough8_%"] = df[RET_COLS].min(axis=1)
    bad = df.sort_values("trough8_%", ascending=True).head(10)
    print(bad[["symbol", "entry_dt", "entry_$", "trough8_%"] + RET_COLS]
          .to_string(index=False, float_format=lambda x: f"{x:.1f}"))


if __name__ == "__main__":
    main()
