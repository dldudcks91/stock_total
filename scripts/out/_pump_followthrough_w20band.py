"""
_pump_followthrough_w20gate.py 변형:
  + 주봉 MA20 위 0~10% 밴드 (추세 초입 추정)

게이트:
  0 < (entry_close - weekly_ma20) / weekly_ma20 <= 0.10
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
FORWARD = 20
MA_N = 10
WEEKLY_MA_N = 20
W20_BAND_MAX = 0.10  # 주봉 MA20 위 10% 이내


def load_with_weekly_ma20(symbol: str) -> pd.DataFrame:
    fp_1h = CACHE_1H / f"{symbol}.parquet"
    fp_1d = CACHE_1D / f"{symbol}.parquet"
    if not fp_1h.exists() or not fp_1d.exists():
        return pd.DataFrame()

    df_1h = pd.read_parquet(fp_1h).sort_values("timestamp").reset_index(drop=True)
    df_1d = pd.read_parquet(fp_1d).sort_values("timestamp").reset_index(drop=True)
    if len(df_1d) < WEEKLY_MA_N * 7 + 5:
        return pd.DataFrame()

    df_1h["ts"] = pd.to_datetime(df_1h["timestamp"], unit="ms", utc=True)
    df_1d["ts"] = pd.to_datetime(df_1d["timestamp"], unit="ms", utc=True)

    d = df_1d.set_index("ts")
    weekly_close = d["close"].resample("W-MON", closed="left", label="left").last()
    weekly_ma20 = weekly_close.rolling(WEEKLY_MA_N).mean()
    weekly_ma20_usable = weekly_ma20.shift(1)

    h = df_1h.set_index("ts").sort_index()
    mapped = weekly_ma20_usable.reindex(h.index, method="ffill")
    h["weekly_ma20"] = mapped.values
    return h.reset_index()


def collect_events(symbol: str) -> pd.DataFrame:
    df = load_with_weekly_ma20(symbol)
    if df.empty or len(df) < MA_N + FORWARD + 5:
        return pd.DataFrame()

    df["ma10"] = df["close"].rolling(MA_N).mean()
    body = df["close"] - df["open"]
    upper = df["high"] - df["open"]
    body_pct = body / df["open"]
    body_to_range = pd.Series(
        np.where(upper > 0, body / upper.replace(0, np.nan), np.nan),
        index=df.index,
    )

    close_to_w20 = (df["close"] - df["weekly_ma20"]) / df["weekly_ma20"]
    band_gate = (close_to_w20 > 0) & (close_to_w20 <= W20_BAND_MAX)

    mask = (body_pct >= BODY_MIN) & (body_to_range > CLOSE_TO_HIGH_MIN) & band_gate
    idx_list = df.index[mask.fillna(False)].tolist()
    if not idx_list:
        return pd.DataFrame()

    closes = df["close"].values
    ma10s = df["ma10"].values
    wma20s = df["weekly_ma20"].values
    ts = df["timestamp"].values

    rows = []
    for i in idx_list:
        if i + FORWARD >= len(df):
            continue
        ec = closes[i]
        em = ma10s[i]
        wm = wma20s[i]
        if not (np.isfinite(em) and em > 0 and ec > 0 and np.isfinite(wm) and wm > 0):
            continue
        fwd_c = closes[i + 1:i + 1 + FORWARD]
        fwd_m = ma10s[i + 1:i + 1 + FORWARD]
        if np.any(~np.isfinite(fwd_m)) or np.any(fwd_m <= 0):
            continue

        fwd_ret = (fwd_c - ec) / ec * 100.0
        fwd_dist_ma10 = (fwd_c - fwd_m) / fwd_m * 100.0

        row = {
            "symbol": symbol,
            "timestamp": ts[i],
            "trigger_body_pct": body_pct.iloc[i] * 100.0,
            "entry_close": ec,
            "entry_close_to_ma10_pct": (ec - em) / em * 100.0,
            "entry_close_to_weekly_ma20_pct": (ec - wm) / wm * 100.0,
            "fwd10_close_mean_return_pct": float(fwd_ret.mean()),
            "fwd10_close_median_return_pct": float(np.median(fwd_ret)),
            "fwd10_close_to_ma10_mean_pct": float(np.nanmean(fwd_dist_ma10)),
            "fwd10_close_to_ma10_median_pct": float(np.nanmedian(fwd_dist_ma10)),
        }
        for k in range(FORWARD):
            row[f"ret_t+{k+1}_pct"] = float(fwd_ret[k])
            row[f"dist_ma10_t+{k+1}_pct"] = float(fwd_dist_ma10[k])
        rows.append(row)

    return pd.DataFrame(rows)


def main():
    symbols = sorted(p.stem for p in CACHE_1H.glob("*.parquet"))
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
    ev.to_csv(OUT_DIR / "pump_followthrough_w20band_f20_events.csv", index=False)
    print(f"\nsaved events → {OUT_DIR/'pump_followthrough_w20band_f20_events.csv'} ({len(ev):,} rows, {ev['symbol'].nunique()} symbols)")

    print("\n=== 표 1. 전체 집계 (주봉 MA20 위 0~10% 밴드) ===")
    summary = [
        ("총_트리거_횟수", len(ev), False),
        ("고유_심볼_수", int(ev["symbol"].nunique()), False),
        ("트리거봉_몸통상승률_평균_퍼센트", float(ev["trigger_body_pct"].mean()), True),
        ("트리거봉_몸통상승률_중앙값_퍼센트", float(ev["trigger_body_pct"].median()), True),
        ("엔트리종가_MA10거리_평균_퍼센트", float(ev["entry_close_to_ma10_pct"].mean()), True),
        ("엔트리종가_MA10거리_중앙값_퍼센트", float(ev["entry_close_to_ma10_pct"].median()), True),
        ("엔트리종가_주봉MA20거리_평균_퍼센트", float(ev["entry_close_to_weekly_ma20_pct"].mean()), True),
        ("엔트리종가_주봉MA20거리_중앙값_퍼센트", float(ev["entry_close_to_weekly_ma20_pct"].median()), True),
        ("다음10봉_종가_평균변화율의_평균_퍼센트", float(ev["fwd10_close_mean_return_pct"].mean()), True),
        ("다음10봉_종가_평균변화율의_중앙값_퍼센트", float(ev["fwd10_close_mean_return_pct"].median()), True),
        ("다음10봉_종가_중앙값변화율의_평균_퍼센트", float(ev["fwd10_close_median_return_pct"].mean()), True),
        ("다음10봉_종가_중앙값변화율의_중앙값_퍼센트", float(ev["fwd10_close_median_return_pct"].median()), True),
        ("다음10봉_종가_MA10거리의_평균_퍼센트", float(ev["fwd10_close_to_ma10_mean_pct"].mean()), True),
        ("다음10봉_종가_MA10거리의_중앙값_퍼센트", float(ev["fwd10_close_to_ma10_mean_pct"].median()), True),
    ]
    for k, v, is_pct in summary:
        print(f"  {k}: {v:+.3f}" if is_pct else f"  {k}: {v}")

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
    per_bar_df.to_csv(OUT_DIR / "pump_followthrough_w20band_f20_per_bar.csv", index=False)
    print("\n=== 표 2. 봉 인덱스별 forward 통계 ===")
    print(per_bar_df.to_string(index=False, float_format=lambda x: f"{x:+.3f}"))
    print(f"\nsaved per-bar → {OUT_DIR/'pump_followthrough_w20band_f20_per_bar.csv'}")


if __name__ == "__main__":
    main()
