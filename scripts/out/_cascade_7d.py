"""
"OPN 류 캐스케이드 펌프" — 최근 7일 동안 같은 심볼에서 1H 5%+ 양봉이 여러 번 발생한 종목.

지표:
  - 7일 트리거 횟수 (A=body>=5% / B=+윗꼬리>0.9)
  - 7일 종가 변화율 (캐시 7일 전 close 대비 현재 close)
  - 최대 1H body 봉
  - 첫/마지막 트리거 시간
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
MIN_TRIGGERS_A = 2  # 일단 2회 이상 발생 종목만 보기


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
    print(f"window: {cutoff.tz_convert('Asia/Seoul')} ~ {last_dt.tz_convert('Asia/Seoul')} KST (7d)")

    rows = []
    for fp in sorted(CACHE.glob("*.parquet")):
        s = fp.stem
        df = pd.read_parquet(fp).sort_values("timestamp").reset_index(drop=True)
        df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        sub = df[df["ts"] >= cutoff].reset_index(drop=True)
        if len(sub) < 24:
            continue
        body = sub["close"] - sub["open"]
        upper = sub["high"] - sub["open"]
        body_pct = body / sub["open"]
        body_to_range = pd.Series(
            np.where(upper > 0, body / upper.replace(0, np.nan), np.nan),
            index=sub.index,
        )
        mask_a = body_pct >= BODY_MIN
        mask_b = mask_a & (body_to_range > CLOSE_TO_HIGH_MIN)

        n_a = int(mask_a.sum())
        n_b = int(mask_b.sum())
        if n_a < MIN_TRIGGERS_A:
            continue

        close_then = float(sub["close"].iloc[0])
        close_now = float(sub["close"].iloc[-1])
        pct_7d = (close_now - close_then) / close_then * 100.0
        max_body = float(body_pct.max() * 100)

        idxs = sub.index[mask_a].tolist()
        first_ts = sub["ts"].iloc[idxs[0]].tz_convert("Asia/Seoul").strftime("%m-%d %H:%M")
        last_ts_s = sub["ts"].iloc[idxs[-1]].tz_convert("Asia/Seoul").strftime("%m-%d %H:%M")

        # 가장 가까운 트리거 두 개 사이 시간 (조밀도 지표)
        if len(idxs) >= 2:
            gaps = np.diff(idxs)
            min_gap_hours = int(gaps.min())
        else:
            min_gap_hours = -1

        rows.append({
            "symbol": s,
            "트리거_A": n_a,
            "트리거_B": n_b,
            "7일변화_%": pct_7d,
            "최대body_%": max_body,
            "최소간격_h": min_gap_hours,
            "첫_트리거": first_ts,
            "마지막_트리거": last_ts_s,
            "현재_close": close_now,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        print("\n조건 만족 종목 없음.")
        return

    df = df.sort_values(["7일변화_%", "트리거_A"], ascending=False).reset_index(drop=True)

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 240)
    pd.set_option("display.max_rows", None)

    print(f"\n=== 최근 7일 트리거 2회 이상 종목 (총 {len(df)}개, 7일 변화율 큰 순) ===")
    show_cols = ["symbol", "트리거_A", "트리거_B", "7일변화_%", "최대body_%", "최소간격_h", "첫_트리거", "마지막_트리거"]
    print(df[show_cols].head(40).to_string(index=False, float_format=lambda x: f"{x:+.2f}" if abs(x) < 10000 else f"{x:.4f}"))

    # OPN 류 = 트리거 횟수 많고 누적 변화율 큰 케이스
    opn_like = df[(df["트리거_A"] >= 3) & (df["7일변화_%"] >= 30)].reset_index(drop=True)
    print(f"\n=== OPN 류 캐스케이드 (3회+ 트리거 & 7일 변화 ≥ +30%) — 총 {len(opn_like)}개 ===")
    if not opn_like.empty:
        print(opn_like[show_cols].to_string(index=False, float_format=lambda x: f"{x:+.2f}" if abs(x) < 10000 else f"{x:.4f}"))

    df.to_csv(OUT_DIR / "pump_cascade_7d.csv", index=False)
    opn_like.to_csv(OUT_DIR / "pump_cascade_7d_opn_like.csv", index=False)
    print(f"\nsaved → {OUT_DIR/'pump_cascade_7d.csv'}")
    print(f"saved → {OUT_DIR/'pump_cascade_7d_opn_like.csv'}")


if __name__ == "__main__":
    main()
