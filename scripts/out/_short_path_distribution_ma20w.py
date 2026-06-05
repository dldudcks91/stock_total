"""숏 진입 후 주봉 MA20w 기준 5% 단위 도달 분포.

질문 (사용자):
- 진입 후 가격이 MA20w 위로 / 아래로 5% 단위로 어디까지 가는지
- 각 임계값별 표본 수 + 비율

룰: 강버전 (rally ≥ +50%) + 실용판 (rally ≥ +20%) 둘 다.

분석 (2가지):
1. **위로 max 도달** — 진입 후 30일 안에 가격이 MA20w 위 X% 까지 도달한 표본 수/비율
   (X = +5, +10, +15, ..., +100%)
2. **아래로 min 도달** — 진입 후 30일 안에 가격이 MA20w 아래 -Y% 까지 도달한 표본 수/비율
   (Y = -5, -10, -15, ..., -100%)

추가: 시간별 (7일/14일/30일) 누적 도달 비율도.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"

RALLY_LOOKBACK = 7
NEAR_PCT = 0.08
DEDUP_DAYS = 15

RULES = {
    "강버전_rally_플50pct": 0.50,
    "실용판_rally_플20pct": 0.20,
}

MAX_HOLD = 30


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
    weekly_ma = weekly[["ma20w", "ma20w_slope_4w"]].reindex(
        d["dt"].dt.normalize().values, method="ffill"
    )
    d["ma20w"] = weekly_ma["ma20w"].values
    d["ma20w_slope_4w"] = weekly_ma["ma20w_slope_4w"].values
    return d


def dedup_signals(sig: pd.Series, dedup_days: int) -> pd.Series:
    idx = np.where(sig.fillna(False).values)[0]
    if len(idx) == 0:
        return sig
    keep = [idx[0]]
    for i in idx[1:]:
        if i - keep[-1] >= dedup_days:
            keep.append(i)
    out = pd.Series(False, index=sig.index)
    out.iloc[keep] = True
    return out


def collect_paths(files, rally_pct_threshold):
    """각 신호에 대해 진입 후 30일 high/low + 진입 시점 MA20w 기록."""
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
        d["dist_to_ma20w"] = d["close"] / d["ma20w"] - 1
        rally = d["close"] / d["close"].shift(RALLY_LOOKBACK) - 1
        sig_raw = (
            (rally >= rally_pct_threshold)
            & (d["dist_to_ma20w"].abs() <= NEAR_PCT)
            & (d["ma20w_slope_4w"] < 0)
        )
        sig = dedup_signals(sig_raw, DEDUP_DAYS)
        n = len(d)
        for i in np.where(sig.fillna(False).values)[0]:
            if i + 1 + MAX_HOLD >= n:
                continue
            ma_entry = d["ma20w"].iloc[i + 1]
            if pd.isna(ma_entry):
                continue
            highs = d["high"].iloc[i + 1 : i + 1 + MAX_HOLD].values.astype(float)
            lows = d["low"].iloc[i + 1 : i + 1 + MAX_HOLD].values.astype(float)
            # MA20w 대비 정규화
            high_vs_ma = highs / ma_entry - 1
            low_vs_ma = lows / ma_entry - 1
            trades.append({
                "high_vs_ma": high_vs_ma,
                "low_vs_ma": low_vs_ma,
            })
    return trades


def reach_table_upward(trades, thresholds_up, horizons):
    """위로 도달 — 각 임계값을 진입 후 N일 안에 처음 넘은 케이스 비율."""
    total = len(trades)
    rows = []
    for thr in thresholds_up:
        row = {"MA20w_대비_위치_pct": f"+{thr*100:.0f}%"}
        for h in horizons:
            reached = 0
            for t in trades:
                if (t["high_vs_ma"][:h] >= thr).any():
                    reached += 1
            row[f"{h}일내_도달_표본"] = reached
            row[f"{h}일내_도달_비율"] = reached / total if total else 0.0
        rows.append(row)
    return pd.DataFrame(rows), total


def reach_table_downward(trades, thresholds_down, horizons):
    """아래로 도달 — 각 임계값을 진입 후 N일 안에 처음 깬 케이스 비율."""
    total = len(trades)
    rows = []
    for thr in thresholds_down:  # thr 는 음수
        row = {"MA20w_대비_위치_pct": f"{thr*100:+.0f}%"}
        for h in horizons:
            reached = 0
            for t in trades:
                if (t["low_vs_ma"][:h] <= thr).any():
                    reached += 1
            row[f"{h}일내_도달_표본"] = reached
            row[f"{h}일내_도달_비율"] = reached / total if total else 0.0
        rows.append(row)
    return pd.DataFrame(rows), total


def final_extremes_histogram(trades, bin_edges):
    """진입 후 30일 동안의 MAX 와 MIN 의 MA20w 대비 위치를 5% 단위 히스토그램.

    한 trade 가 1번씩만 카운트 (가장 멀리 간 위치).
    """
    max_positions = []
    min_positions = []
    for t in trades:
        max_positions.append(t["high_vs_ma"].max())
        min_positions.append(t["low_vs_ma"].min())
    max_s = pd.Series(max_positions)
    min_s = pd.Series(min_positions)
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

    horizons = [7, 14, 30]
    thresholds_up = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75, 1.00, 1.50, 2.00]
    thresholds_down = [-0.05, -0.10, -0.15, -0.20, -0.25, -0.30, -0.40, -0.50, -0.75]
    bin_edges = [-1.0, -0.75, -0.50, -0.40, -0.30, -0.25, -0.20, -0.15, -0.10, -0.05,
                 0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75, 1.00, 5.0]

    for name, threshold in RULES.items():
        print(f"\n{'='*100}\n>>>>>>>>>>  {name}  (rally ≥ +{threshold:.0%})\n{'='*100}")
        trades = collect_paths(files, threshold)
        total = len(trades)
        print(f"신호 (dedup 후): {total} 건\n")

        # 1. 위로 도달 (cumulative)
        up_df, _ = reach_table_upward(trades, thresholds_up, horizons)
        print("=" * 100)
        print("위로 도달 — MA20w 위 +X% 까지 진입 후 N일 안에 도달한 케이스 (누적):")
        print("=" * 100)
        # 비율 % 표시
        up_show = up_df.copy()
        for h in horizons:
            up_show[f"{h}일내_도달_비율"] = up_show[f"{h}일내_도달_비율"].apply(lambda v: f"{v*100:.1f}%")
        print(up_show.to_string(index=False))

        # 2. 아래로 도달 (cumulative)
        dn_df, _ = reach_table_downward(trades, thresholds_down, horizons)
        print()
        print("=" * 100)
        print("아래로 도달 — MA20w 아래 -X% 까지 진입 후 N일 안에 도달한 케이스 (누적):")
        print("=" * 100)
        dn_show = dn_df.copy()
        for h in horizons:
            dn_show[f"{h}일내_도달_비율"] = dn_show[f"{h}일내_도달_비율"].apply(lambda v: f"{v*100:.1f}%")
        print(dn_show.to_string(index=False))

        # 3. 30일 동안 도달한 최고/최저 위치 히스토그램 (5% bin)
        hist_df = final_extremes_histogram(trades, bin_edges)
        print()
        print("=" * 100)
        print("30일 동안 MA20w 대비 최고가/최저가 5% 단위 히스토그램 (각 trade 1번 카운트):")
        print("=" * 100)
        hist_show = hist_df.copy()
        hist_show["최고가_비율"] = hist_show["최고가_비율"].apply(lambda v: f"{v*100:.1f}%")
        hist_show["최저가_비율"] = hist_show["최저가_비율"].apply(lambda v: f"{v*100:.1f}%")
        print(hist_show.to_string(index=False))

        # 저장
        up_path = ROOT / "scripts" / "out" / f"short_reach_up_{name}.csv"
        dn_path = ROOT / "scripts" / "out" / f"short_reach_dn_{name}.csv"
        hist_path = ROOT / "scripts" / "out" / f"short_hist_{name}.csv"
        up_df.to_csv(up_path, index=False, encoding="utf-8-sig")
        dn_df.to_csv(dn_path, index=False, encoding="utf-8-sig")
        hist_df.to_csv(hist_path, index=False, encoding="utf-8-sig")
        print(f"\nCSV: {up_path}\nCSV: {dn_path}\nCSV: {hist_path}")


if __name__ == "__main__":
    main()
