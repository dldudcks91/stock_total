"""
최근 24시간 1H 봉 기준 5%+ 양봉 카운트.
  (A) body >= 5% (윗꼬리 조건 없음)
  (B) body >= 5% + body/(high-open) > 0.9 (윗꼬리 짧음 = 우리 지금까지의 정의)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import numpy as np
import pandas as pd

CACHE = Path("data/cache/crypto/1h")
BODY_MIN = 0.05
CLOSE_TO_HIGH_MIN = 0.9

last_ts = None
for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]:
    fp = CACHE / f"{s}.parquet"
    if fp.exists():
        m = pd.read_parquet(fp, columns=["timestamp"])["timestamp"].max()
        if last_ts is None or m > last_ts:
            last_ts = m
last_dt = pd.to_datetime(last_ts, unit="ms", utc=True)
cutoff = last_dt - pd.Timedelta(hours=24)
print(f"window: {cutoff.tz_convert('Asia/Seoul')} ~ {last_dt.tz_convert('Asia/Seoul')} KST (24h)")

rows_a, rows_b = [], []
for fp in sorted(CACHE.glob("*.parquet")):
    s = fp.stem
    df = pd.read_parquet(fp).sort_values("timestamp")
    df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df[df["ts"] >= cutoff].reset_index(drop=True)
    if df.empty:
        continue
    body = df["close"] - df["open"]
    upper = df["high"] - df["open"]
    body_pct = body / df["open"]
    body_to_range = pd.Series(
        np.where(upper > 0, body / upper.replace(0, np.nan), np.nan),
        index=df.index,
    )
    mask_a = body_pct >= BODY_MIN
    mask_b = mask_a & (body_to_range > CLOSE_TO_HIGH_MIN)

    for i in df.index[mask_a.fillna(False)].tolist():
        r = {
            "symbol": s,
            "ts_kst": df["ts"].iloc[i].tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
            "close": float(df["close"].iloc[i]),
            "body_pct": float(body_pct.iloc[i] * 100),
            "body_to_range": float(body_to_range.iloc[i]) if np.isfinite(body_to_range.iloc[i]) else np.nan,
        }
        rows_a.append(r)
        if mask_b.iloc[i]:
            rows_b.append(r)

print(f"\n(A) body >= 5%        : {len(rows_a)} 트리거 / {len({r['symbol'] for r in rows_a})} 심볼")
print(f"(B) + 윗꼬리 짧음(>0.9): {len(rows_b)} 트리거 / {len({r['symbol'] for r in rows_b})} 심볼")

if rows_a:
    a = pd.DataFrame(rows_a).sort_values(["ts_kst", "body_pct"], ascending=[False, False])
    print(f"\n=== (A) body >= 5% 전체 ({len(a)}건) ===")
    print(a.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    out = Path("scripts/out/pump_recent_24h_all.csv")
    a.to_csv(out, index=False)
    print(f"\nsaved → {out}")
