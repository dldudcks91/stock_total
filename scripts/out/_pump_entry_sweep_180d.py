"""
최근 6개월 (180일) 1H 5%+ 윗꼬리 짧은 양봉 트리거 후 t+1~t+8 MA10 위 유지 케이스.
  + entry 시점별 (t+0, t+5, t+8, t+10, t+12, t+15, t+18, t+20) → 현재까지 / forward 통계.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import numpy as np
import pandas as pd

CACHE = Path("data/cache/crypto/1h")
OUT_DIR = Path("scripts/out")
BODY_MIN = 0.05
WICK_MIN = 0.9
MA_N = 10
DAYS_BACK = 180
HOLD_BARS = 8
FORWARD = 20


def main():
    last_ts = None
    for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]:
        fp = CACHE / f"{s}.parquet"
        if fp.exists():
            m = pd.read_parquet(fp, columns=["timestamp"])["timestamp"].max()
            if last_ts is None or m > last_ts:
                last_ts = m
    last_dt = pd.to_datetime(last_ts, unit="ms", utc=True)
    cutoff = last_dt - pd.Timedelta(days=DAYS_BACK)
    print(f"window: {cutoff.tz_convert('Asia/Seoul')} ~ {last_dt.tz_convert('Asia/Seoul')} KST (180일)")

    rows = []
    for fp in sorted(CACHE.glob("*.parquet")):
        s = fp.stem
        df = pd.read_parquet(fp).sort_values("timestamp").reset_index(drop=True)
        df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        if len(df) < MA_N + HOLD_BARS + 5:
            continue
        df["ma10"] = df["close"].rolling(MA_N).mean()
        body = df["close"] - df["open"]
        upper = df["high"] - df["open"]
        body_pct = body / df["open"]
        body_to_range = pd.Series(
            np.where(upper > 0, body / upper.replace(0, np.nan), np.nan), index=df.index)
        mask_pump = (body_pct >= BODY_MIN) & (body_to_range > WICK_MIN)
        mask_time = df["ts"] >= cutoff
        full = mask_pump & mask_time

        closes = df["close"].values
        ma10s = df["ma10"].values
        n = len(df)

        for i in df.index[full.fillna(False)].tolist():
            if i + HOLD_BARS >= n:
                continue
            ec = closes[i]
            em = ma10s[i]
            if not (np.isfinite(em) and em > 0 and ec > em):
                continue
            held = True
            for k in range(1, HOLD_BARS + 1):
                j = i + k
                if not np.isfinite(ma10s[j]) or ma10s[j] <= 0 or closes[j] <= ma10s[j]:
                    held = False
                    break
            if not held:
                continue
            row = {"symbol": s, "ts_kst": df["ts"].iloc[i].tz_convert("Asia/Seoul"),
                   "close": float(ec), "body_pct": float(body_pct.iloc[i] * 100)}
            for k in range(1, FORWARD + 1):
                j = i + k
                row[f"t+{k}_close"] = float(closes[j]) if j < n else np.nan
            row["close_now"] = float(closes[-1])
            rows.append(row)

    ev = pd.DataFrame(rows)
    print(f"t+1~t+{HOLD_BARS} MA10 위 유지: {len(ev)}건 / {ev['symbol'].nunique()} 심볼")

    def entry_close(k):
        return ev["close"] if k == 0 else ev.get(f"t+{k}_close")

    print(f"\n=== 표 1. entry 시점별 → 현재까지 변화율 ===")
    print(f"{'entry':>8} {'n':>5} {'평균_%':>9} {'중앙값_%':>10} {'양수_%':>8} {'P25':>8} {'P75':>8} {'최대':>9} {'최소':>9}")
    for k in [0, 3, 5, 8, 10, 12, 15, 18, 20]:
        e = entry_close(k)
        if e is None:
            continue
        valid = e.notna() & ev["close_now"].notna()
        if valid.sum() == 0:
            continue
        pct = (ev["close_now"][valid] - e[valid]) / e[valid] * 100
        print(f"{'t+'+str(k):>8} {len(pct):>5d} {pct.mean():>+9.2f} {pct.median():>+10.2f} "
              f"{(pct>0).mean()*100:>7.1f}% {pct.quantile(0.25):>+8.2f} {pct.quantile(0.75):>+8.2f} "
              f"{pct.max():>+9.2f} {pct.min():>+9.2f}")

    print(f"\n=== 표 2. entry 시점별 short-term forward (+1 / +3 / +5 / +10 봉) ===")
    print(f"{'entry':>8} {'fwd':>5} {'n':>5} {'평균_%':>9} {'중앙값_%':>10} {'양수_%':>8} {'P25':>8} {'P75':>8}")
    for k in [0, 3, 5, 8, 10, 12, 15, 18, 20]:
        e = entry_close(k)
        if e is None:
            continue
        for fwd in [1, 3, 5, 10]:
            target_k = k + fwd
            tc = ev.get(f"t+{target_k}_close")
            if tc is None:
                continue
            valid = e.notna() & tc.notna()
            if valid.sum() == 0:
                continue
            pct = (tc[valid] - e[valid]) / e[valid] * 100
            print(f"{'t+'+str(k):>8} {'+'+str(fwd):>5} {len(pct):>5d} {pct.mean():>+9.2f} "
                  f"{pct.median():>+10.2f} {(pct>0).mean()*100:>7.1f}% "
                  f"{pct.quantile(0.25):>+8.2f} {pct.quantile(0.75):>+8.2f}")

    ev.to_csv(OUT_DIR / "pump_held_above_ma10_8bars_180d.csv", index=False)
    print(f"\nsaved → {OUT_DIR/'pump_held_above_ma10_8bars_180d.csv'}")


if __name__ == "__main__":
    main()
