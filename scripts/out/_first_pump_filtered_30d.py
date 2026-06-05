"""
최근 30일 "진짜 시작점" 필터 검증.

기본 조건 (1주일 quiet):
  - 트리거: body>=5% & wick>0.9
  - 직전 168h 동안 body>=5% 양봉 0개

추가 필터 (winners vs losers 비교에서 도출):
  - burst_count = 1 (같은 1H 봉에 다른 트리거 없음)
  - 직전 168h 누적 수익률 >= 5% (조용한 step-up)
  - breakout_pct >= 2% (베이스 상단 돌파)

산출:
  - 통과 트리거 + t+24h / t+72h / t+168h forward 변화율 + 현재 변화율
  - 통계 + 개별 리스트
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
QUIET_HOURS = 168
DAYS_BACK = 30
CUM_RET_MIN = 0.05
BREAKOUT_MIN = 0.02


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

    # cache df per symbol (재사용)
    sym_dfs = {}
    all_rows = []
    for fp in sorted(CACHE.glob("*.parquet")):
        s = fp.stem
        df = pd.read_parquet(fp).sort_values("timestamp").reset_index(drop=True)
        df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        if len(df) < QUIET_HOURS + 24:
            continue
        sym_dfs[s] = df

        body = df["close"] - df["open"]
        upper = df["high"] - df["open"]
        body_pct = body / df["open"]
        body_to_range = pd.Series(np.where(upper > 0, body / upper.replace(0, np.nan), np.nan), index=df.index)
        mask_pump = (body_pct >= BODY_MIN) & (body_to_range > WICK_MIN)
        big_up_cnt = (body_pct >= BODY_MIN).rolling(QUIET_HOURS, closed="left").sum()
        mask_quiet = big_up_cnt == 0
        mask_time = df["ts"] >= cutoff
        full = mask_pump & mask_quiet & mask_time

        for i in df.index[full.fillna(False)].tolist():
            if i < QUIET_HOURS:
                continue
            prev = df.iloc[i - QUIET_HOURS:i]
            pmax = prev["close"].max()
            pstart = prev["close"].iloc[0]
            if pmax <= 0 or pstart <= 0:
                continue
            all_rows.append({
                "symbol": s,
                "ts": df["ts"].iloc[i],
                "i": int(i),
                "close": float(df["close"].iloc[i]),
                "body_pct": float(body_pct.iloc[i] * 100),
                "wick": float(body_to_range.iloc[i]),
                "p168_cum_ret_pct": float((df["close"].iloc[i] - pstart) / pstart * 100),
                "breakout_pct": float((df["close"].iloc[i] - pmax) / pmax * 100),
            })

    ev = pd.DataFrame(all_rows)
    if ev.empty:
        print("\n트리거 0건.")
        return

    burst = ev.groupby("ts").size().reset_index(name="burst_count")
    ev = ev.merge(burst, on="ts")

    n_total = len(ev)
    m1 = ev["burst_count"] == 1
    m2 = m1 & (ev["p168_cum_ret_pct"] >= CUM_RET_MIN * 100)
    m3 = m2 & (ev["breakout_pct"] >= BREAKOUT_MIN * 100)
    print(f"\n=== 필터 단계별 카운트 ===")
    print(f"  (1) 1주일 quiet 트리거 전체     : {n_total}")
    print(f"  (2) + burst_count = 1           : {int(m1.sum())}")
    print(f"  (3) + 누적 수익률 ≥ +5%         : {int(m2.sum())}")
    print(f"  (4) + breakout ≥ +2%            : {int(m3.sum())}")

    filt = ev[m3].copy().sort_values("ts").reset_index(drop=True)

    # fwd & now
    fwd_h = [24, 72, 168]
    for h in fwd_h:
        filt[f"fwd_t+{h}h_pct"] = np.nan
    filt["close_now"] = np.nan
    filt["change_now_pct"] = np.nan

    for r_i in range(len(filt)):
        s = filt.at[r_i, "symbol"]
        i = int(filt.at[r_i, "i"])
        c0 = float(filt.at[r_i, "close"])
        df = sym_dfs[s]
        for h in fwd_h:
            if i + h < len(df):
                cj = float(df["close"].iloc[i + h])
                filt.at[r_i, f"fwd_t+{h}h_pct"] = (cj - c0) / c0 * 100
        filt.at[r_i, "close_now"] = float(df["close"].iloc[-1])
        filt.at[r_i, "change_now_pct"] = (df["close"].iloc[-1] - c0) / c0 * 100

    filt["ts_kst"] = filt["ts"].dt.tz_convert("Asia/Seoul").dt.strftime("%Y-%m-%d %H:%M")
    filt = filt.sort_values("ts", ascending=False).reset_index(drop=True)

    print(f"\n=== 최종 필터 통과 {len(filt)}건 ===")
    show = filt[["symbol", "ts_kst", "close", "close_now", "change_now_pct",
                 "fwd_t+24h_pct", "fwd_t+72h_pct", "fwd_t+168h_pct",
                 "body_pct", "p168_cum_ret_pct", "breakout_pct"]]
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 280)
    pd.set_option("display.max_rows", None)
    print(show.to_string(index=False, float_format=lambda x: f"{x:+.2f}" if isinstance(x, float) else x))

    print(f"\n=== 통계 ===")
    for col in ["change_now_pct", "fwd_t+24h_pct", "fwd_t+72h_pct", "fwd_t+168h_pct"]:
        s = filt[col].dropna()
        if len(s) == 0:
            continue
        print(f"  {col} (n={len(s)}): 평균 {s.mean():+.2f}%, 중앙값 {s.median():+.2f}%, "
              f"양수 {(s > 0).sum()}/{len(s)} ({(s > 0).mean()*100:.1f}%), "
              f"P25 {s.quantile(0.25):+.2f}, P75 {s.quantile(0.75):+.2f}, 최대 {s.max():+.2f}, 최소 {s.min():+.2f}")

    # 비교용: 필터 안 한 1주일 quiet 전체의 t+168h 통계
    base = ev.copy()
    base_fwd = []
    for _, r in base.iterrows():
        s = r["symbol"]
        i = int(r["i"])
        c0 = r["close"]
        df = sym_dfs[s]
        for h in fwd_h:
            if i + h < len(df):
                base_fwd.append({"col": f"fwd_t+{h}h_pct", "val": (df["close"].iloc[i + h] - c0) / c0 * 100})
    bdf = pd.DataFrame(base_fwd)
    print(f"\n=== 비교: 필터 미적용 (1주일 quiet 전체 n={n_total}) ===")
    for h in fwd_h:
        s = bdf[bdf["col"] == f"fwd_t+{h}h_pct"]["val"]
        if len(s):
            print(f"  fwd_t+{h}h_pct (n={len(s)}): 평균 {s.mean():+.2f}%, 중앙값 {s.median():+.2f}%, 양수 {(s > 0).mean()*100:.1f}%")

    filt.to_csv(OUT_DIR / "first_pump_filtered_30d.csv", index=False)
    print(f"\nsaved → {OUT_DIR/'first_pump_filtered_30d.csv'}")


if __name__ == "__main__":
    main()
