"""NASDAQ 시총 상위 200 일봉 fetch → data/cache/us/{TICKER}.parquet

FDR.StockListing('NASDAQ')은 시총순으로 정렬되어 head(200)이 상위 200.
2020-01-01 부터 현재까지 일봉 다운로드.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import FinanceDataReader as fdr

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
US_DIR = ROOT / "data" / "cache" / "us"
US_DIR.mkdir(parents=True, exist_ok=True)

TOP_N = 200
START = "2020-01-01"


def main():
    listing = fdr.StockListing("NASDAQ")
    tickers = listing["Symbol"].head(TOP_N).tolist()
    print(f"fetching NASDAQ top {len(tickers)} since {START}", flush=True)

    ok = 0
    skip = 0
    fail = []
    t0 = time.time()
    for i, t in enumerate(tickers, 1):
        out = US_DIR / f"{t}.parquet"
        if out.exists() and out.stat().st_size > 0:
            skip += 1
            continue
        try:
            df = fdr.DataReader(t, START)
            if df is None or df.empty:
                fail.append(t)
                continue
            df.to_parquet(out)
            ok += 1
        except Exception as e:
            print(f"  ! {t}: {type(e).__name__}: {e}", flush=True)
            fail.append(t)
        if i % 20 == 0:
            elapsed = time.time() - t0
            print(f"  {i}/{len(tickers)}  ok={ok} skip={skip} fail={len(fail)}  "
                  f"({elapsed:.0f}s)", flush=True)

    elapsed = time.time() - t0
    print(f"\ndone in {elapsed:.0f}s — ok={ok}, skipped(exists)={skip}, fail={len(fail)}")
    if fail:
        print(f"failed tickers: {fail}")


if __name__ == "__main__":
    main()
