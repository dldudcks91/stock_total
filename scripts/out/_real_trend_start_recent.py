"""
진짜 추세 시작 후보 — 최근 20일 신호.

조건 4개 동시 만족:
  (1) 베이스: 직전 56일(8주) close 의 (max-min)/min <= 0.25  (= ±25% 박스)
  (2) 돌파:  트리거 봉 close > 직전 56일 high                  (= 베이스 상단 돌파)
  (3) 추세:  주봉 MA30 의 4주 변화율 > 0                        (= 장기 우상향)
  (4) 양봉:  body >= 5%, body/(high-open) > 0.9

룩어헤드 방지: 베이스 high/low 와 weekly MA30 모두 트리거 봉 *이전* 시점 값만 사용.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import numpy as np
import pandas as pd

CACHE_1H = Path("data/cache/crypto/1h")
CACHE_1D = Path("data/cache/crypto/1d")
OUT_DIR = Path("scripts/out")

BODY_MIN = 0.05
CLOSE_TO_HIGH_MIN = 0.9
BASE_DAYS = 56
BASE_RANGE_MAX = 0.25
WEEKLY_MA_N = 30
SLOPE_LB_WEEKS = 4
DAYS_BACK = 20


def load_one(symbol):
    fp_1h = CACHE_1H / f"{symbol}.parquet"
    fp_1d = CACHE_1D / f"{symbol}.parquet"
    if not fp_1h.exists() or not fp_1d.exists():
        return None
    df_1h = pd.read_parquet(fp_1h).sort_values("timestamp").reset_index(drop=True)
    df_1d = pd.read_parquet(fp_1d).sort_values("timestamp").reset_index(drop=True)
    if len(df_1d) < WEEKLY_MA_N * 7 + BASE_DAYS + 10:
        return None
    df_1h["ts"] = pd.to_datetime(df_1h["timestamp"], unit="ms", utc=True)
    df_1d["ts"] = pd.to_datetime(df_1d["timestamp"], unit="ms", utc=True)

    d = df_1d.set_index("ts")
    # 주봉 MA30 + 4주 변화율 (직전 주봉만 사용 → shift(1))
    weekly_close = d["close"].resample("W-MON", closed="left", label="left").last()
    weekly_ma30 = weekly_close.rolling(WEEKLY_MA_N).mean()
    weekly_ma30_slope = (weekly_ma30 - weekly_ma30.shift(SLOPE_LB_WEEKS)) / weekly_ma30.shift(SLOPE_LB_WEEKS)

    # 일봉 베이스 (트리거 봉 이전 56일)
    base_high = d["high"].rolling(BASE_DAYS).max().shift(1)
    base_low = d["low"].rolling(BASE_DAYS).min().shift(1)
    base_range_pct = (base_high - base_low) / base_low

    h = df_1h.set_index("ts").sort_index()
    h["weekly_ma30_slope"] = weekly_ma30_slope.shift(1).reindex(h.index, method="ffill").values
    h["base_high"] = base_high.reindex(h.index, method="ffill").values
    h["base_low"] = base_low.reindex(h.index, method="ffill").values
    h["base_range_pct"] = base_range_pct.reindex(h.index, method="ffill").values
    return h.reset_index()


def main():
    symbols = sorted(p.stem for p in CACHE_1H.glob("*.parquet"))

    last_ts = None
    for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]:
        fp = CACHE_1H / f"{s}.parquet"
        if fp.exists():
            mts = pd.read_parquet(fp, columns=["timestamp"])["timestamp"].max()
            if last_ts is None or mts > last_ts:
                last_ts = mts
    last_dt = pd.to_datetime(last_ts, unit="ms", utc=True)
    cutoff = last_dt - pd.Timedelta(days=DAYS_BACK)
    print(f"data last 1H bar: {last_dt.tz_convert('Asia/Seoul')} (KST)")
    print(f"cutoff (20d back): {cutoff.tz_convert('Asia/Seoul')} (KST)")
    print(f"universe: {len(symbols)} symbols")

    rows = []
    for s in symbols:
        try:
            df = load_one(s)
            if df is None:
                continue
            body = df["close"] - df["open"]
            upper = df["high"] - df["open"]
            body_pct = body / df["open"]
            body_to_range = pd.Series(
                np.where(upper > 0, body / upper.replace(0, np.nan), np.nan),
                index=df.index,
            )
            mask_pump = (body_pct >= BODY_MIN) & (body_to_range > CLOSE_TO_HIGH_MIN)
            mask_base = df["base_range_pct"] <= BASE_RANGE_MAX
            mask_breakout = df["close"] > df["base_high"]
            mask_slope = df["weekly_ma30_slope"] > 0
            mask_time = df["ts"] >= cutoff

            full_mask = mask_pump & mask_base & mask_breakout & mask_slope & mask_time
            for i in df.index[full_mask.fillna(False)].tolist():
                rows.append({
                    "symbol": s,
                    "ts_kst": df["ts"].iloc[i].tz_convert("Asia/Seoul"),
                    "close": float(df["close"].iloc[i]),
                    "body_pct": float(body_pct.iloc[i] * 100),
                    "base_range_pct": float(df["base_range_pct"].iloc[i] * 100),
                    "base_high": float(df["base_high"].iloc[i]),
                    "breakout_pct": float((df["close"].iloc[i] - df["base_high"].iloc[i]) / df["base_high"].iloc[i] * 100),
                    "weekly_ma30_slope_4w_pct": float(df["weekly_ma30_slope"].iloc[i] * 100),
                })
        except Exception as e:
            print(f"  skip {s}: {e}")

    if not rows:
        print("\n해당 조건을 만족하는 트리거 없음.")
        return

    df = pd.DataFrame(rows).sort_values("ts_kst", ascending=False)

    nows = []
    for s in df["symbol"]:
        fp = CACHE_1H / f"{s}.parquet"
        nows.append(float(pd.read_parquet(fp, columns=["close"])["close"].iloc[-1]))
    df["close_now"] = nows
    df["change_now_pct"] = (df["close_now"] - df["close"]) / df["close"] * 100.0
    df["ts_kst"] = df["ts_kst"].dt.strftime("%Y-%m-%d %H:%M")

    print(f"\n=== 최근 20일 진짜 추세 시작 후보 ===")
    print(f"트리거 횟수: {len(df)}, 고유 심볼: {df['symbol'].nunique()}")

    show = df[["symbol", "ts_kst", "close", "close_now", "change_now_pct",
               "body_pct", "base_range_pct", "breakout_pct", "weekly_ma30_slope_4w_pct"]]
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 280)
    print("\n" + show.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    df.to_csv(OUT_DIR / "pump_real_trend_start_recent_20d.csv", index=False)
    print(f"\nsaved → {OUT_DIR/'pump_real_trend_start_recent_20d.csv'}")


if __name__ == "__main__":
    main()
