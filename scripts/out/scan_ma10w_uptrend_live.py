"""주봉 MA10 + slope 스캔 — 라이브 ticker로 진행 중 봉 보강.

Bitget history-candles 는 진행 중 봉 (UTC 06-05) 을 안 주므로,
1d 캐시 + 라이브 ticker (lastPr) 로 "오늘 봉"을 합성한 뒤
주봉 리샘플 → MA10w / slope_2w 평가.
"""

from __future__ import annotations

import sys
import urllib.request
import json
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_1D = ROOT / "data" / "cache" / "crypto" / "1d"
TICKER_URL = (
    "https://api.bitget.com/api/v2/mix/market/tickers?productType=usdt-futures"
)


def fetch_live_tickers() -> dict[str, dict]:
    req = urllib.request.Request(TICKER_URL, headers={"User-Agent": "curl/7"})
    with urllib.request.urlopen(req, timeout=15) as r:
        j = json.loads(r.read().decode())
    if j.get("code") != "00000":
        raise RuntimeError(f"bitget api error: {j}")
    return {row["symbol"]: row for row in j["data"]}


def patch_with_live(df_1d: pd.DataFrame, tick: dict) -> pd.DataFrame:
    """1d 캐시 마지막 봉이 UTC 어제(=openUtc 기준)면 오늘 봉(진행중)을 1행 append."""
    last_pr = float(tick["lastPr"])
    high24 = float(tick["high24h"])
    low24 = float(tick["low24h"])
    open_utc = float(tick["openUtc"])  # UTC 자정 open = 오늘 진행중 일봉 open
    quote_vol = float(tick.get("quoteVolume") or 0)  # 24h 거래대금 (근사)
    base_vol = float(tick.get("baseVolume") or 0)

    # 오늘 UTC 자정 timestamp (ms)
    now_utc = datetime.now(timezone.utc)
    today_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    today_ms = int(today_utc.timestamp() * 1000)

    last_ts = int(df_1d["timestamp"].iloc[-1])
    if last_ts == today_ms:
        # 이미 오늘 봉 존재 → close 만 라이브로 덮어쓰기
        df_1d = df_1d.copy()
        df_1d.iloc[-1, df_1d.columns.get_loc("close")] = last_pr
        df_1d.iloc[-1, df_1d.columns.get_loc("high")] = max(
            df_1d["high"].iloc[-1], high24
        )
        df_1d.iloc[-1, df_1d.columns.get_loc("low")] = min(
            df_1d["low"].iloc[-1], low24
        )
        return df_1d
    # 새 봉 append
    new_row = {
        "timestamp": today_ms,
        "open": open_utc,
        "high": high24,
        "low": low24,
        "close": last_pr,
        "volume": base_vol,
        "amount": quote_vol,
    }
    return pd.concat([df_1d, pd.DataFrame([new_row])], ignore_index=True)


def resample_to_weekly(df_1d: pd.DataFrame) -> pd.DataFrame:
    df = df_1d.copy()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("dt")
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "amount": "sum",
    }
    out = df.resample("W-MON", label="left", closed="left").agg(agg).dropna()
    return out.reset_index(drop=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("[1/3] fetching live tickers from Bitget ...")
    tickers = fetch_live_tickers()
    print(f"      got {len(tickers)} symbols live")

    print("[2/3] scanning ...")
    rows = []
    skipped = 0
    symbols = sorted(p.stem for p in CACHE_1D.glob("*.parquet"))
    for sym in symbols:
        try:
            df_1d = pd.read_parquet(CACHE_1D / f"{sym}.parquet")
        except Exception:
            skipped += 1
            continue
        if len(df_1d) < 80:  # 주봉 13봉 ≈ 일봉 90+
            continue
        tick = tickers.get(sym)
        if tick is not None:
            df_1d = patch_with_live(df_1d, tick)

        df_1w = resample_to_weekly(df_1d)
        if len(df_1w) < 13:
            continue
        df_1w["ma10w"] = df_1w["close"].rolling(10).mean()
        last_idx = -1
        c = df_1w["close"].iloc[last_idx]
        ma = df_1w["ma10w"].iloc[last_idx]
        ma2 = df_1w["ma10w"].iloc[last_idx - 2]
        if pd.isna(ma) or pd.isna(ma2) or ma2 <= 0:
            continue
        slope = ma / ma2 - 1
        gap = c / ma - 1
        if c > ma and slope > 0:
            n = len(df_1w)
            end = n + last_idx + 1
            start = max(0, end - 4)
            amt_4w = df_1w["amount"].iloc[start:end].sum()
            rows.append(
                {
                    "symbol": sym,
                    "close": c,
                    "ma10w": ma,
                    "gap_pct": gap * 100,
                    "slope_2w_pct": slope * 100,
                    "amt_4w_M": amt_4w / 1e6,
                    "live_patched": tick is not None,
                }
            )

    print(f"      skipped={skipped}")
    df = pd.DataFrame(rows)
    print(f"[3/3] {len(df)} symbols pass (close>MA10w AND slope_2w>0)")
    if df.empty:
        return
    active = df[df["amt_4w_M"] >= 1.0].copy()
    print(f"      active (amt_4w>=1M USDT): {len(active)}")
    active = active.sort_values("slope_2w_pct", ascending=False)
    pd.set_option("display.max_rows", 200)
    pd.set_option("display.float_format", lambda x: f"{x:.2f}")
    print()
    print("Top 50 by slope_2w_pct (live-patched):")
    print(active.head(50).to_string(index=False))


if __name__ == "__main__":
    main()
