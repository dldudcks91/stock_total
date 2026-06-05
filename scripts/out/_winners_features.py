"""
first_pump_after_quiet_168h.csv 의 51건 중 winners(OPN, MAGMA, HOME, APR) vs losers(47) 비교.

트리거 시점에 측정 가능한 사전 변수:
  - 거래대금 폭증 (trigger amount / 직전 N시간 평균)
  - 직전 168h 누적/최대/표준편차
  - 같은 1H 봉에 동시 발생 트리거 수 (burst)
  - 직전 168h 누적 수익률
  - 트리거 body / wick / breakout
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import numpy as np
import pandas as pd

CACHE = Path("data/cache/crypto/1h")
OUT_DIR = Path("scripts/out")
SRC = OUT_DIR / "first_pump_after_quiet_168h.csv"
WINNERS = {"OPNUSDT", "MAGMAUSDT", "HOMEUSDT", "APRUSDT"}


def amount_of(df: pd.DataFrame) -> pd.Series:
    if "amount" in df.columns:
        return df["amount"]
    return df["volume"] * df["close"]


def main():
    ev = pd.read_csv(SRC)
    rows = []
    for _, r in ev.iterrows():
        s = r["symbol"]
        fp = CACHE / f"{s}.parquet"
        if not fp.exists():
            continue
        df = pd.read_parquet(fp).sort_values("timestamp").reset_index(drop=True)
        df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        trg_kst = pd.Timestamp(r["ts_kst"]).tz_localize("Asia/Seoul")
        trg_utc = trg_kst.tz_convert("UTC")
        idx = df.index[df["ts"] == trg_utc]
        if len(idx) == 0:
            continue
        i = int(idx[0])
        if i < 168:
            continue

        amt = amount_of(df)
        trg_amt = float(amt.iloc[i])
        prev168_amt = amt.iloc[i - 168:i]
        prev24_amt = amt.iloc[i - 24:i]
        prev168_close = df["close"].iloc[i - 168:i]

        rows.append({
            "symbol": s,
            "ts_kst": r["ts_kst"],
            "winner": s in WINNERS,
            "body_pct": r["body_pct"],
            "wick": r["wick_ratio"],
            "breakout_pct": r["breakout_pct"],
            "trg_amount_USD": trg_amt,
            "vol_surge_24h_x": trg_amt / prev24_amt.mean() if prev24_amt.mean() > 0 else np.nan,
            "vol_surge_168h_x": trg_amt / prev168_amt.mean() if prev168_amt.mean() > 0 else np.nan,
            "trg_vs_max_168h_x": trg_amt / prev168_amt.max() if prev168_amt.max() > 0 else np.nan,
            "p168_amount_sum_USD": float(prev168_amt.sum()),
            "p168_close_cv": float(prev168_close.std() / prev168_close.mean()) if prev168_close.mean() > 0 else np.nan,
            "p168_cum_ret_pct": float((df["close"].iloc[i] - prev168_close.iloc[0]) / prev168_close.iloc[0] * 100),
            "change_now_pct": r["change_now_pct"],
        })

    ev_x = pd.DataFrame(rows)
    burst = ev_x.groupby("ts_kst").size().reset_index(name="burst_count")
    ev_x = ev_x.merge(burst, on="ts_kst")

    w = ev_x[ev_x["winner"]]
    l = ev_x[~ev_x["winner"]]

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 240)

    print(f"=== 표 1. winners(n={len(w)}) 개별 값 ===")
    cols_w = ["symbol", "ts_kst", "change_now_pct", "body_pct", "wick",
              "vol_surge_24h_x", "vol_surge_168h_x", "trg_vs_max_168h_x",
              "burst_count", "p168_cum_ret_pct", "trg_amount_USD"]
    print(w[cols_w].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

    metrics = ["body_pct", "wick", "breakout_pct",
               "vol_surge_24h_x", "vol_surge_168h_x", "trg_vs_max_168h_x",
               "burst_count", "p168_cum_ret_pct", "p168_close_cv",
               "trg_amount_USD", "p168_amount_sum_USD"]

    summary = []
    for m in metrics:
        summary.append({
            "변수": m,
            "winners_평균": w[m].mean(),
            "winners_중앙값": w[m].median(),
            "losers_평균": l[m].mean(),
            "losers_중앙값": l[m].median(),
            "비율(W/L_중앙값)": (w[m].median() / l[m].median()) if l[m].median() != 0 else np.nan,
        })
    sdf = pd.DataFrame(summary)
    print(f"\n=== 표 2. 변수별 winners vs losers 비교 (n_w={len(w)}, n_l={len(l)}) ===")
    print(sdf.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    ev_x.to_csv(OUT_DIR / "first_pump_features.csv", index=False)
    sdf.to_csv(OUT_DIR / "first_pump_features_summary.csv", index=False)
    print(f"\nsaved → {OUT_DIR/'first_pump_features.csv'}")
    print(f"saved → {OUT_DIR/'first_pump_features_summary.csv'}")


if __name__ == "__main__":
    main()
