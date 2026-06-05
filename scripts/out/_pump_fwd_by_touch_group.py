"""
5%+ 윗꼬리 짧은 장대양봉 후, MA10 첫 터치까지 걸린 봉 수 그룹별로
t+1 ~ t+20 종가 변화율(entry 기준 %) 의 평균 / 중앙값.

모집단: 전체 트리거 (주봉 게이트 없음).
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import numpy as np
import pandas as pd

CACHE_1H = Path("data/cache/crypto/1h")
OUT_DIR = Path("scripts/out")

BODY_MIN = 0.05
CLOSE_TO_HIGH_MIN = 0.9
MA_N = 10
FORWARD = 20
MAX_LOOKAHEAD = 480


def find_events(symbol: str):
    fp = CACHE_1H / f"{symbol}.parquet"
    if not fp.exists():
        return []
    df = pd.read_parquet(fp).sort_values("timestamp").reset_index(drop=True)
    if len(df) < MA_N + MAX_LOOKAHEAD + 5:
        return []
    df["ma10"] = df["close"].rolling(MA_N).mean()
    body = df["close"] - df["open"]
    upper = df["high"] - df["open"]
    body_pct = body / df["open"]
    body_to_range = pd.Series(
        np.where(upper > 0, body / upper.replace(0, np.nan), np.nan),
        index=df.index,
    )
    mask = (body_pct >= BODY_MIN) & (body_to_range > CLOSE_TO_HIGH_MIN)

    closes = df["close"].values
    ma10s = df["ma10"].values
    n = len(df)

    out = []
    for i in df.index[mask.fillna(False)].tolist():
        ec = closes[i]
        em = ma10s[i]
        if not (np.isfinite(em) and em > 0 and ec > em):
            continue
        if i + FORWARD >= n:
            continue
        fwd_c = closes[i + 1:i + 1 + FORWARD]
        fwd_m = ma10s[i + 1:i + 1 + FORWARD]
        if np.any(~np.isfinite(fwd_m)) or np.any(fwd_m <= 0):
            continue

        end = min(n, i + 1 + MAX_LOOKAHEAD)
        touched = -1
        for j in range(i + 1, end):
            m = ma10s[j]
            if not np.isfinite(m) or m <= 0:
                continue
            if closes[j] <= m:
                touched = j - i
                break
        if touched == -1:
            continue

        fwd_ret = (fwd_c - ec) / ec * 100.0
        row = {"symbol": symbol, "bars_to_touch": touched}
        for k in range(FORWARD):
            row[f"ret_t+{k+1}_pct"] = float(fwd_ret[k])
        out.append(row)
    return out


def assign_group(b: int) -> str:
    if b == 1: return "01_1봉"
    if b <= 3: return "02_2~3봉"
    if b <= 6: return "03_4~6봉"
    if b <= 10: return "04_7~10봉"
    if b <= 20: return "05_11~20봉"
    return "06_21봉+"


def main():
    symbols = sorted(p.stem for p in CACHE_1H.glob("*.parquet"))
    print(f"universe: {len(symbols)} symbols")

    rows = []
    for s in symbols:
        try:
            rows.extend(find_events(s))
        except Exception as e:
            print(f"  skip {s}: {e}")

    ev = pd.DataFrame(rows)
    ev["group"] = ev["bars_to_touch"].apply(assign_group)
    print(f"events: {len(ev):,}")

    ret_cols = [f"ret_t+{k}_pct" for k in range(1, FORWARD + 1)]
    short_cols = [f"t+{k}" for k in range(1, FORWARD + 1)]

    n_per = ev.groupby("group").size().rename("n").to_frame()
    med = ev.groupby("group")[ret_cols].median()
    mean = ev.groupby("group")[ret_cols].mean()
    med.columns = short_cols
    mean.columns = short_cols

    med_df = pd.concat([n_per, med.round(2)], axis=1)
    mean_df = pd.concat([n_per, mean.round(2)], axis=1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    med_df.to_csv(OUT_DIR / "pump_fwd_by_touch_group_median.csv")
    mean_df.to_csv(OUT_DIR / "pump_fwd_by_touch_group_mean.csv")

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 280)

    print("\n=== 표 1. 첫 터치 봉 수 그룹별 종가 변화율 중앙값(%) — entry 대비 ===")
    print(med_df.to_string(float_format=lambda x: f"{x:+.2f}"))

    print("\n=== 표 2. 동일하게 평균(%) ===")
    print(mean_df.to_string(float_format=lambda x: f"{x:+.2f}"))

    print(f"\nsaved → {OUT_DIR/'pump_fwd_by_touch_group_median.csv'}")
    print(f"saved → {OUT_DIR/'pump_fwd_by_touch_group_mean.csv'}")


if __name__ == "__main__":
    main()
