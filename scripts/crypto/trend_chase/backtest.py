"""crypto trend_chase 백테스트 — 멀티 TF (1d + 1h) 자체 harness.

scripts._common.backtest_runner 는 single-TF cache 만 지원하므로 별도 loop.
종목당 1d + 1h 캐시 둘 다 읽어 score_chase_crypto 호출 → fwd_ret 측정.

사용:
    .venv/Scripts/python.exe -m scripts.crypto.trend_chase.backtest
    .venv/Scripts/python.exe -m scripts.crypto.trend_chase.backtest --start 2025-11-26 --end 2026-05-26
"""
from __future__ import annotations

import argparse
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

from scripts._common.backtest_runner import (
    analyze_threshold_multi,
    analyze_baseline_multi,
    analyze_quantile_multi,
)
from scripts.crypto.trend_chase.scoring import score_chase_crypto, to_kr_schema, CH_CRYPTO_MAX

CACHE_1D = ROOT / "data" / "cache" / "crypto" / "1d"
CACHE_1H = ROOT / "data" / "cache" / "crypto" / "1h"
OUT_DIR = ROOT / "scripts" / "out"
WORKERS = 8


def _process_symbol(sym: str, start: pd.Timestamp, end: pd.Timestamp, holds: tuple) -> pd.DataFrame:
    """한 종목 점수 + fwd_ret 계산. 1h 가 없으면 1d core 만."""
    try:
        df_1d_raw = pd.read_parquet(CACHE_1D / f"{sym}.parquet")
        if len(df_1d_raw) < 120:
            return pd.DataFrame()
        df_1h_raw = None
        p1h = CACHE_1H / f"{sym}.parquet"
        if p1h.exists():
            df_1h_raw = pd.read_parquet(p1h)

        df_1d = to_kr_schema(df_1d_raw)
        df_1h = to_kr_schema(df_1h_raw) if df_1h_raw is not None else None

        sc = score_chase_crypto(df_1d, df_1h)

        # fwd_ret
        fwd = {}
        for h in holds:
            fwd[f"fwd_ret_{h}"] = df_1d["Close"].shift(-h) / df_1d["Close"] - 1

        mask = (df_1d.index >= start) & (df_1d.index <= end)
        out = pd.DataFrame({
            "ch_score": sc[mask],
            "Close": df_1d["Close"][mask],
            "ret_30d": df_1d["Close"].pct_change(30)[mask],
            "ret_90d": df_1d["Close"].pct_change(90)[mask],
            **{k: v[mask] for k, v in fwd.items()},
        })
        if out.empty:
            return pd.DataFrame()
        out = out.reset_index().rename(columns={"index": "date", "dt": "date"})
        out["symbol"] = sym
        return out
    except Exception as e:
        print(f"  [warn] {sym}: {e}")
        return pd.DataFrame()


def run_backtest(start: pd.Timestamp, end: pd.Timestamp, holds=(5, 10, 20, 30, 60)) -> pd.DataFrame:
    syms = sorted(p.stem for p in CACHE_1D.glob("*.parquet"))
    print(f"종목 수: {len(syms)} / 기간 {start.date()} ~ {end.date()} / hold: {list(holds)}\n")

    rows = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(_process_symbol, sym, start, end, holds): sym for sym in syms}
        done = 0
        for fut in as_completed(futs):
            done += 1
            if done % 50 == 0:
                print(f"  [{done}/{len(syms)}] processing...")
            df = fut.result()
            if not df.empty:
                rows.append(df)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    print(f"\n총 (종목 × 일자) 샘플: {len(out):,}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-11-26")
    ap.add_argument("--end", default="2026-05-26")
    args = ap.parse_args()

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    HOLDS = (5, 10, 20, 30, 60)

    print(f"=== Crypto trend_chase 백테스트 (multi-TF: 1d primary + 1h alignment) ===\n")
    bt = run_backtest(start, end, HOLDS)
    if bt.empty:
        print("샘플 없음 — 종료")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"crypto_chase_bt_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.parquet"
    bt.to_parquet(out_path, index=False)
    print(f"저장: {out_path}\n")

    analyze_baseline_multi(bt, HOLDS)

    print("\n" + "=" * 60)
    print(" CH_CRYPTO threshold sweep")
    print("=" * 60)
    for th in (0, 20, 40, 60, 80, 100):
        analyze_threshold_multi(bt, "ch_score", th, "CH_CRYPTO", HOLDS)

    print("\n\n" + "=" * 60)
    print(" CH_CRYPTO 점수 분위별 (10분위) — 차별력 검증")
    print("=" * 60)
    analyze_quantile_multi(bt, "ch_score", "CH_CRYPTO", hold_periods=(30, 60))


if __name__ == "__main__":
    main()
