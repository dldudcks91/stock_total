"""Bitget USDT-M 선물 전 종목 1H OHLCV 다운로드 → parquet 캐시.

Bitget v2 REST 직접 호출 (ccxt 미사용).
- 마켓 리스트: GET /api/v2/mix/market/tickers?productType=usdt-futures
- 캔들 조회:  GET /api/v2/mix/market/history-candles

CLI:
    python -m data.fetch_bitget                      # 전 종목 (증분)
    python -m data.fetch_bitget --symbol BTCUSDT
    python -m data.fetch_bitget --since 2020-01-01   # 처음부터
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import pandas as pd
import requests

CACHE_DIR = Path(__file__).parent / "cache"
BASE = "https://api.bitget.com/api/v2/mix/market"
TICKERS_URL = f"{BASE}/tickers"
CANDLES_URL = f"{BASE}/history-candles"

PRODUCT_TYPE = "usdt-futures"
GRANULARITY = "1H"
HOUR_MS = 3_600_000
LIMIT = 200  # Bitget v2 history-candles 최대치
DEFAULT_SINCE = "2020-01-01"

# 동시 요청 제한 (Bitget IP 한도 20 req/s — 보수적으로)
CONCURRENCY = 5
BATCH_SLEEP_SEC = 0.5
RETRY_429_MAX = 5

OHLCV_COLS = ["timestamp", "open", "high", "low", "close", "volume", "amount"]


# ──────────────────────────── 마켓 목록 ────────────────────────────
def list_usdt_perp_symbols() -> list[str]:
    r = requests.get(TICKERS_URL, params={"productType": PRODUCT_TYPE}, timeout=10)
    r.raise_for_status()
    data = r.json().get("data", [])
    return sorted(t["symbol"] for t in data)


# ──────────────────────────── 캔들 조회 ────────────────────────────
async def _fetch_window(
    session: aiohttp.ClientSession, symbol: str, start_ms: int, end_ms: int
) -> list[list]:
    """endTime 직전의 1H 캔들을 최대 LIMIT개 받아옴 (Bitget은 endTime 기준 거꾸로 응답)."""
    params = {
        "symbol": symbol,
        "productType": PRODUCT_TYPE,
        "granularity": GRANULARITY,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": LIMIT,
    }
    for attempt in range(RETRY_429_MAX):
        async with session.get(CANDLES_URL, params=params, timeout=15) as resp:
            if resp.status == 429:
                await asyncio.sleep(2 ** attempt)  # 1, 2, 4, 8, 16
                continue
            resp.raise_for_status()
            body = await resp.json()
        if body.get("code") != "00000":
            raise RuntimeError(f"{symbol} {body.get('code')}: {body.get('msg')}")
        return body.get("data") or []
    raise RuntimeError(f"{symbol}: 429 after {RETRY_429_MAX} retries")


async def fetch_full_history(
    session: aiohttp.ClientSession, symbol: str, start_ms: int, end_ms: int
) -> pd.DataFrame:
    """start_ms 부터 end_ms 까지 endTime을 과거로 옮겨가며 페이지네이션."""
    all_rows: list[list] = []
    cursor_end = end_ms
    window_ms = LIMIT * HOUR_MS  # Bitget은 큰 윈도우를 거부 — limit*granularity로 좁힘
    while cursor_end > start_ms:
        win_start = max(start_ms, cursor_end - window_ms)
        chunk = await _fetch_window(session, symbol, win_start, cursor_end)
        if not chunk:
            # 이 구간엔 데이터 없음(상장 전). 더 과거로 이동.
            if win_start <= start_ms:
                break
            cursor_end = win_start
            await asyncio.sleep(0.05)
            continue
        # 응답은 시간 오름차순. chunk[0]가 가장 오래된 ts.
        all_rows.extend(chunk)
        first_ts = int(chunk[0][0])
        if first_ts <= start_ms:
            break
        cursor_end = first_ts  # endTime exclusive 가정
        await asyncio.sleep(0.05)

    if not all_rows:
        return pd.DataFrame(columns=OHLCV_COLS)

    # 캔들 포맷: [ts_ms, open, high, low, close, volume, amount]
    df = pd.DataFrame(all_rows, columns=OHLCV_COLS)
    df["timestamp"] = df["timestamp"].astype("int64")
    for c in OHLCV_COLS[1:]:
        df[c] = df[c].astype("float64")
    return (
        df.drop_duplicates("timestamp")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


# ──────────────────────────── 캐시 입출력 ────────────────────────────
def cache_path(symbol: str) -> Path:
    return CACHE_DIR / f"bitget_{symbol}_1h.parquet"


def _resolve_since(symbol: str, force_since_ms: int | None) -> int:
    """force_since_ms 없으면 캐시 마지막 + 1h, 그것도 없으면 DEFAULT_SINCE."""
    if force_since_ms is not None:
        return force_since_ms
    path = cache_path(symbol)
    if path.exists():
        existing = pd.read_parquet(path)
        if not existing.empty:
            return int(existing["timestamp"].iloc[-1]) + HOUR_MS
    return _iso_to_ms(DEFAULT_SINCE)


def _merge_with_cache(symbol: str, new_df: pd.DataFrame) -> pd.DataFrame:
    path = cache_path(symbol)
    if path.exists():
        old = pd.read_parquet(path)
        new_df = pd.concat([old, new_df], ignore_index=True)
    return (
        new_df.drop_duplicates("timestamp")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


# ──────────────────────────── 단일/전체 ────────────────────────────
async def fetch_one(
    session: aiohttp.ClientSession, symbol: str, force_since_ms: int | None
) -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    start_ms = _resolve_since(symbol, force_since_ms)
    end_ms = _now_hour_ms()
    if start_ms >= end_ms:
        return pd.read_parquet(cache_path(symbol))

    new_df = await fetch_full_history(session, symbol, start_ms, end_ms)
    merged = _merge_with_cache(symbol, new_df)
    merged.to_parquet(cache_path(symbol), index=False)
    return merged


async def fetch_all(force_since_ms: int | None) -> None:
    symbols = list_usdt_perp_symbols()
    print(f"{len(symbols)} USDT-M perpetual symbols on Bitget")
    sem = asyncio.Semaphore(CONCURRENCY)

    async with aiohttp.ClientSession() as session:

        async def _task(i: int, sym: str) -> None:
            async with sem:
                t0 = time.time()
                try:
                    df = await fetch_one(session, sym, force_since_ms)
                    print(
                        f"[{i:>4}/{len(symbols)}] {sym:<20} "
                        f"rows={len(df):>6}  ({time.time() - t0:4.1f}s)"
                    )
                except Exception as e:
                    print(f"[{i:>4}/{len(symbols)}] {sym:<20} ERROR: {e}")

        for i in range(0, len(symbols), CONCURRENCY):
            batch = symbols[i : i + CONCURRENCY]
            await asyncio.gather(
                *(_task(i + j + 1, s) for j, s in enumerate(batch))
            )
            if i + CONCURRENCY < len(symbols):
                await asyncio.sleep(BATCH_SLEEP_SEC)


# ──────────────────────────── 유틸 ────────────────────────────
def _iso_to_ms(s: str) -> int:
    dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _now_hour_ms() -> int:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return int(now.timestamp() * 1000)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", help="단일 심볼 (예: BTCUSDT)")
    p.add_argument("--since", help="시작 일자 ISO (예: 2020-01-01). 생략 시 증분")
    args = p.parse_args()

    force_since_ms = _iso_to_ms(args.since) if args.since else None

    if args.symbol:

        async def _run_one() -> None:
            async with aiohttp.ClientSession() as session:
                df = await fetch_one(session, args.symbol, force_since_ms)
                print(f"{args.symbol}: {len(df)} rows -> {cache_path(args.symbol)}")

        asyncio.run(_run_one())
    else:
        asyncio.run(fetch_all(force_since_ms))


if __name__ == "__main__":
    main()
