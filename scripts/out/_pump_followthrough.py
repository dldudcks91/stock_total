"""
1시간봉 장대양봉 follow-through 분석.

트리거:
  - (close - open) / open >= 0.05  (5% 이상 상승)
  - (close - open) / (high - open) > 0.9  (윗꼬리 짧음 = 강한 양봉)

산출:
  - 다음 10봉 종가 변화율 평균/중앙값 (entry close 대비, %)
  - entry close ↔ MA10(1h, close SMA10) 거리
  - 다음 10봉 종가 ↔ 그 시점 MA10 거리
  - 봉 인덱스(t+1..t+10) 별 forward 통계
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import numpy as np
import pandas as pd

CACHE_DIR = Path("data/cache/crypto/1h")
OUT_DIR = Path("scripts/out")
BODY_MIN = 0.05
CLOSE_TO_HIGH_MIN = 0.9
FORWARD = 10
MA_N = 10


def collect_events(symbol: str) -> pd.DataFrame:
    fp = CACHE_DIR / f"{symbol}.parquet"
    df = pd.read_parquet(fp)
    if len(df) < MA_N + FORWARD + 5:
        return pd.DataFrame()

    df = df.sort_values("timestamp").reset_index(drop=True)
    df["ma10"] = df["close"].rolling(MA_N).mean()

    body = df["close"] - df["open"]
    upper = df["high"] - df["open"]
    body_pct = body / df["open"]
    body_to_range = np.where(upper > 0, body / upper.replace(0, np.nan), np.nan)

    mask = (body_pct >= BODY_MIN) & (pd.Series(body_to_range, index=df.index) > CLOSE_TO_HIGH_MIN)
    idx_list = df.index[mask.fillna(False)].tolist()
    if not idx_list:
        return pd.DataFrame()

    closes = df["close"].values
    ma10s = df["ma10"].values
    ts = df["timestamp"].values

    rows = []
    for i in idx_list:
        if i + FORWARD >= len(df):
            continue
        ec = closes[i]
        em = ma10s[i]
        if not np.isfinite(em) or em <= 0 or ec <= 0:
            continue
        fwd_c = closes[i + 1:i + 1 + FORWARD]
        fwd_m = ma10s[i + 1:i + 1 + FORWARD]
        if np.any(~np.isfinite(fwd_m)) or np.any(fwd_m <= 0):
            continue

        fwd_ret = (fwd_c - ec) / ec * 100.0  # entry close 기준 %
        fwd_dist_ma10 = (fwd_c - fwd_m) / fwd_m * 100.0  # 각 봉 시점 MA10 거리 %

        row = {
            "symbol": symbol,
            "timestamp": ts[i],
            "trigger_body_pct": body_pct.iloc[i] * 100.0,
            "trigger_close_to_high": (body.iloc[i] / upper.iloc[i]) if upper.iloc[i] > 0 else np.nan,
            "entry_close": ec,
            "entry_close_to_ma10_pct": (ec - em) / em * 100.0,
            "fwd10_close_mean_return_pct": float(fwd_ret.mean()),
            "fwd10_close_median_return_pct": float(np.median(fwd_ret)),
            "fwd10_close_to_ma10_mean_pct": float(np.nanmean(fwd_dist_ma10)),
            "fwd10_close_to_ma10_median_pct": float(np.nanmedian(fwd_dist_ma10)),
        }
        # 봉별 (t+1..t+10) 도 저장
        for k in range(FORWARD):
            row[f"ret_t+{k+1}_pct"] = float(fwd_ret[k])
            row[f"dist_ma10_t+{k+1}_pct"] = float(fwd_dist_ma10[k])
        rows.append(row)

    return pd.DataFrame(rows)


def main():
    symbols = sorted(p.stem for p in CACHE_DIR.glob("*.parquet"))
    print(f"universe: {len(symbols)} symbols")

    parts = []
    for s in symbols:
        try:
            ev = collect_events(s)
            if not ev.empty:
                parts.append(ev)
        except Exception as e:
            print(f"  skip {s}: {e}")

    if not parts:
        print("no events found.")
        return

    ev = pd.concat(parts, ignore_index=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ev.to_csv(OUT_DIR / "pump_followthrough_events.csv", index=False)
    print(f"\nsaved events → {OUT_DIR/'pump_followthrough_events.csv'} ({len(ev):,} rows, {ev['symbol'].nunique()} symbols)")

    # ─── 표 1. 트리거·forward 전체 통계 ───
    summary = {
        "총_트리거_횟수": len(ev),
        "고유_심볼_수": int(ev["symbol"].nunique()),
        "트리거봉_몸통상승률_평균_퍼센트": float(ev["trigger_body_pct"].mean()),
        "트리거봉_몸통상승률_중앙값_퍼센트": float(ev["trigger_body_pct"].median()),
        "엔트리종가_MA10거리_평균_퍼센트": float(ev["entry_close_to_ma10_pct"].mean()),
        "엔트리종가_MA10거리_중앙값_퍼센트": float(ev["entry_close_to_ma10_pct"].median()),
        "다음10봉_종가_평균변화율의_평균_퍼센트": float(ev["fwd10_close_mean_return_pct"].mean()),
        "다음10봉_종가_평균변화율의_중앙값_퍼센트": float(ev["fwd10_close_mean_return_pct"].median()),
        "다음10봉_종가_중앙값변화율의_평균_퍼센트": float(ev["fwd10_close_median_return_pct"].mean()),
        "다음10봉_종가_중앙값변화율의_중앙값_퍼센트": float(ev["fwd10_close_median_return_pct"].median()),
        "다음10봉_종가_MA10거리의_평균_퍼센트": float(ev["fwd10_close_to_ma10_mean_pct"].mean()),
        "다음10봉_종가_MA10거리의_중앙값_퍼센트": float(ev["fwd10_close_to_ma10_mean_pct"].median()),
    }
    print("\n=== 표 1. 전체 집계 ===")
    for k, v in summary.items():
        print(f"  {k}: {v:+.3f}" if "퍼센트" in k or "거리" in k or "변화율" in k else f"  {k}: {v}")

    # ─── 표 2. 봉별(t+1..t+10) 통계 ───
    per_bar = []
    for k in range(1, FORWARD + 1):
        rcol = f"ret_t+{k}_pct"
        mcol = f"dist_ma10_t+{k}_pct"
        per_bar.append({
            "봉_인덱스": f"t+{k}",
            "종가변화율_평균_퍼센트": float(ev[rcol].mean()),
            "종가변화율_중앙값_퍼센트": float(ev[rcol].median()),
            "MA10거리_평균_퍼센트": float(ev[mcol].mean()),
            "MA10거리_중앙값_퍼센트": float(ev[mcol].median()),
        })
    per_bar_df = pd.DataFrame(per_bar)
    per_bar_df.to_csv(OUT_DIR / "pump_followthrough_per_bar.csv", index=False)
    print("\n=== 표 2. 봉 인덱스별 forward 통계 ===")
    print(per_bar_df.to_string(index=False, float_format=lambda x: f"{x:+.3f}"))
    print(f"\nsaved per-bar → {OUT_DIR/'pump_followthrough_per_bar.csv'}")


if __name__ == "__main__":
    main()
