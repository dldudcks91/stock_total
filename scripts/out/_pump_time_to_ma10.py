"""
5%+ 윗꼬리 짧은 장대양봉(트리거) 후, 종가가 처음으로 MA10에 닿기까지 (close <= MA10) 걸리는 봉 수 분포.

모집단:
  (A) 전체 트리거 (body >= 5%, body/(high-open) > 0.9)
  (B) (A) + 주봉 MA20 위 0~10% 밴드

룩어헤드 한계: MAX = 480봉 (20일). 그 안에 안 닿으면 censored.
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
MAX_LOOKAHEAD = 480  # 20일


def load_one(symbol: str):
    fp_1h = CACHE_1H / f"{symbol}.parquet"
    fp_1d = CACHE_1D / f"{symbol}.parquet"
    if not fp_1h.exists() or not fp_1d.exists():
        return None
    df_1h = pd.read_parquet(fp_1h).sort_values("timestamp").reset_index(drop=True)
    df_1d = pd.read_parquet(fp_1d).sort_values("timestamp").reset_index(drop=True)
    if len(df_1h) < MA_N + MAX_LOOKAHEAD or len(df_1d) < WEEKLY_MA_N * 7 + 5:
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


def find_events(symbol: str):
    df = load_one(symbol)
    if df is None:
        return [], []
    body = df["close"] - df["open"]
    upper = df["high"] - df["open"]
    body_pct = body / df["open"]
    body_to_range = pd.Series(
        np.where(upper > 0, body / upper.replace(0, np.nan), np.nan),
        index=df.index,
    )
    mask_base = (body_pct >= BODY_MIN) & (body_to_range > CLOSE_TO_HIGH_MIN)
    close_to_w20 = (df["close"] - df["weekly_ma20"]) / df["weekly_ma20"]
    mask_band = mask_base & (close_to_w20 > 0) & (close_to_w20 <= W20_BAND_MAX)

    closes = df["close"].values
    ma10s = df["ma10"].values
    n = len(df)

    def collect(mask):
        out = []
        for i in df.index[mask.fillna(False)].tolist():
            ec = closes[i]
            em = ma10s[i]
            if not (np.isfinite(em) and em > 0 and ec > em):
                continue  # 트리거 시점 종가가 MA10 위라는 전제만
            end = min(n, i + 1 + MAX_LOOKAHEAD)
            touched = -1
            for j in range(i + 1, end):
                m = ma10s[j]
                if not np.isfinite(m) or m <= 0:
                    continue
                if closes[j] <= m:
                    touched = j - i
                    break
            out.append(touched)
        return out

    return collect(mask_base), collect(mask_band)


def summarize(name: str, vals: list[int]):
    n_all = len(vals)
    arr = np.array(vals)
    censored = int((arr == -1).sum())
    touched = arr[arr > 0]
    n_touched = len(touched)
    if n_touched == 0:
        return {
            "모집단": name, "트리거_수": n_all, "닿은_비율_퍼센트": 0.0,
            "평균_봉수": np.nan, "중앙값_봉수": np.nan,
            "P25_봉수": np.nan, "P75_봉수": np.nan,
            "censored_봉수480초과": censored,
        }
    return {
        "모집단": name,
        "트리거_수": n_all,
        "닿은_비율_퍼센트": float(n_touched / n_all * 100.0),
        "평균_봉수": float(touched.mean()),
        "중앙값_봉수": float(np.median(touched)),
        "P25_봉수": float(np.percentile(touched, 25)),
        "P75_봉수": float(np.percentile(touched, 75)),
        "censored_봉수480초과": censored,
    }


def hist_bins(vals: list[int], name: str):
    arr = np.array(vals)
    touched = arr[arr > 0]
    bins = [(1, 1), (2, 3), (4, 6), (7, 10), (11, 20), (21, 50), (51, 120), (121, 480)]
    row = {"모집단": name}
    for lo, hi in bins:
        if lo == hi:
            key = f"{lo}봉"
        else:
            key = f"{lo}~{hi}봉"
        cnt = int(((touched >= lo) & (touched <= hi)).sum())
        pct = cnt / len(arr) * 100.0 if len(arr) else 0.0
        row[f"{key}_퍼센트"] = round(pct, 2)
    row["480봉이내_안닿음_퍼센트"] = round((arr == -1).sum() / len(arr) * 100.0, 2) if len(arr) else 0.0
    return row


def main():
    symbols = sorted(p.stem for p in CACHE_1H.glob("*.parquet"))
    print(f"universe: {len(symbols)} symbols")

    all_base, all_band = [], []
    for s in symbols:
        try:
            b, w = find_events(s)
            all_base.extend(b)
            all_band.extend(w)
        except Exception as e:
            print(f"  skip {s}: {e}")

    summary_rows = [
        summarize("전체 트리거", all_base),
        summarize("주봉 MA20 위 0~10% 밴드", all_band),
    ]
    sdf = pd.DataFrame(summary_rows)
    sdf.to_csv(OUT_DIR / "pump_time_to_ma10_summary.csv", index=False)
    print("\n=== 표 1. MA10 첫 터치까지 걸리는 봉 수 (요약) ===")
    print(sdf.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    hist_rows = [
        hist_bins(all_base, "전체 트리거"),
        hist_bins(all_band, "주봉 MA20 위 0~10% 밴드"),
    ]
    hdf = pd.DataFrame(hist_rows)
    hdf.to_csv(OUT_DIR / "pump_time_to_ma10_histogram.csv", index=False)
    print("\n=== 표 2. 첫 터치까지 봉 수의 분포 (% 비율) ===")
    print(hdf.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    print(f"\nsaved → {OUT_DIR/'pump_time_to_ma10_summary.csv'}")
    print(f"saved → {OUT_DIR/'pump_time_to_ma10_histogram.csv'}")


if __name__ == "__main__":
    main()
