"""NASDAQ live-ticker snapshot via the official nasdaq.com screener API.

Single HTTP request returns all ~4000 NASDAQ-listed tickers with current
price/volume/market-cap — replaces the per-symbol fan-out in
``data.sources.naver_us`` (which made 3000+ requests over ~5 minutes).

Endpoint: ``https://api.nasdaq.com/api/screener/stocks`` — unofficial but
stable; same JSON the NASDAQ.com stock screener page consumes.

Output schema matches ``naver_us`` so the snapshot parquet
(``data/cache/us/_live_snapshot.parquet``) and downstream dashboard code
stay compatible:

  symbolCode, stockName, stockNameEng, closePrice, fluctuationsRatio,
  accumulatedTradingVolume, marketValueRaw, marketStatus, localTradedAt,
  netChange, sector, industry, country, fetched_at

CLI::

    python -m data.sources.nasdaq_screener [--exchange NASDAQ|NYSE|AMEX|ALL]
"""
from __future__ import annotations

import argparse
import re
import sys
import time
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
US_CACHE_DIR = _ROOT / "data" / "cache" / "us"
SNAPSHOT_PATH = US_CACHE_DIR / "_live_snapshot.parquet"

SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}


# ---------------------------------------------------------------------------
# Universe (kept for parity with naver_us.discover_universe — dashboards use
# it to display the cached-symbol count in the toolbar)
# ---------------------------------------------------------------------------

def discover_universe() -> list[str]:
    """Cached US tickers from local parquet stems. Excludes ``_``-prefixed."""
    if not US_CACHE_DIR.exists():
        return []
    return sorted(
        p.stem for p in US_CACHE_DIR.glob("*.parquet") if not p.stem.startswith("_")
    )


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_screener(exchange: str = "NASDAQ", limit: int = 10000,
                   timeout: float = 20.0) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return (df, meta) for the given exchange.

    ``exchange``: ``NASDAQ``, ``NYSE``, ``AMEX``, or ``"ALL"`` (omit filter).
    """
    params = {"tableonly": "true", "limit": str(limit), "download": "true"}
    if exchange and exchange.upper() != "ALL":
        params["exchange"] = exchange.upper()

    r = requests.get(SCREENER_URL, params=params, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    payload = r.json()
    data = payload.get("data") or {}
    rows = data.get("rows") or (data.get("table", {}) or {}).get("rows") or []
    meta = {
        "totalCount": (data.get("totalrecords")
                       or len(rows)),
        "asOf": data.get("asof") or data.get("asOf"),
        "status": payload.get("status", {}).get("rCode"),
    }
    return _normalize(rows), meta


# ---------------------------------------------------------------------------
# Normalization — map screener fields to naver_us schema
# ---------------------------------------------------------------------------

def _normalize(rows: list[dict[str, Any]]) -> pd.DataFrame:
    out = []
    for s in rows:
        sym = (s.get("symbol") or "").strip()
        if not sym:
            continue
        name = (s.get("name") or "").strip()
        out.append({
            "symbolCode": sym,
            "stockName": name,         # NASDAQ screener has only English name
            "stockNameEng": name,      # mirrored for naver_us compatibility
            "closePrice": _parse_price(s.get("lastsale")),
            "fluctuationsRatio": _parse_pct(s.get("pctchange")),
            "netChange": _parse_price(s.get("netchange")),
            "accumulatedTradingVolume": _to_float(s.get("volume")),
            "marketValueRaw": _to_float(s.get("marketCap")),
            "marketStatus": None,      # screener doesn't expose this
            "localTradedAt": None,
            "country": s.get("country"),
            "sector": s.get("sector"),
            "industry": s.get("industry"),
        })
    return pd.DataFrame(out)


_PRICE_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _parse_price(s: Any) -> Optional[float]:
    """Parse strings like ``"$10.44"``, ``"-$0.25"``, ``"NA"``."""
    if s is None:
        return None
    txt = str(s).strip()
    if not txt or txt.upper() in {"NA", "N/A", "--"}:
        return None
    m = _PRICE_RE.search(txt.replace(",", ""))
    if not m:
        return None
    val = float(m.group())
    if "-$" in txt or txt.startswith("-"):
        val = -abs(val)
    return val


def _parse_pct(s: Any) -> Optional[float]:
    """``"0.096%" -> 0.00096`` (decimal, matching naver_us semantics)."""
    if s is None:
        return None
    txt = str(s).strip().rstrip("%")
    if not txt or txt.upper() in {"NA", "N/A", "--", "UNCH"}:
        return None
    try:
        return float(txt.replace(",", "")) / 100.0
    except ValueError:
        return None


def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    txt = str(x).strip().replace(",", "").replace("$", "")
    if not txt or txt.upper() in {"NA", "N/A", "--"}:
        return None
    try:
        return float(txt)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Snapshot persistence — thin wrappers
# ---------------------------------------------------------------------------

def load_snapshot(path: Path = SNAPSHOT_PATH) -> Optional[pd.DataFrame]:
    return _generic_load_snapshot(path)


def merge_snapshot(new_df: pd.DataFrame, path: Path = SNAPSHOT_PATH) -> pd.DataFrame:
    return _generic_merge_snapshot(new_df, path, symbol_col="symbolCode")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="Fetch NASDAQ live snapshot (one-shot)")
    ap.add_argument("--exchange", default="NASDAQ",
                    choices=["NASDAQ", "NYSE", "AMEX", "ALL"],
                    help="Which US exchange to fetch (default NASDAQ).")
    args = ap.parse_args()

    started = pd.Timestamp.now(tz="Asia/Seoul")
    print(f"[info] fetching {args.exchange} screener from api.nasdaq.com "
          f"({started.strftime('%H:%M:%S')})")

    t0 = time.time()
    try:
        df, meta = fetch_screener(args.exchange)
    except Exception as e:
        print(f"[error] nasdaq screener fetch failed: {e}")
        return 1
    elapsed = time.time() - t0
    print(f"[info] received {len(df)} rows in {elapsed:.2f}s "
          f"(totalCount={meta.get('totalCount')}, asOf={meta.get('asOf')})")

    if df.empty:
        print("[error] empty response")
        return 1

    merged = merge_snapshot(df)
    write_atomic(merged, SNAPSHOT_PATH)
    print(f"[ok] wrote snapshot ({len(merged)} rows) -> {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
