"""
"평탄(횡보) → 첫 5%+ 양봉 박차고" 패턴 검출.

Step 1: OPN 의 첫 트리거 (06-03 22:00 KST) 직전 N봉(24/48/72/168시간)의 close range 측정.
Step 2: 같은 정의로 최근 7일간 universe scan.

조건 (Step 2):
  - 5%+ 윗꼬리 짧은 양봉 (B 정의)
  - 직전 N시간 close 의 (max-min)/min <= RANGE_MAX  (= 평탄)
  - 트리거 close > 직전 N시간 max close  (= 베이스 상단 돌파)
  - 직전 N시간 안에 또 다른 5%+ 양봉 *없음*  (= "첫" 박차고)
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

# ─── Step 1: OPN 사전 진단 ───
def opn_debug():
    fp = CACHE / "OPNUSDT.parquet"
    df = pd.read_parquet(fp).sort_values("timestamp").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    trg_utc = pd.Timestamp("2026-06-03 22:00", tz="Asia/Seoul").tz_convert("UTC")
    idx = df.index[df["ts"] == trg_utc]
    if len(idx) == 0:
        print("OPN 06-03 22:00 KST 봉 못 찾음.")
        return None
    i = int(idx[0])
    c = df["close"].iloc[i]
    o = df["open"].iloc[i]
    h = df["high"].iloc[i]
    body_pct = (c - o) / o * 100
    print(f"=== Step 1. OPN 06-03 22:00 KST 트리거 사전 진단 ===")
    print(f"  트리거 body: {body_pct:+.2f}%, close: {c:.4f}, wick_ratio: {(c-o)/(h-o):.2f}")
    for N in [24, 48, 72, 168]:
        prev = df.iloc[max(0, i - N):i]
        if prev.empty:
            continue
        pmin = prev["close"].min()
        pmax = prev["close"].max()
        rng = (pmax - pmin) / pmin * 100
        body_prev = (prev["close"] - prev["open"]) / prev["open"]
        n5pct = int((body_prev >= 0.05).sum())
        print(f"  직전 {N:3d}h: close range {rng:6.2f}%, max {pmax:.4f}, 트리거> max? {c > pmax}, 그 안 5%+ 양봉 수 {n5pct}")
    print()


# ─── Step 2: universe scan ───
def scan(lookback: int, range_max: float, label: str):
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
        if len(df) < lookback + 24:
            continue

        body = df["close"] - df["open"]
        upper = df["high"] - df["open"]
        body_pct = body / df["open"]
        body_to_range = pd.Series(
            np.where(upper > 0, body / upper.replace(0, np.nan), np.nan),
            index=df.index,
        )
        mask_pump = (body_pct >= BODY_MIN) & (body_to_range > CLOSE_TO_HIGH_MIN)
        mask_time = df["ts"] >= cutoff

        idx_list = df.index[mask_pump & mask_time].tolist()
        for i in idx_list:
            if i < lookback:
                continue
            prev = df.iloc[i - lookback:i]
            pmin = prev["close"].min()
            pmax = prev["close"].max()
            if pmin <= 0:
                continue
            rng = (pmax - pmin) / pmin
            c = df["close"].iloc[i]
            # 평탄 + 베이스 상단 돌파
            if rng > range_max:
                continue
            if c <= pmax:
                continue
            # 직전 lookback 안에 다른 5%+ 양봉 없어야 (첫 박차고)
            body_prev = (prev["close"] - prev["open"]) / prev["open"]
            if (body_prev >= 0.05).any():
                continue
            rows.append({
                "symbol": s,
                "ts_kst": df["ts"].iloc[i].tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
                "close": float(c),
                "body_pct": float(body_pct.iloc[i] * 100),
                "prev_range_pct": float(rng * 100),
                "breakout_pct": float((c - pmax) / pmax * 100),
                "prev_max": float(pmax),
            })

    df_out = pd.DataFrame(rows).sort_values("ts_kst", ascending=False).reset_index(drop=True)
    # 현재가격
    if not df_out.empty:
        nows = []
        for s in df_out["symbol"]:
            fpx = CACHE / f"{s}.parquet"
            nows.append(float(pd.read_parquet(fpx, columns=["close"])["close"].iloc[-1]))
        df_out["close_now"] = nows
        df_out["change_now_pct"] = (df_out["close_now"] - df_out["close"]) / df_out["close"] * 100.0

    print(f"=== {label}: lookback={lookback}h, range<={range_max*100:.0f}% — {len(df_out)}건 ===")
    if not df_out.empty:
        show = df_out[["symbol", "ts_kst", "close", "close_now", "change_now_pct",
                       "body_pct", "prev_range_pct", "breakout_pct"]]
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 260)
        pd.set_option("display.max_rows", None)
        print(show.to_string(index=False, float_format=lambda x: f"{x:+.2f}" if isinstance(x, float) else x))
    print()
    df_out.to_csv(OUT_DIR / f"breakout_from_flat_{lookback}h_r{int(range_max*100)}.csv", index=False)


def main():
    opn_debug()
    # 여러 정의 비교 (느슨 → 빡빡)
    scan(48, 0.15, "정의 1 (가장 느슨)")
    scan(48, 0.10, "정의 2 (OPN 디버그 따라)")
    scan(72, 0.12, "정의 3 (좀 더 긴 베이스)")
    scan(168, 0.20, "정의 4 (1주일 베이스)")


if __name__ == "__main__":
    main()
