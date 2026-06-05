"""
2026-06-04 06:00 KST 의 5%+ 양봉 트리거 전체 + t+1~t+10 종가/변화율.

데이터 마지막 봉이 2026-06-04 10:00 KST 이므로 t+5 이후는 N/A.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import numpy as np
import pandas as pd

CACHE = Path("data/cache/crypto/1h")
OUT_DIR = Path("scripts/out")
BODY_MIN = 0.05
FORWARD = 10
TRIGGER_TS_UTC = pd.Timestamp("2026-06-04 06:00", tz="Asia/Seoul").tz_convert("UTC")


def main():
    rows = []
    for fp in sorted(CACHE.glob("*.parquet")):
        s = fp.stem
        df = pd.read_parquet(fp).sort_values("timestamp").reset_index(drop=True)
        df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        sel = df.index[df["ts"] == TRIGGER_TS_UTC]
        if len(sel) == 0:
            continue
        i = int(sel[0])
        o = float(df["open"].iloc[i])
        h = float(df["high"].iloc[i])
        c = float(df["close"].iloc[i])
        body_pct = (c - o) / o
        if body_pct < BODY_MIN:
            continue
        wick = (c - o) / (h - o) if h > o else np.nan

        row = {"symbol": s, "close": c, "body_pct": body_pct * 100,
               "wick_ratio": wick if np.isfinite(wick) else np.nan}
        for k in range(1, FORWARD + 1):
            j = i + k
            if j < len(df):
                cj = float(df["close"].iloc[j])
                row[f"t+{k}_close"] = cj
                row[f"t+{k}_pct"] = (cj - c) / c * 100.0
            else:
                row[f"t+{k}_close"] = np.nan
                row[f"t+{k}_pct"] = np.nan
        rows.append(row)

    df = pd.DataFrame(rows).sort_values("body_pct", ascending=False).reset_index(drop=True)
    print(f"2026-06-04 06:00 KST — body>=5% 트리거: {len(df)}개")
    print(f"  (이 중 윗꼬리 짧음 (wick>0.9) 만족: {(df['wick_ratio']>0.9).sum()}개)")

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 320)

    def fmt_price(x):
        if not np.isfinite(x): return "N/A"
        if abs(x) < 0.01: return f"{x:.6f}"
        if abs(x) < 100: return f"{x:.4f}"
        return f"{x:.2f}"

    def fmt_pct(x):
        return "N/A" if not np.isfinite(x) else f"{x:+.2f}"

    price_cols = ["symbol", "close"] + [f"t+{k}_close" for k in range(1, FORWARD + 1)]
    print("\n=== 종가 (t+5 이후는 N/A — 데이터 없음) ===")
    print(df[price_cols].to_string(index=False, formatters={c: fmt_price for c in price_cols if c != "symbol"}))

    pct_cols = ["symbol", "body_pct", "wick_ratio"] + [f"t+{k}_pct" for k in range(1, FORWARD + 1)]
    print("\n=== 변화율 (entry 대비 %) ===")
    print(df[pct_cols].to_string(index=False, formatters={
        "body_pct": lambda x: f"{x:+.2f}",
        "wick_ratio": lambda x: f"{x:.2f}",
        **{c: fmt_pct for c in pct_cols if c.startswith("t+")},
    }))

    df.to_csv(OUT_DIR / "pump_2026-06-04_06_fwd10.csv", index=False)
    print(f"\nsaved → {OUT_DIR/'pump_2026-06-04_06_fwd10.csv'}")


if __name__ == "__main__":
    main()
