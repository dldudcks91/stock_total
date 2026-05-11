"""KOSPI + NASDAQ 전 종목 일봉 OHLCV → parquet 캐시.

FinanceDataReader 사용. ThreadPoolExecutor 병렬 다운로드.

캐시 경로:
    KOSPI  → data/cache/kr/{SYMBOL}.parquet
    NASDAQ → data/cache/us/{SYMBOL}.parquet

CLI:
    python -m data.sources.stocks                     # KOSPI + NASDAQ 증분
    python -m data.sources.stocks --market KOSPI      # 한쪽만
    python -m data.sources.stocks --refresh           # 캐시 무시하고 재다운로드
    python -m data.sources.stocks --workers 30        # 동시 요청 수 조정
"""

from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Tuple

import FinanceDataReader as fdr
import pandas as pd
from tqdm import tqdm

CACHE_ROOT = Path(__file__).resolve().parents[2] / "data" / "cache"
MARKET_DIR = {"KOSPI": CACHE_ROOT / "kr", "NASDAQ": CACHE_ROOT / "us"}
DEFAULT_START = "1990-01-01"
DEFAULT_WORKERS = 20


def get_ticker_list(market: str) -> pd.DataFrame:
    """market: 'KOSPI' or 'NASDAQ'. Returns DataFrame with at least Code/Symbol + Name."""
    df = fdr.StockListing(market)
    if market == "KOSPI":
        df = df.rename(columns={"Code": "Symbol"})[["Symbol", "Name"]]
    elif market == "NASDAQ":
        df = df[["Symbol", "Name"]]
    else:
        raise ValueError(f"unsupported market: {market}")
    df = df.dropna(subset=["Symbol"]).drop_duplicates("Symbol").reset_index(drop=True)
    return df


def fetch_one(symbol: str, start: str = DEFAULT_START) -> pd.DataFrame:
    df = fdr.DataReader(symbol, start)
    if df is None or df.empty:
        return pd.DataFrame()
    df.index.name = "Date"
    return df


def cache_path(market: str, symbol: str) -> Path:
    return MARKET_DIR[market] / f"{symbol}.parquet"


def fetch_and_save(market: str, symbol: str, refresh: bool) -> Tuple[str, int, str]:
    """Returns (symbol, rows, status)."""
    path = cache_path(market, symbol)
    if path.exists() and not refresh:
        return symbol, -1, "skip"
    try:
        df = fetch_one(symbol)
        if df.empty:
            return symbol, 0, "empty"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, compression="snappy")
        return symbol, len(df), "ok"
    except Exception as e:
        return symbol, 0, f"err:{type(e).__name__}:{e}"[:200]


def run_market(market: str, workers: int, refresh: bool) -> dict:
    print(f"\n=== {market} ===")
    tickers = get_ticker_list(market)
    symbols = tickers["Symbol"].tolist()
    print(f"tickers: {len(symbols)}")

    out_dir = MARKET_DIR[market]
    out_dir.mkdir(parents=True, exist_ok=True)
    tickers.to_csv(out_dir / "_listing.csv", index=False, encoding="utf-8-sig")

    results = {"ok": 0, "skip": 0, "empty": 0, "err": 0}
    errors = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fetch_and_save, market, s, refresh): s for s in symbols}
        for fut in tqdm(as_completed(futures), total=len(futures), desc=market, ncols=80):
            sym, rows, status = fut.result()
            if status == "ok":
                results["ok"] += 1
            elif status == "skip":
                results["skip"] += 1
            elif status == "empty":
                results["empty"] += 1
            else:
                results["err"] += 1
                errors.append((sym, status))

    dt = time.time() - t0
    print(f"{market} done in {dt/60:.1f}min: {results}")
    if errors:
        err_path = out_dir / "_errors.csv"
        pd.DataFrame(errors, columns=["Symbol", "Error"]).to_csv(err_path, index=False)
        print(f"  errors logged to {err_path}")
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=["KOSPI", "NASDAQ", "ALL"], default="ALL")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--refresh", action="store_true", help="ignore cache, redownload")
    args = p.parse_args()

    markets = ["KOSPI", "NASDAQ"] if args.market == "ALL" else [args.market]
    for m in markets:
        run_market(m, workers=args.workers, refresh=args.refresh)

    print(f"\nAll done. Cache root: {CACHE_ROOT}")


if __name__ == "__main__":
    main()
