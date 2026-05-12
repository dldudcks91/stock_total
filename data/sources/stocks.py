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

from data import fetch_log

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


FETCH_TIMEOUT_SEC = 20
MAX_RETRIES = 2
RETRY_BACKOFF_SEC = 1.5


def fetch_one(symbol: str, start: str = DEFAULT_START) -> pd.DataFrame:
    df = fdr.DataReader(symbol, start)
    if df is None or df.empty:
        return pd.DataFrame()
    df.index.name = "Date"
    return df


def cache_path(market: str, symbol: str) -> Path:
    return MARKET_DIR[market] / f"{symbol}.parquet"


def _fetch_with_timeout_start(symbol: str, start: str) -> pd.DataFrame:
    """fetch_one(symbol, start) with hard timeout — same pattern as _fetch_with_timeout."""
    from concurrent.futures import ThreadPoolExecutor as _TPE, TimeoutError as _TO
    ex = _TPE(max_workers=1)
    try:
        fut = ex.submit(fetch_one, symbol, start)
        try:
            return fut.result(timeout=FETCH_TIMEOUT_SEC)
        except _TO:
            raise TimeoutError(f"fetch_one({symbol}, start={start}) > {FETCH_TIMEOUT_SEC}s")
    finally:
        ex.shutdown(wait=False)


def _fetch_with_timeout(symbol: str) -> pd.DataFrame:
    """Run fetch_one in a sub-thread so we can enforce a per-call timeout.
    Necessary because FDR's underlying requests can hang indefinitely under rate limit.

    Uses shutdown(wait=False) so the worker is not blocked waiting for the
    hung sub-thread — `with` would call shutdown(wait=True), deadlocking the
    main pool when many FDR calls hang at once (orphan threads will leak, but
    the parent worker is freed immediately to process the next ticker)."""
    from concurrent.futures import ThreadPoolExecutor as _TPE, TimeoutError as _TO
    ex = _TPE(max_workers=1)
    try:
        fut = ex.submit(fetch_one, symbol)
        try:
            return fut.result(timeout=FETCH_TIMEOUT_SEC)
        except _TO:
            raise TimeoutError(f"fetch_one({symbol}) > {FETCH_TIMEOUT_SEC}s")
    finally:
        ex.shutdown(wait=False)


def fetch_and_save(market: str, symbol: str, refresh: bool) -> Tuple[str, int, str]:
    """Returns (symbol, rows, status).

    - 캐시 없음 또는 --refresh: 전체 히스토리(1990-01-01~) 다운로드.
    - 캐시 있고 --refresh 아님: 캐시 마지막 날짜 + 1일 부터만 받아 append → 진짜 증분.
      이미 최신이면 status='skip', 그 외엔 'append'.
    """
    path = cache_path(market, symbol)
    existing: pd.DataFrame = pd.DataFrame()
    start = DEFAULT_START
    if path.exists() and not refresh:
        existing = pd.read_parquet(path)
        if not existing.empty:
            last_date = pd.to_datetime(existing.index.max()).normalize()
            today = pd.Timestamp.utcnow().tz_localize(None).normalize()
            if last_date >= today:
                return symbol, len(existing), "skip"
            start = (last_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            df = _fetch_with_timeout_start(symbol, start)
            if df.empty and existing.empty:
                return symbol, 0, "empty"
            if existing.empty:
                merged = df
                status = "ok"
            elif df.empty:
                return symbol, len(existing), "skip"
            else:
                merged = pd.concat([existing, df])
                merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                status = "append"
            path.parent.mkdir(parents=True, exist_ok=True)
            merged.to_parquet(path, compression="snappy")
            return symbol, len(merged), status
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SEC * (attempt + 1))
    return symbol, 0, f"err:{type(last_err).__name__}:{last_err}"[:200]


def run_market(market: str, workers: int, refresh: bool) -> dict:
    print(f"\n=== {market} ===")
    tickers = get_ticker_list(market)
    symbols = tickers["Symbol"].tolist()
    print(f"tickers: {len(symbols)}")

    out_dir = MARKET_DIR[market]
    out_dir.mkdir(parents=True, exist_ok=True)
    tickers.to_csv(out_dir / "_listing.csv", index=False, encoding="utf-8-sig")

    results = {"ok": 0, "append": 0, "skip": 0, "empty": 0, "err": 0}
    errors = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fetch_and_save, market, s, refresh): s for s in symbols}
        for fut in tqdm(as_completed(futures), total=len(futures), desc=market, ncols=80):
            sym, rows, status = fut.result()
            if status in ("ok", "append", "skip", "empty"):
                results[status] += 1
            else:
                results["err"] += 1
                errors.append((sym, status))

    dt = time.time() - t0
    print(f"{market} done in {dt/60:.1f}min: {results}")
    if errors:
        err_path = out_dir / "_errors.csv"
        pd.DataFrame(errors, columns=["Symbol", "Error"]).to_csv(err_path, index=False)
        print(f"  errors logged to {err_path}")

    key = {"KOSPI": "kr_1d", "NASDAQ": "us_1d"}[market]
    fetch_log.mark(key, n_symbols=len(symbols))
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
