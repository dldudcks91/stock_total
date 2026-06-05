"""
OPN 패턴: 직전 N시간 동안 5%+ body 양봉이 0개였다가 갑자기 첫 5%+ 윗꼬리짧음 양봉.

조건:
  - 트리거: body >= 5% & body/(high-open) > 0.9
  - 직전 N시간 동안 body >= 5% 봉이 0개 (양봉/음봉 무관 큰 봉 없음 → 더 엄격하게 가능)
  - 최근 7일 안에 발생

N 을 sweep (72/120/168 시간) 해서 엄격도 별로 보여줌.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import numpy as np
import pandas as pd

CACHE = Path("data/cache/crypto/1h")
OUT_DIR = Path("scripts/out")
BODY_MIN = 0.05
CLOSE_TO_HIGH_MIN = 0.9
DAYS_BACK = 7


def scan(quiet_hours: int):
    last_ts = None
    for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]:
        fp = CACHE / f"{s}.parquet"
        if fp.exists():
            m = pd.read_parquet(fp, columns=["timestamp"])["timestamp"].max()
            if last_ts is None or m > last_ts:
                last_ts = m
    last_dt = pd.to_datetime(last_ts, unit="ms", utc=True)
    cutoff = last_dt - pd.Timedelta(days=DAYS_BACK)

    rows = []
    for fp in sorted(CACHE.glob("*.parquet")):
        s = fp.stem
        df = pd.read_parquet(fp).sort_values("timestamp").reset_index(drop=True)
        df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        if len(df) < quiet_hours + 24:
            continue

        body = df["close"] - df["open"]
        upper = df["high"] - df["open"]
        body_pct = body / df["open"]
        body_to_range = pd.Series(
            np.where(upper > 0, body / upper.replace(0, np.nan), np.nan),
            index=df.index,
        )
        mask_pump = (body_pct >= BODY_MIN) & (body_to_range > CLOSE_TO_HIGH_MIN)
        # 양봉 5%+ 만 (음봉 큰 봉은 허용) — 사용자가 말한 "평탄" 은 큰 양봉이 없음
        big_up = body_pct >= BODY_MIN

        # rolling: 직전 quiet_hours 동안 big_up 개수
        big_up_cnt = big_up.rolling(quiet_hours, closed="left").sum()
        mask_quiet = big_up_cnt == 0

        mask_time = df["ts"] >= cutoff
        full = mask_pump & mask_quiet & mask_time

        for i in df.index[full.fillna(False)].tolist():
            prev = df.iloc[i - quiet_hours:i]
            pmin = prev["close"].min()
            pmax = prev["close"].max()
            rng = (pmax - pmin) / pmin * 100 if pmin > 0 else np.nan
            rows.append({
                "symbol": s,
                "ts_kst": df["ts"].iloc[i].tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
                "close": float(df["close"].iloc[i]),
                "body_pct": float(body_pct.iloc[i] * 100),
                "wick_ratio": float(body_to_range.iloc[i]) if np.isfinite(body_to_range.iloc[i]) else np.nan,
                "prev_range_pct": float(rng),
                "prev_max": float(pmax),
                "breakout_pct": float((df["close"].iloc[i] - pmax) / pmax * 100),
            })

    df_out = pd.DataFrame(rows).sort_values("ts_kst", ascending=False).reset_index(drop=True)
    if not df_out.empty:
        nows = []
        for s in df_out["symbol"]:
            fpx = CACHE / f"{s}.parquet"
            nows.append(float(pd.read_parquet(fpx, columns=["close"])["close"].iloc[-1]))
        df_out["close_now"] = nows
        df_out["change_now_pct"] = (df_out["close_now"] - df_out["close"]) / df_out["close"] * 100

    print(f"\n=== quiet_hours={quiet_hours}h (= {quiet_hours/24:.1f}일) — {len(df_out)}건 ===")
    if not df_out.empty:
        show = df_out[["symbol", "ts_kst", "close", "close_now", "change_now_pct",
                       "body_pct", "wick_ratio", "prev_range_pct", "breakout_pct"]]
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 260)
        pd.set_option("display.max_rows", None)
        print(show.to_string(index=False, float_format=lambda x: f"{x:+.2f}"))
    df_out.to_csv(OUT_DIR / f"first_pump_after_quiet_{quiet_hours}h.csv", index=False)


def main():
    for n in [72, 120, 168]:
        scan(n)


if __name__ == "__main__":
    main()
