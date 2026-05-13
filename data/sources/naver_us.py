"""Naver Finance live-ticker snapshot for NASDAQ.

Reads cached US universe from ``data/cache/us/*.parquet``, fetches per-symbol
live data from Naver's unofficial endpoint with bounded concurrency, merges
with the existing snapshot (tickers absent from this fetch retain previous
values + ``fetched_at``), and atomically writes
``data/cache/us/_live_snapshot.parquet``.

CLI usage::

    python -m data.sources.naver_us [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
US_CACHE_DIR = _ROOT / "data" / "cache" / "us"
SNAPSHOT_PATH = US_CACHE_DIR / "_live_snapshot.parquet"

NAVER_BASIC_URL = "https://api.stock.naver.com/stock/{ticker}.O/basic"
FETCH_CONCURRENCY = 10
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------

def discover_universe() -> list[str]:
    """Cached US tickers (parquet files), alphabetical. Excludes ``_``-prefixed."""
    if not US_CACHE_DIR.exists():
        return []
    return sorted(
        p.stem for p in US_CACHE_DIR.glob("*.parquet") if not p.stem.startswith("_")
    )


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

async def _fetch_one(session, sem, ticker: str) -> tuple[str, Optional[dict[str, Any]]]:
    import aiohttp
    url = NAVER_BASIC_URL.format(ticker=ticker)
    async with sem:
        try:
            async with session.get(
                url,
                headers={"User-Agent": USER_AGENT, "Referer": "https://m.stock.naver.com/"},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status != 200:
                    return ticker, None
                return ticker, await r.json()
        except Exception:
            return ticker, None


async def _fetch_universe_async(tickers: list[str]) -> dict[str, dict[str, Any]]:
    import aiohttp
    sem = asyncio.Semaphore(FETCH_CONCURRENCY)
    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_one(session, sem, t) for t in tickers]
        results = await asyncio.gather(*tasks)
    return {sym: payload for sym, payload in results if payload is not None}


def fetch_universe(tickers: list[str]) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    payloads = asyncio.run(_fetch_universe_async(tickers))
    rows = [_normalize(sym, p) for sym, p in payloads.items()]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _normalize(symbol: str, p: dict[str, Any]) -> dict[str, Any]:
    totals = {item.get("code"): item.get("value") for item in (p.get("stockItemTotalInfos") or [])}
    row: dict[str, Any] = {
        "symbolCode": p.get("symbolCode") or symbol,
        "stockName": p.get("stockName"),
        "stockNameEng": p.get("stockNameEng"),
        "closePrice": _to_float(p.get("closePrice")),
        "fluctuationsRatio": _to_pct(p.get("fluctuationsRatio")),
        "accumulatedTradingVolume": _to_float(totals.get("accumulatedTradingVolume")),
        "marketValueRaw": _parse_market_value_usd(totals.get("marketValue")),
        "marketStatus": p.get("marketStatus"),
        "localTradedAt": p.get("localTradedAt"),
    }
    direction = (p.get("compareToPreviousPrice") or {}).get("code")
    if direction in {"4", "5"} and row["fluctuationsRatio"] is not None:
        row["fluctuationsRatio"] = -abs(row["fluctuationsRatio"])
    return row


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


# Parses Naver-formatted USD market-cap strings like "4조 2,914억 USD".
# 1조 = 10^12, 1억 = 10^8 (Korean accounting digit-grouping).
_MV_RE = re.compile(
    r"(?:(?P<jo>\d+(?:[\d,]*\d)?)\s*조\s*)?"
    r"(?:(?P<eok>\d+(?:[\d,]*\d)?)\s*억)?",
)


def _parse_market_value_usd(s: Any) -> Optional[float]:
    if s is None or s == "" or s == "N/A":
        return None
    s = str(s).strip()
    plain = _to_float(s.replace("USD", "").strip())
    if plain is not None and "조" not in s and "억" not in s:
        return plain
    m = _MV_RE.search(s)
    if not m or not (m.group("jo") or m.group("eok")):
        return None
    jo = _to_float(m.group("jo")) or 0.0
    eok = _to_float(m.group("eok")) or 0.0
    return jo * 1e12 + eok * 1e8


# ---------------------------------------------------------------------------
# Snapshot persistence — thin wrappers around the shared helpers
# ---------------------------------------------------------------------------

from data.sources._snapshot import (  # noqa: E402
    load_snapshot as _generic_load_snapshot,
    merge_snapshot as _generic_merge_snapshot,
    write_atomic,
)


def load_snapshot(path: Path = SNAPSHOT_PATH) -> Optional[pd.DataFrame]:
    return _generic_load_snapshot(path)


def merge_snapshot(new_df: pd.DataFrame, path: Path = SNAPSHOT_PATH) -> pd.DataFrame:
    return _generic_merge_snapshot(new_df, path, symbol_col="symbolCode")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 한글 보호

    ap = argparse.ArgumentParser(description="Fetch Naver NASDAQ live snapshot")
    ap.add_argument("--limit", type=int, default=0, help="0 = all cached symbols")
    args = ap.parse_args()

    universe = discover_universe()
    if args.limit > 0:
        universe = universe[: args.limit]

    if not universe:
        print("[error] no cached symbols in data/cache/us/")
        return 1

    started = pd.Timestamp.now(tz="Asia/Seoul")
    print(
        f"[info] fetching {len(universe)} symbols from Naver "
        f"(concurrency={FETCH_CONCURRENCY}, started {started.strftime('%H:%M:%S')})"
    )

    df = fetch_universe(universe)

    elapsed = (pd.Timestamp.now(tz="Asia/Seoul") - started).total_seconds()
    print(f"[info] received {len(df)}/{len(universe)} symbols in {elapsed:.1f}s")

    if df.empty:
        print("[error] no response from Naver")
        return 1

    merged = merge_snapshot(df)
    write_atomic(merged)
    print(f"[ok] wrote snapshot ({len(merged)} rows) -> {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
