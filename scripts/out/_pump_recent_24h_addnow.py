"""
pump_recent_24h_all.csv 후처리: 현재가격(데이터 마지막 1H close) 과 차이 추가.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import pandas as pd

CACHE = Path("data/cache/crypto/1h")
OUT_DIR = Path("scripts/out")
SRC = OUT_DIR / "pump_recent_24h_all.csv"


def last_close(s: str) -> float:
    fp = CACHE / f"{s}.parquet"
    return float(pd.read_parquet(fp, columns=["close"])["close"].iloc[-1])


def main():
    df = pd.read_csv(SRC)
    df["close_now"] = [last_close(s) for s in df["symbol"]]
    df["change_now_pct"] = (df["close_now"] - df["close"]) / df["close"] * 100.0

    df_sorted = df.sort_values("ts_kst", ascending=False).reset_index(drop=True)
    out = OUT_DIR / "pump_recent_24h_with_now.csv"
    df_sorted.to_csv(out, index=False)

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", None)
    print(f"전체 {len(df_sorted)}건 (시간 desc):\n")
    print(df_sorted[["symbol", "ts_kst", "close", "close_now", "change_now_pct",
                     "body_pct", "body_to_range"]].to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    print("\n=== 분포 (전체 {0}건) ===".format(len(df_sorted)))
    s = df_sorted["change_now_pct"]
    print(f"  평균: {s.mean():+.3f}%   중앙값: {s.median():+.3f}%")
    print(f"  양수: {(s > 0).sum()}/{len(s)} ({(s > 0).mean()*100:.1f}%)")
    print(f"  P10: {s.quantile(0.10):+.3f}  P25: {s.quantile(0.25):+.3f}  P75: {s.quantile(0.75):+.3f}  P90: {s.quantile(0.90):+.3f}")
    print(f"  최대: {s.max():+.3f}%   최소: {s.min():+.3f}%")

    print(f"\nsaved → {out}")


if __name__ == "__main__":
    main()
