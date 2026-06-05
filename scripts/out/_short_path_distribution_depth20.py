"""깊이 20% 시그널 — 진입 후 가격이 MA20w 대비 어디까지 갔다가 떨어졌나 (path 분포).

신호:
- 직전 N일 안에 일봉 low ≤ MA20w × 0.80 (= 직전에 MA20w 대비 -20% 이상 깊이 빠짐)
- 오늘 일봉 high ≥ MA20w
- MA20w slope_4w < 0

진입: 그 일봉 안에서 MA20w 가격에 limit short = 진입가 = MA20w
관측: 진입 후 1~30일 동안의 일봉 high/low, MA20w 대비 정규화

분석:
1. 위로 도달 누적 — 30일 안에 가격이 MA20w 위 +X% 까지 도달한 비율 (5% 단위)
2. 아래로 도달 누적 — 30일 안에 MA20w 아래 -X% 까지 도달한 비율
3. 30일 동안 도달한 최고가/최저가 5% 단위 히스토그램
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"

DEPTH_X = 0.20
LOOKBACKS = [10, 20]  # 반등기간
MAX_HOLD = 30
DEDUP_DAYS = 20


def attach_weekly_ma20(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["dt"] = pd.to_datetime(d["timestamp"], unit="ms")
    weekly = (
        d.set_index("dt")
        .resample("W-MON", label="left", closed="left")
        .agg({"close": "last"})
        .dropna()
    )
    weekly["ma20w"] = weekly["close"].rolling(20, min_periods=20).mean()
    weekly["ma20w_slope_4w"] = weekly["ma20w"] / weekly["ma20w"].shift(4) - 1
    weekly_ma = weekly[["ma20w", "ma20w_slope_4w"]].shift(1).reindex(
        d["dt"].dt.normalize().values, method="ffill"
    )
    d["ma20w"] = weekly_ma["ma20w"].values
    d["ma20w_slope_4w"] = weekly_ma["ma20w_slope_4w"].values
    return d


def dedup_signals(sig_arr, dedup_days):
    idx = np.where(sig_arr)[0]
    if len(idx) == 0:
        return np.zeros_like(sig_arr, dtype=bool)
    keep = [idx[0]]
    for i in idx[1:]:
        if i - keep[-1] >= dedup_days:
            keep.append(i)
    out = np.zeros_like(sig_arr, dtype=bool)
    out[keep] = True
    return out


def collect_paths(files, N_lookback):
    trades = []
    for f in files:
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if len(df) < 250:
            continue
        df = df.sort_values("timestamp").reset_index(drop=True)
        df = df.iloc[150:].reset_index(drop=True)
        if len(df) < 100:
            continue
        d = attach_weekly_ma20(df)
        n = len(d)

        low_min_N = d["low"].shift(1).rolling(N_lookback, min_periods=N_lookback).min()
        cond = (
            (low_min_N <= d["ma20w"] * (1 - DEPTH_X)) &
            (d["high"] >= d["ma20w"]) &
            (d["ma20w_slope_4w"] < 0)
        )
        sig_arr = cond.fillna(False).values
        sig_arr = dedup_signals(sig_arr, DEDUP_DAYS)

        for t in np.where(sig_arr)[0]:
            if t + MAX_HOLD >= n:
                continue
            entry = d["ma20w"].iloc[t]  # 진입가 = MA20w (limit short 가정)
            if pd.isna(entry):
                continue
            highs = d["high"].iloc[t + 1 : t + 1 + MAX_HOLD].values.astype(float)
            lows = d["low"].iloc[t + 1 : t + 1 + MAX_HOLD].values.astype(float)
            # MA20w (= entry) 대비 정규화
            high_vs = highs / entry - 1
            low_vs = lows / entry - 1
            trades.append({"high_vs": high_vs, "low_vs": low_vs})
    return trades


def reach_table_upward(trades, thresholds, horizons):
    total = len(trades)
    rows = []
    for thr in thresholds:
        row = {"MA20w_위_pct": f"+{thr*100:.0f}%"}
        for h in horizons:
            reached = sum(1 for t in trades if (t["high_vs"][:h] >= thr).any())
            row[f"{h}일_표본"] = reached
            row[f"{h}일_비율"] = reached / total if total else 0
        rows.append(row)
    return pd.DataFrame(rows)


def reach_table_downward(trades, thresholds, horizons):
    total = len(trades)
    rows = []
    for thr in thresholds:  # thr 는 음수
        row = {"MA20w_아래_pct": f"{thr*100:+.0f}%"}
        for h in horizons:
            reached = sum(1 for t in trades if (t["low_vs"][:h] <= thr).any())
            row[f"{h}일_표본"] = reached
            row[f"{h}일_비율"] = reached / total if total else 0
        rows.append(row)
    return pd.DataFrame(rows)


def final_extremes_histogram(trades, bin_edges):
    max_p, min_p = [], []
    for t in trades:
        max_p.append(t["high_vs"].max())
        min_p.append(t["low_vs"].min())
    max_s = pd.Series(max_p)
    min_s = pd.Series(min_p)
    bin_labels = [f"{bin_edges[i]*100:+.0f}% ~ {bin_edges[i+1]*100:+.0f}%" for i in range(len(bin_edges)-1)]
    max_hist = pd.cut(max_s, bins=bin_edges, labels=bin_labels, include_lowest=True).value_counts().sort_index()
    min_hist = pd.cut(min_s, bins=bin_edges, labels=bin_labels, include_lowest=True).value_counts().sort_index()
    total = len(trades)
    rows = []
    for label in bin_labels:
        rows.append({
            "MA20w_대비_구간": label,
            "최고가_표본수": int(max_hist.get(label, 0)),
            "최고가_비율": float(max_hist.get(label, 0)) / total if total else 0.0,
            "최저가_표본수": int(min_hist.get(label, 0)),
            "최저가_비율": float(min_hist.get(label, 0)) / total if total else 0.0,
        })
    return pd.DataFrame(rows)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CACHE_DIR.glob("*.parquet"))
    print(f"심볼 {len(files)}개")

    horizons = [3, 7, 14, 30]
    thr_up = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75, 1.00]
    thr_dn = [-0.05, -0.10, -0.15, -0.20, -0.25, -0.30, -0.40, -0.50]
    bin_edges = [-1.0, -0.50, -0.40, -0.30, -0.25, -0.20, -0.15, -0.10, -0.05,
                 0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 1.0, 5.0]

    for N in LOOKBACKS:
        print(f"\n{'='*100}\n>>>>> 깊이 임계 20% × 반등기간 {N}일\n{'='*100}")
        trades = collect_paths(files, N)
        total = len(trades)
        print(f"표본 (dedup 후): {total} 건  / 진입가 = MA20w 정확히\n")

        up_df = reach_table_upward(trades, thr_up, horizons)
        print("=" * 100)
        print(f"위로 도달 — 진입 후 N일 안에 MA20w 위 +X% 까지 도달한 케이스 (= 숏 손실 방향):")
        print("=" * 100)
        s = up_df.copy()
        for h in horizons:
            s[f"{h}일_비율"] = s[f"{h}일_비율"].apply(lambda v: f"{v*100:.1f}%")
        print(s.to_string(index=False))

        dn_df = reach_table_downward(trades, thr_dn, horizons)
        print()
        print("=" * 100)
        print(f"아래로 도달 — 진입 후 N일 안에 MA20w 아래 -X% 까지 도달한 케이스 (= 숏 이익 방향):")
        print("=" * 100)
        s = dn_df.copy()
        for h in horizons:
            s[f"{h}일_비율"] = s[f"{h}일_비율"].apply(lambda v: f"{v*100:.1f}%")
        print(s.to_string(index=False))

        hist_df = final_extremes_histogram(trades, bin_edges)
        print()
        print("=" * 100)
        print(f"30일 동안 도달한 최고가/최저가 5% 단위 히스토그램 (각 trade 1번 카운트):")
        print("=" * 100)
        h = hist_df.copy()
        h["최고가_비율"] = h["최고가_비율"].apply(lambda v: f"{v*100:.1f}%")
        h["최저가_비율"] = h["최저가_비율"].apply(lambda v: f"{v*100:.1f}%")
        print(h.to_string(index=False))

        # 저장
        up_path = ROOT / "scripts" / "out" / f"short_depth20_path_up_lb{N}.csv"
        dn_path = ROOT / "scripts" / "out" / f"short_depth20_path_dn_lb{N}.csv"
        hist_path = ROOT / "scripts" / "out" / f"short_depth20_path_hist_lb{N}.csv"
        up_df.to_csv(up_path, index=False, encoding="utf-8-sig")
        dn_df.to_csv(dn_path, index=False, encoding="utf-8-sig")
        hist_df.to_csv(hist_path, index=False, encoding="utf-8-sig")
        print(f"\nCSV: {up_path}\nCSV: {dn_path}\nCSV: {hist_path}")


if __name__ == "__main__":
    main()
