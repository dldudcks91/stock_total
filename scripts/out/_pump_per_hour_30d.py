"""
최근 30일 동안 1H 봉당 트리거 발생 수 분포.
  (A) body >= 5%
  (B) + 윗꼬리 짧음(>0.9)
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
DAYS_BACK = 30


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
            rows_a.append({"symbol": s, "ts": df["ts"].iloc[i]})
            if mask_b.iloc[i]:
                rows_b.append({"symbol": s, "ts": df["ts"].iloc[i]})

    da = pd.DataFrame(rows_a)
    db = pd.DataFrame(rows_b)

    # 1H 봉 단위 카운트 (UTC ts 기준)
    grid_start = cutoff.ceil("h")
    grid_end = last_dt.floor("h")
    all_hours = pd.date_range(grid_start, grid_end, freq="h", tz="UTC")

    ca = da.groupby("ts").size().reindex(all_hours, fill_value=0)
    cb = db.groupby("ts").size().reindex(all_hours, fill_value=0)

    def stats(name, c, total):
        return {
            "정의": name,
            "총_트리거": int(total),
            "시간_수": len(c),
            "시간당_평균": float(c.mean()),
            "시간당_중앙값": float(c.median()),
            "시간당_최대": int(c.max()),
            "0건_시간_비율_%": float((c == 0).mean() * 100),
            "1건이상_시간_비율_%": float((c >= 1).mean() * 100),
            "5건이상_시간_비율_%": float((c >= 5).mean() * 100),
            "10건이상_시간_비율_%": float((c >= 10).mean() * 100),
        }

    sdf = pd.DataFrame([
        stats("(A) body>=5%", ca, len(da)),
        stats("(B) + 윗꼬리 짧음", cb, len(db)),
    ])
    print("\n=== 표 1. 1H 봉당 트리거 수 분포 (최근 30일, " + f"{len(all_hours)}시간) ===")
    print(sdf.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    # 시간별 발생 (KST hour 0~23) 평균
    def by_hour(events):
        if events.empty:
            return pd.Series(dtype=float)
        kst_hour = events["ts"].dt.tz_convert("Asia/Seoul").dt.hour
        per_hour = kst_hour.value_counts().sort_index()
        days = DAYS_BACK
        return (per_hour / days).reindex(range(24), fill_value=0)

    ha = by_hour(da)
    hb = by_hour(db)
    hdf = pd.DataFrame({
        "KST_시간": list(range(24)),
        "(A)_시간당_평균_트리거": ha.values,
        "(B)_시간당_평균_트리거": hb.values,
    })
    print("\n=== 표 2. KST 시간대(0~23)별 1H 봉당 평균 트리거 수 ===")
    print(hdf.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    # 가장 많이 발생한 1H 봉 상위 10개
    top_a = ca.nlargest(10)
    print("\n=== 표 3. (A) 가장 많이 발생한 1H 봉 상위 10개 (KST) ===")
    show = pd.DataFrame({
        "ts_kst": top_a.index.tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
        "트리거_수": top_a.values,
    })
    print(show.to_string(index=False))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sdf.to_csv(OUT_DIR / "pump_per_hour_30d_summary.csv", index=False)
    hdf.to_csv(OUT_DIR / "pump_per_hour_30d_by_kst_hour.csv", index=False)
    pd.DataFrame({"ts_utc": ca.index, "count_A": ca.values, "count_B": cb.values}).to_csv(
        OUT_DIR / "pump_per_hour_30d_hourly.csv", index=False
    )
    print(f"\nsaved → {OUT_DIR/'pump_per_hour_30d_summary.csv'}")
    print(f"saved → {OUT_DIR/'pump_per_hour_30d_by_kst_hour.csv'}")
    print(f"saved → {OUT_DIR/'pump_per_hour_30d_hourly.csv'}")


if __name__ == "__main__":
    main()
