"""
pump_recent_30d_events.csv 후처리:
  주봉 MA20 위 0~10% 밴드 (추세 초입) 최근 20건 + 현재가격(데이터 마지막 1H close) 비교.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import pandas as pd

CACHE_1H = Path("data/cache/crypto/1h")
OUT_DIR = Path("scripts/out")
SRC = OUT_DIR / "pump_recent_30d_events.csv"


def last_close(symbol: str):
    fp = CACHE_1H / f"{symbol}.parquet"
    if not fp.exists():
        return None, None
    df = pd.read_parquet(fp, columns=["timestamp", "close"]).sort_values("timestamp")
    ts = pd.to_datetime(df["timestamp"].iloc[-1], unit="ms", utc=True).tz_convert("Asia/Seoul")
    return float(df["close"].iloc[-1]), ts


def main():
    ev = pd.read_csv(SRC, parse_dates=["ts_utc", "ts_kst"])
    band = ev[ev["category"] == "w20_band_0to10"].sort_values("ts_utc", ascending=False).head(20).copy()

    nows, now_ts_set = [], set()
    for s in band["symbol"]:
        c, t = last_close(s)
        nows.append(c)
        if t is not None:
            now_ts_set.add(t)
    band["close_now"] = nows
    band["change_now_vs_trigger_pct"] = (band["close_now"] - band["close"]) / band["close"] * 100.0
    band["ts_kst"] = band["ts_kst"].dt.strftime("%Y-%m-%d %H:%M")

    show = band[["symbol", "ts_kst", "close", "close_now", "change_now_vs_trigger_pct",
                 "body_pct", "close_to_weekly_ma20_pct"]].copy()
    print(f"data last 1H bar (모든 심볼 공통 시점): {sorted(now_ts_set)[-1].strftime('%Y-%m-%d %H:%M')} KST" if now_ts_set else "")
    print("\n=== 주봉 MA20 위 0~10% 밴드 — 최근 20건 + 현재가격 비교 ===")
    print(show.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    show.to_csv(OUT_DIR / "pump_recent_30d_w20band_with_now.csv", index=False)
    print(f"\nsaved → {OUT_DIR/'pump_recent_30d_w20band_with_now.csv'}")


if __name__ == "__main__":
    main()
