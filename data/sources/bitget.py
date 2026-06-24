"""Bitget USDT-M 선물 전 종목 OHLCV 다운로드 → parquet 캐시.

Bitget v2 REST 직접 호출 (ccxt 미사용).
- 마켓 리스트: GET /api/v2/mix/market/tickers?productType=usdt-futures
- 캔들 조회:  GET /api/v2/mix/market/history-candles

CLI:
    python -m data.sources.bitget                                # 전 종목 1H (증분)
    python -m data.sources.bitget --granularity 1d               # 전 종목 1D
    python -m data.sources.bitget --symbol BTCUSDT --granularity 1d
    python -m data.sources.bitget --granularity 1d --since 2017-01-01 # 처음부터
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # 한자/이모지 심볼이 cp949에서 깨지는 것 방지
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
import pandas as pd
import requests

from data import fetch_log

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "crypto"
BASE = "https://api.bitget.com/api/v2/mix/market"
TICKERS_URL = f"{BASE}/tickers"
CANDLES_URL = f"{BASE}/history-candles"   # 닫힌(완성) 봉만 — 백필용
RECENT_CANDLES_URL = f"{BASE}/candles"    # 진행 중(미완성) 봉 포함 — 최신 보충용

PRODUCT_TYPE = "usdt-futures"
LIMIT = 200  # Bitget v2 history-candles 최대치

# user-facing key → (Bitget API granularity, ms per candle, max request window ms)
# 주의: Bitget v2 history-candles는 윈도우 크기에 granularity별 캡이 있음 (한계가 200×candle이 아님).
#   1H : 200시간 (≈8.3일) OK
#   1D : 약 90일이 상한 (200일은 40017 에러)
GRAN_SPEC: dict[str, tuple[str, int, int]] = {
    "1h": ("1H", 3_600_000, 200 * 3_600_000),
    "4h": ("4H", 14_400_000, 200 * 14_400_000),
    "1d": ("1Dutc", 86_400_000, 90 * 86_400_000),
    "1w": ("1Wutc", 604_800_000, 52 * 604_800_000),
}

DEFAULT_SINCE_BY_GRAN = {
    "1h": "2020-01-01",
    "4h": "2020-01-01",
    "1d": "2017-01-01",  # Bitget이 리턴 시작 시점까지 알아서 멈춤
    "1w": "2017-01-01",
}

# 동시 요청 제한 (Bitget IP 한도 20 req/s).
# CONCURRENCY=5 + BATCH_SLEEP_SEC=0.2 → 평균 ~25 req/s 순간 부하, 0.2s sleep 으로
# 분산되면 정상 처리됨 (429 발생 시 _fetch_window 가 exponential backoff 처리).
# 0.5 였을 때 6xx 종목 fetch 의 sleep 만으로 60s 이상 손실 → 0.2 로 단축.
CONCURRENCY = 5
BATCH_SLEEP_SEC = 0.2
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
    session: aiohttp.ClientSession,
    symbol: str,
    start_ms: int,
    end_ms: int,
    bitget_gran: str,
) -> list[list]:
    """endTime 직전 캔들을 최대 LIMIT개 받아옴 (Bitget은 endTime 기준 거꾸로 응답)."""
    params = {
        "symbol": symbol,
        "productType": PRODUCT_TYPE,
        "granularity": bitget_gran,
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


async def _fetch_recent(
    session: aiohttp.ClientSession,
    symbol: str,
    bitget_gran: str,
    limit: int = 10,
) -> list[list]:
    """`candles` 엔드포인트 — 진행 중(미완성) 봉을 포함한 최근 캔들."""
    params = {
        "symbol": symbol,
        "productType": PRODUCT_TYPE,
        "granularity": bitget_gran,
        "limit": limit,
    }
    for attempt in range(RETRY_429_MAX):
        async with session.get(RECENT_CANDLES_URL, params=params, timeout=15) as resp:
            if resp.status == 429:
                await asyncio.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            body = await resp.json()
        if body.get("code") != "00000":
            raise RuntimeError(f"{symbol} {body.get('code')}: {body.get('msg')}")
        return body.get("data") or []
    raise RuntimeError(f"{symbol}: 429 after {RETRY_429_MAX} retries")


async def fetch_full_history(
    session: aiohttp.ClientSession,
    symbol: str,
    start_ms: int,
    end_ms: int,
    gran: str,
) -> pd.DataFrame:
    """start_ms 부터 end_ms 까지 endTime을 과거로 옮겨가며 페이지네이션."""
    bitget_gran, candle_ms, window_ms = GRAN_SPEC[gran]
    all_rows: list[list] = []
    cursor_end = end_ms
    while cursor_end > start_ms:
        win_start = max(start_ms, cursor_end - window_ms)
        chunk = await _fetch_window(session, symbol, win_start, cursor_end, bitget_gran)
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

    return _rows_to_df(all_rows)


def _rows_to_df(rows: list[list]) -> pd.DataFrame:
    """Bitget 캔들 행 리스트 → 표준 DataFrame. 포맷: [ts_ms, o, h, l, c, vol, amount]."""
    if not rows:
        return pd.DataFrame(columns=OHLCV_COLS)
    df = pd.DataFrame(rows, columns=OHLCV_COLS)
    df["timestamp"] = df["timestamp"].astype("int64")
    for c in OHLCV_COLS[1:]:
        df[c] = df[c].astype("float64")
    return (
        df.drop_duplicates("timestamp")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


# ──────────────────────────── 캐시 입출력 ────────────────────────────
def cache_path(symbol: str, gran: str = "1h") -> Path:
    """data/cache/crypto/{gran}/{SYMBOL}.parquet."""
    return CACHE_DIR / gran / f"{symbol}.parquet"


def _resolve_since(symbol: str, gran: str, force_since_ms: Optional[int]) -> int:
    """force_since_ms 없으면 캐시 마지막 candle, 그것도 없으면 DEFAULT_SINCE.

    마지막 candle 을 (+1 이 아니라) 그대로 재요청하는 이유: 진행 중(미완성)
    봉을 저장한 뒤 그 봉이 닫히면 최신 값으로 덮어써야 하기 때문. _merge_with_cache
    가 keep="last" 라서 재요청된 봉이 옛 partial 봉을 갱신한다.
    """
    if force_since_ms is not None:
        return force_since_ms
    path = cache_path(symbol, gran)
    if path.exists():
        existing = pd.read_parquet(path)
        if not existing.empty:
            return int(existing["timestamp"].iloc[-1])
    return _iso_to_ms(DEFAULT_SINCE_BY_GRAN[gran])


def _merge_with_cache(symbol: str, gran: str, new_df: pd.DataFrame) -> pd.DataFrame:
    path = cache_path(symbol, gran)
    if path.exists():
        old = pd.read_parquet(path)
        new_df = pd.concat([old, new_df], ignore_index=True)
    return (
        new_df.drop_duplicates("timestamp", keep="last")  # 재요청된 봉이 옛 partial 갱신
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


# ──────────────────────────── 단일/전체 ────────────────────────────
async def fetch_one(
    session: aiohttp.ClientSession,
    symbol: str,
    gran: str,
    force_since_ms: Optional[int],
    closed_only: bool = False,
) -> pd.DataFrame:
    (CACHE_DIR / gran).mkdir(parents=True, exist_ok=True)
    start_ms = _resolve_since(symbol, gran, force_since_ms)
    # closed_only=False(기본): 진행 중인 현재 봉까지 포함하려고 now 를 그대로 endTime 으로.
    # closed_only=True: 닫힌 봉만 — 캔들 경계로 floor (백테스트 룩어헤드 방지용).
    end_ms = _now_aligned_ms(gran) if closed_only else _now_ms()
    if start_ms >= end_ms:
        return pd.read_parquet(cache_path(symbol, gran))

    new_df = await fetch_full_history(session, symbol, start_ms, end_ms, gran)
    if not closed_only:
        # history-candles 는 닫힌 봉만 주므로, 진행 중인 현재 봉을 candles 엔드포인트로 보충.
        bitget_gran = GRAN_SPEC[gran][0]
        recent = await _fetch_recent(session, symbol, bitget_gran)
        new_df = pd.concat([new_df, _rows_to_df(recent)], ignore_index=True)
    merged = _merge_with_cache(symbol, gran, new_df)
    merged.to_parquet(cache_path(symbol, gran), index=False)
    return merged


async def fetch_all(gran: str, force_since_ms: Optional[int], closed_only: bool = False) -> None:
    symbols = list_usdt_perp_symbols()
    print(f"{len(symbols)} USDT-M perpetual symbols on Bitget (granularity={gran})")
    sem = asyncio.Semaphore(CONCURRENCY)

    async with aiohttp.ClientSession() as session:

        async def _task(i: int, sym: str) -> None:
            async with sem:
                t0 = time.time()
                try:
                    df = await fetch_one(session, sym, gran, force_since_ms, closed_only)
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

    fetch_log.mark(f"crypto_{gran}", n_symbols=len(symbols))


# ──────────────────────────── 유틸 ────────────────────────────
def _iso_to_ms(s: str) -> int:
    dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _now_ms() -> int:
    """현재 시각 ms (UTC). 진행 중인 봉까지 포함하려고 endTime 으로 사용."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _now_aligned_ms(gran: str) -> int:
    """현재 시각을 해당 granularity 캔들 경계로 floor (UTC)."""
    _, candle_ms, _ = GRAN_SPEC[gran]
    return (_now_ms() // candle_ms) * candle_ms


def main() -> None:
    # CLAUDE.md venv 규칙: 시스템(anaconda) 파이썬으로 실행 금지.
    # aiohttp ProactorEventLoop 호환성과 의존성 버전 정합을 위해 .venv 강제.
    from data._venv_guard import require_project_venv
    require_project_venv()

    p = argparse.ArgumentParser()
    p.add_argument("--symbol", help="단일 심볼 (예: BTCUSDT)")
    p.add_argument(
        "--granularity",
        default="1h",
        choices=list(GRAN_SPEC.keys()),
        help="캔들 주기 (1h/4h/1d/1w). 기본 1h",
    )
    p.add_argument("--since", help="시작 일자 ISO (예: 2020-01-01). 생략 시 증분")
    p.add_argument(
        "--closed-only",
        action="store_true",
        help="닫힌 봉만 저장 (기본은 진행 중 봉도 포함). 백테스트 룩어헤드 방지용.",
    )
    args = p.parse_args()

    gran = args.granularity.lower()
    force_since_ms = _iso_to_ms(args.since) if args.since else None
    closed_only = args.closed_only

    if args.symbol:

        async def _run_one() -> None:
            async with aiohttp.ClientSession() as session:
                df = await fetch_one(session, args.symbol, gran, force_since_ms, closed_only)
                print(
                    f"{args.symbol} [{gran}]: {len(df)} rows -> "
                    f"{cache_path(args.symbol, gran)}"
                )

        asyncio.run(_run_one())
    else:
        asyncio.run(fetch_all(gran, force_since_ms, closed_only))


if __name__ == "__main__":
    main()
