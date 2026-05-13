"""ma_slope_turn_up 진입 시점의 N주 forward return 분포 분석.

각 시그널 시점(t)에 대해 +N주 후 종가 수익률을 구하고,
자산별로 horizon × 통계(평균/중앙값/승률/분위수)를 집계.

참고: forward window가 부족한 (끝부분에 너무 가까운) 시그널은 해당 horizon에서 NaN 처리.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.strategies import ma_slope_turn_up  # noqa: E402
from scripts.count_slope_turn_signals import (  # noqa: E402
    load_crypto_weekly,
    load_stock_weekly,
    crypto_symbol_from_file,
    CRYPTO_DIR,
    KR_DIR,
    US_DIR,
    SINCE,
)

OUT_DIR = ROOT / "scripts" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HORIZONS = [1, 4, 8, 13, 26, 52]  # weeks


def collect_returns(asset: str, files: list[Path], loader) -> pd.DataFrame:
    rows = []
    n = len(files)
    print(f"[{asset}] {n} symbols", flush=True)
    for i, p in enumerate(files, 1):
        symbol = crypto_symbol_from_file(p) if asset == "crypto" else p.stem
        try:
            df_w = loader(p)
            if df_w is None or df_w.empty or len(df_w) < 120:
                continue
            sig = ma_slope_turn_up.signal(df_w.reset_index(drop=True), {})
            sig.index = df_w.index
            close = df_w["close"].to_numpy()
            entries = (sig.diff() == 1)
            entries = entries & (entries.index >= SINCE)
            entry_pos = np.where(entries.to_numpy())[0]
            for pos in entry_pos:
                entry_close = close[pos]
                entry_dt = df_w.index[pos]
                row = {
                    "asset": asset,
                    "symbol": symbol,
                    "entry_dt": entry_dt.date().isoformat(),
                    "entry_close": float(entry_close),
                }
                for h in HORIZONS:
                    fp = pos + h
                    if fp < len(close):
                        row[f"ret_{h}w"] = float(close[fp] / entry_close - 1.0)
                    else:
                        row[f"ret_{h}w"] = np.nan
                rows.append(row)
        except Exception as e:
            print(f"  ! {symbol}: {type(e).__name__}: {e}", flush=True)
        if i % 100 == 0 or i == n:
            print(f"  [{asset}] {i}/{n}", flush=True)
    return pd.DataFrame(rows)


def stats_by_horizon(df: pd.DataFrame, asset_label: str) -> pd.DataFrame:
    out = []
    for h in HORIZONS:
        col = f"ret_{h}w"
        s = df[col].dropna()
        if len(s) == 0:
            continue
        out.append({
            "asset": asset_label,
            "horizon": f"{h}w",
            "n": len(s),
            "mean_%": s.mean() * 100,
            "median_%": s.median() * 100,
            "win_rate_%": (s > 0).mean() * 100,
            "p25_%": s.quantile(0.25) * 100,
            "p75_%": s.quantile(0.75) * 100,
            "min_%": s.min() * 100,
            "max_%": s.max() * 100,
            "std_%": s.std() * 100,
        })
    return pd.DataFrame(out)


def main():
    crypto_files = sorted(CRYPTO_DIR.glob("bitget_*_1h.parquet"))
    df_c = collect_returns("crypto", crypto_files, load_crypto_weekly)

    kr_files = [p for p in sorted(KR_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    df_k = collect_returns("kr", kr_files, load_stock_weekly)

    if US_DIR.exists():
        us_files = [p for p in sorted(US_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
        df_u = collect_returns("us", us_files, load_stock_weekly) if us_files else pd.DataFrame()
    else:
        df_u = pd.DataFrame()

    all_df = pd.concat([d for d in [df_c, df_k, df_u] if not d.empty], ignore_index=True)
    raw_csv = OUT_DIR / "forward_returns_raw.csv"
    all_df.to_csv(raw_csv, index=False, encoding="utf-8-sig")
    print(f"\nsaved raw: {raw_csv}  (rows={len(all_df)})")

    # asset-level stats
    summary = pd.concat(
        [stats_by_horizon(d, name) for name, d in all_df.groupby("asset") if not d.empty],
        ignore_index=True,
    )
    summary_csv = OUT_DIR / "forward_returns_summary.csv"
    summary.to_csv(summary_csv, index=False, encoding="utf-8-sig", float_format="%.2f")
    print(f"saved summary: {summary_csv}")

    print("\n=== Forward returns by asset × horizon ===")
    fmt_cols = ["asset", "horizon", "n", "mean_%", "median_%", "win_rate_%",
                "p25_%", "p75_%", "min_%", "max_%", "std_%"]
    with pd.option_context("display.float_format", "{:.2f}".format,
                            "display.width", 160,
                            "display.max_columns", None):
        print(summary[fmt_cols].to_string(index=False))

    # 추가: 모든 자산 합산 통계 (전체)
    print("\n=== ALL assets combined ===")
    overall = stats_by_horizon(all_df, "ALL")
    with pd.option_context("display.float_format", "{:.2f}".format,
                            "display.width", 160, "display.max_columns", None):
        print(overall[fmt_cols].to_string(index=False))

    # horizon 별 상위/하위 사례 — 13주 기준
    h_pick = "ret_13w"
    if h_pick in all_df.columns:
        print(f"\n=== Best/Worst 10 ({h_pick}) — entries with full {h_pick} data ===")
        s = all_df.dropna(subset=[h_pick]).sort_values(h_pick, ascending=False)
        print("\n[Best 10]")
        print(s.head(10)[["asset", "symbol", "entry_dt", h_pick]].to_string(index=False))
        print("\n[Worst 10]")
        print(s.tail(10)[["asset", "symbol", "entry_dt", h_pick]].to_string(index=False))


if __name__ == "__main__":
    main()
