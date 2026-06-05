"""
최근 30일간 5%+ 윗꼬리 짧은 양봉 트리거 카운트 + 최근 발생 리스트.

  base            : body>=5% & body/(high-open) > 0.9
  above_w20       : base + 주봉 MA20 위 (모든 거리)
  w20_band_0to10  : base + 주봉 MA20 위 0~10% 밴드 (추세 초입)
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
MA_N = 10
WEEKLY_MA_N = 20
W20_BAND_MAX = 0.10
DAYS_BACK = 30


def load_one(symbol):
    fp_1h = CACHE_1H / f"{symbol}.parquet"
    fp_1d = CACHE_1D / f"{symbol}.parquet"
    if not fp_1h.exists() or not fp_1d.exists():
        return None
    df_1h = pd.read_parquet(fp_1h).sort_values("timestamp").reset_index(drop=True)
    df_1d = pd.read_parquet(fp_1d).sort_values("timestamp").reset_index(drop=True)
    if len(df_1d) < WEEKLY_MA_N * 7 + 5:
        return None
    df_1h["ts"] = pd.to_datetime(df_1h["timestamp"], unit="ms", utc=True)
    df_1d["ts"] = pd.to_datetime(df_1d["timestamp"], unit="ms", utc=True)
    d = df_1d.set_index("ts")
    weekly_close = d["close"].resample("W-MON", closed="left", label="left").last()
    weekly_ma20 = weekly_close.rolling(WEEKLY_MA_N).mean().shift(1)
    h = df_1h.set_index("ts").sort_index()
    mapped = weekly_ma20.reindex(h.index, method="ffill")
    df = h.reset_index()
    df["weekly_ma20"] = mapped.values
    df["ma10"] = df["close"].rolling(MA_N).mean()
    return df


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
    print(f"data last bar: {last_dt.tz_convert('Asia/Seoul')} (KST)")
    print(f"cutoff (30d back): {cutoff.tz_convert('Asia/Seoul')} (KST)")
    print(f"universe: {len(symbols)} symbols")

    rows = []
    for s in symbols:
        try:
            df = load_one(s)
            if df is None:
                continue
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
            mask_base = (body_pct >= BODY_MIN) & (body_to_range > CLOSE_TO_HIGH_MIN)
            close_to_w20 = (df["close"] - df["weekly_ma20"]) / df["weekly_ma20"]
            mask_above = mask_base & (close_to_w20 > 0)
            mask_band = mask_above & (close_to_w20 <= W20_BAND_MAX)

            for label, mask in [
                ("base", mask_base),
                ("above_w20", mask_above),
                ("w20_band_0to10", mask_band),
            ]:
                for i in df.index[mask.fillna(False)].tolist():
                    v = close_to_w20.iloc[i]
                    rows.append({
                        "category": label,
                        "symbol": s,
                        "ts_utc": df["ts"].iloc[i],
                        "ts_kst": df["ts"].iloc[i].tz_convert("Asia/Seoul"),
                        "close": float(df["close"].iloc[i]),
                        "body_pct": float(body_pct.iloc[i] * 100),
                        "close_to_weekly_ma20_pct": (float(v * 100) if np.isfinite(v) else np.nan),
                    })
        except Exception as e:
            print(f"  skip {s}: {e}")

    df = pd.DataFrame(rows)

    summary_rows = []
    for cat, label in [
        ("base", "5%+ 윗꼬리 짧은 양봉 (전체)"),
        ("above_w20", "+ 주봉 MA20 위 (전체)"),
        ("w20_band_0to10", "+ 주봉 MA20 위 0~10% 밴드"),
    ]:
        sub = df[df["category"] == cat]
        summary_rows.append({
            "조건": label,
            "트리거_횟수": len(sub),
            "고유_심볼_수": int(sub["symbol"].nunique()),
        })
    sdf = pd.DataFrame(summary_rows)
    print("\n=== 표 1. 최근 30일 트리거 카운트 ===")
    print(sdf.to_string(index=False))

    band = df[df["category"] == "w20_band_0to10"].sort_values("ts_utc", ascending=False)
    print(f"\n=== 표 2. 주봉 MA20 위 0~10% 밴드 — 가장 최근 발생 (최대 20건) ===")
    if band.empty:
        print("  (없음)")
    else:
        show = band.head(20)[["symbol", "ts_kst", "close", "body_pct", "close_to_weekly_ma20_pct"]].copy()
        show["ts_kst"] = show["ts_kst"].dt.strftime("%Y-%m-%d %H:%M")
        print(show.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    df.to_csv(OUT_DIR / "pump_recent_30d_events.csv", index=False)
    print(f"\nsaved → {OUT_DIR/'pump_recent_30d_events.csv'} ({len(df)} rows)")


if __name__ == "__main__":
    main()
