"""Naver Finance live-ticker snapshot for KOSPI.

Uses the bulk page endpoint
``https://m.stock.naver.com/api/stocks/marketValue/KOSPI`` (100 stocks per
page, fan-out across pages with bounded concurrency). Writes
``data/cache/kr/_live_snapshot.parquet`` via the shared snapshot helpers.

CLI usage::

    python -m data.sources.naver_kr [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests

from data.sources._snapshot import (
    load_snapshot as _generic_load_snapshot,
    merge_snapshot as _generic_merge_snapshot,
    write_atomic,
)

_ROOT = Path(__file__).resolve().parents[2]
KR_CACHE_DIR = _ROOT / "data" / "cache" / "kr"
SNAPSHOT_PATH = KR_CACHE_DIR / "_live_snapshot.parquet"

NAVER_LIST_URL = "https://m.stock.naver.com/api/stocks/marketValue/{exchange}"
NAVER_PAGE_SIZE = 100
FETCH_CONCURRENCY = 4
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _fetch_page(exchange: str, page: int, page_size: int, timeout: float = 8.0) -> dict[str, Any]:
    resp = requests.get(
        NAVER_LIST_URL.format(exchange=exchange),
        params={"page": page, "pageSize": page_size},
        headers={"User-Agent": USER_AGENT, "Referer": "https://m.stock.naver.com/"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


async def _fetch_page_async(session, sem, exchange: str, page: int, page_size: int) -> dict[str, Any]:
    import aiohttp
    params = {"page": page, "pageSize": page_size}
    async with sem:
        try:
            async with session.get(
                NAVER_LIST_URL.format(exchange=exchange), params=params,
                headers={"User-Agent": USER_AGENT, "Referer": "https://m.stock.naver.com/"},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                return await r.json()
        except Exception:
            return {"stocks": []}


async def _fetch_pages_async(exchange: str, total_pages: int, page_size: int) -> list[dict[str, Any]]:
    import aiohttp
    sem = asyncio.Semaphore(FETCH_CONCURRENCY)
    async with aiohttp.ClientSession() as session:
        tasks = [
            _fetch_page_async(session, sem, exchange, p, page_size)
            for p in range(1, total_pages + 1)
        ]
        return await asyncio.gather(*tasks)


def fetch_market(exchange: str, top_n: int = 0) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch ``exchange`` (e.g. ``KOSPI``) ticker list.

    ``top_n=0`` fetches all listed stocks (uses ``totalCount`` from page 1).
    """
    page_size = NAVER_PAGE_SIZE
    first = _fetch_page(exchange, 1, page_size)
    meta = {
        "marketStatus": first.get("marketStatus"),
        "totalCount": first.get("totalCount"),
        "localOpenTimeDesc": first.get("localOpenTimeDesc"),
    }
    total = first.get("totalCount") or 0
    target = top_n if top_n > 0 else total
    total_pages = max(1, -(-target // page_size))
    stocks = list(first.get("stocks", []))
    if total_pages > 1:
        rest = asyncio.run(_fetch_pages_async(exchange, total_pages, page_size))
        for payload in rest[1:]:
            stocks.extend(payload.get("stocks", []))
    if top_n > 0:
        stocks = stocks[:top_n]
    return _normalize(stocks), meta


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _normalize(stocks: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for s in stocks:
        rows.append({
            "itemCode": s.get("itemCode"),
            "stockName": s.get("stockName"),
            "closePrice": _to_float(s.get("closePriceRaw")),
            "fluctuationsRatio": _to_pct(s.get("fluctuationsRatio")),
            "accumulatedTradingVolume": _to_float(s.get("accumulatedTradingVolumeRaw")),
            "accumulatedTradingValue": _to_float(s.get("accumulatedTradingValueRaw")),
            "marketValue": _to_float(s.get("marketValueRaw")),
            "marketStatus": s.get("marketStatus"),
            "localTradedAt": s.get("localTradedAt"),
        })
        direction = (s.get("compareToPreviousPrice") or {}).get("code")
        if direction in {"4", "5"} and rows[-1]["fluctuationsRatio"] is not None:
            rows[-1]["fluctuationsRatio"] = -abs(rows[-1]["fluctuationsRatio"])
    return pd.DataFrame(rows)


def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None or x == "" or x == "N/A":
            return None
        return float(str(x).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _to_pct(x: Any) -> Optional[float]:
    v = _to_float(x)
    return None if v is None else v / 100.0


# ---------------------------------------------------------------------------
# Snapshot persistence — thin wrappers
# ---------------------------------------------------------------------------

def load_snapshot(path: Path = SNAPSHOT_PATH) -> Optional[pd.DataFrame]:
    return _generic_load_snapshot(path)


def merge_snapshot(new_df: pd.DataFrame, path: Path = SNAPSHOT_PATH) -> pd.DataFrame:
    return _generic_merge_snapshot(new_df, path, symbol_col="itemCode")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="Fetch Naver KOSPI live snapshot")
    ap.add_argument("--limit", type=int, default=0,
                    help="0 = all (fetches totalCount from Naver)")
    args = ap.parse_args()

    started = pd.Timestamp.now(tz="Asia/Seoul")
    print(f"[info] fetching KOSPI tickers from Naver ({started.strftime('%H:%M:%S')})")

    try:
        df, meta = fetch_market("KOSPI", top_n=args.limit)
    except Exception as e:
        print(f"[error] Naver KOSPI API failure: {e}")
        return 1
    elapsed = (pd.Timestamp.now(tz="Asia/Seoul") - started).total_seconds()
    print(f"[info] received {len(df)}/{meta.get('totalCount')} in {elapsed:.1f}s")

    if df.empty:
        print("[error] empty response")
        return 1

    merged = merge_snapshot(df)
    write_atomic(merged, SNAPSHOT_PATH)
    print(f"[ok] wrote snapshot ({len(merged)} rows) -> {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
