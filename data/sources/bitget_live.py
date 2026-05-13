"""Bitget USDT-M futures live-ticker snapshot.

Fetches the bulk ``/v2/mix/market/tickers`` endpoint (all USDT-M symbols in
one request, ~1s) plus CoinGecko market caps, joins them on the coin base
symbol, and writes ``data/cache/crypto/_live_snapshot.parquet`` via the
shared snapshot helpers.

CLI usage::

    python -m data.sources.bitget_live [--no-mcap]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from data.sources._snapshot import (
    load_snapshot as _generic_load_snapshot,
    merge_snapshot as _generic_merge_snapshot,
    write_atomic,
)

_ROOT = Path(__file__).resolve().parents[2]
CRYPTO_CACHE_DIR = _ROOT / "data" / "cache" / "crypto"
SNAPSHOT_PATH = CRYPTO_CACHE_DIR / "_live_snapshot.parquet"

BITGET_TICKERS_URL = "https://api.bitget.com/api/v2/mix/market/tickers"
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
PRODUCT_TYPE = "USDT-FUTURES"

NUMERIC_COLS = [
    "lastPr", "askPr", "bidPr", "bidSz", "askSz",
    "high24h", "low24h", "ts", "change24h", "baseVolume",
    "quoteVolume", "usdtVolume", "openUtc", "changeUtc24h",
    "indexPrice", "fundingRate", "holdingAmount",
    "open24h", "markPrice",
]


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_tickers(timeout: float = 10.0) -> pd.DataFrame:
    """Fetch the full USDT-M futures ticker snapshot. Raises on API error."""
    resp = requests.get(
        BITGET_TICKERS_URL,
        params={"productType": PRODUCT_TYPE},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("msg") != "success":
        raise RuntimeError(
            f"Bitget API error: code={payload.get('code')} msg={payload.get('msg')}"
        )
    rows = payload.get("data", [])
    df = pd.DataFrame(rows)
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def fetch_market_caps(pages: int = 2, per_page: int = 250, timeout: float = 10.0) -> dict[str, float]:
    """Top N coins by market cap from CoinGecko → ``{SYMBOL_UPPER: market_cap_usd}``.

    First-seen wins (list is mcap-desc), so collisions like LUNA / LUNC resolve
    to the higher-cap ticker. Empty dict on failure.
    """
    caps: dict[str, float] = {}
    for page in range(1, pages + 1):
        try:
            resp = requests.get(
                COINGECKO_MARKETS_URL,
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": per_page,
                    "page": page,
                    "sparkline": "false",
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            for row in resp.json() or []:
                sym = (row.get("symbol") or "").upper()
                mc = row.get("market_cap")
                if sym and mc and sym not in caps:
                    caps[sym] = float(mc)
        except Exception:
            break
    return caps


def _bitget_to_base(symbol: str) -> Optional[str]:
    """``BTCUSDT`` → ``BTC``, ``1000PEPEUSDT`` → ``PEPE``, ``USDCUSDT`` → ``USDC``."""
    s = symbol.upper()
    if not s.endswith("USDT"):
        return None
    base = s[:-4]
    if base.startswith("1000") and len(base) > 4:
        base = base[4:]
    return base or None


def attach_market_cap(df: pd.DataFrame, caps: dict[str, float]) -> pd.DataFrame:
    """Add a ``marketCap`` column to ``df`` by mapping Bitget symbol → base coin."""
    if df.empty or not caps:
        df = df.copy()
        df["marketCap"] = pd.Series([None] * len(df), dtype="float64")
        return df
    df = df.copy()
    df["marketCap"] = (
        df["symbol"].astype(str).map(_bitget_to_base).map(caps).astype("float64")
    )
    return df


# ---------------------------------------------------------------------------
# Snapshot persistence — thin wrappers
# ---------------------------------------------------------------------------

def load_snapshot(path: Path = SNAPSHOT_PATH) -> Optional[pd.DataFrame]:
    return _generic_load_snapshot(path)


def merge_snapshot(new_df: pd.DataFrame, path: Path = SNAPSHOT_PATH) -> pd.DataFrame:
    return _generic_merge_snapshot(new_df, path, symbol_col="symbol")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 한글 보호

    ap = argparse.ArgumentParser(description="Fetch Bitget live snapshot + CoinGecko mcap")
    ap.add_argument("--no-mcap", action="store_true", help="skip CoinGecko market cap fetch")
    args = ap.parse_args()

    started = pd.Timestamp.now(tz="Asia/Seoul")
    print(f"[info] fetching Bitget USDT-M tickers ({started.strftime('%H:%M:%S')})")

    try:
        df = fetch_tickers()
    except Exception as e:
        print(f"[error] Bitget API failure: {e}")
        return 1
    print(f"[info] received {len(df)} tickers")

    if not args.no_mcap:
        caps = fetch_market_caps()
        print(f"[info] received {len(caps)} CoinGecko market caps")
        df = attach_market_cap(df, caps)
    else:
        df = df.copy()
        df["marketCap"] = pd.Series([None] * len(df), dtype="float64")

    if df.empty:
        print("[error] empty ticker response")
        return 1

    merged = merge_snapshot(df)
    write_atomic(merged, SNAPSHOT_PATH)
    elapsed = (pd.Timestamp.now(tz="Asia/Seoul") - started).total_seconds()
    print(f"[ok] wrote snapshot ({len(merged)} rows) in {elapsed:.1f}s -> {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
