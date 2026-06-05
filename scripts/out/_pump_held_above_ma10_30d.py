"""
최근 30일 1H 5%+ 윗꼬리 짧은 양봉 트리거 후 t+1 ~ t+8 봉 동안
close > MA10 유지한 케이스 (= 추세 follow-through 살아남은 그룹).

각 트리거의 t+1 ~ t+20 변화율 + 현재 변화율 표시.
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
DAYS_BACK = 30
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
    print(f"window: {cutoff.tz_convert('Asia/Seoul')} ~ {last_dt.tz_convert('Asia/Seoul')} KST")

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
            # t+1 ~ t+8 모두 close > ma10
            held = True
            for k in range(1, HOLD_BARS + 1):
                j = i + k
                if not np.isfinite(ma10s[j]) or ma10s[j] <= 0 or closes[j] <= ma10s[j]:
                    held = False
                    break
            if not held:
                continue
            row = {
                "symbol": s,
                "ts_kst": df["ts"].iloc[i].tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
                "close": float(ec),
                "body_pct": float(body_pct.iloc[i] * 100),
                "wick": float(body_to_range.iloc[i]),
                "entry_close_to_ma10_pct": float((ec - em) / em * 100),
            }
            for k in range(1, FORWARD + 1):
                j = i + k
                if j < n:
                    cj = float(closes[j])
                    row[f"t+{k}_close"] = cj
                    row[f"t+{k}_pct"] = (cj - ec) / ec * 100
                else:
                    row[f"t+{k}_close"] = np.nan
                    row[f"t+{k}_pct"] = np.nan
            row["close_now"] = float(closes[-1])
            row["change_now_pct"] = (closes[-1] - ec) / ec * 100
            rows.append(row)

    df_out = pd.DataFrame(rows).sort_values("ts_kst", ascending=False).reset_index(drop=True)
    print(f"\nt+1~t+{HOLD_BARS} close > MA10 유지: {len(df_out)}건 / 고유 심볼 {df_out['symbol'].nunique() if len(df_out) else 0}")

    if len(df_out) == 0:
        return

    print("\n=== 통계 ===")
    for label, col in [("현재", "change_now_pct"), ("t+8", "t+8_pct"),
                       ("t+10", "t+10_pct"), ("t+15", "t+15_pct"), ("t+20", "t+20_pct")]:
        s = df_out[col].dropna()
        if len(s) == 0:
            continue
        print(f"  {label}변화율 (n={len(s)}): 평균 {s.mean():+.2f}%, 중앙값 {s.median():+.2f}%, "
              f"양수 {(s>0).sum()}/{len(s)} ({(s>0).mean()*100:.1f}%), "
              f"최대 {s.max():+.2f}, 최소 {s.min():+.2f}")

    show_cols = ["symbol", "ts_kst", "body_pct", "entry_close_to_ma10_pct",
                 "t+1_pct", "t+2_pct", "t+4_pct", "t+6_pct", "t+8_pct",
                 "t+10_pct", "t+15_pct", "t+20_pct", "change_now_pct"]
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 280)
    pd.set_option("display.max_rows", None)
    print(f"\n=== 변화율(%) — entry 대비, 시간 desc ===")
    print(df_out[show_cols].to_string(index=False, float_format=lambda x: f"{x:+.2f}" if isinstance(x, float) else x))

    df_out.to_csv(OUT_DIR / "pump_held_above_ma10_8bars_30d.csv", index=False)
    print(f"\nsaved → {OUT_DIR/'pump_held_above_ma10_8bars_30d.csv'}")


if __name__ == "__main__":
    main()
