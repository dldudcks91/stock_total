"""숏 보유 1~30일 일별 수익 분포.

룰 (사용자 원안 확정):
- 최근 7일 close 수익률 ≥ +X%  (X = 0.20 실용판 / 0.50 강버전 둘 다)
- 현재 close 가 주봉 MA20w 의 ±8% 이내
- 주봉 MA20w slope_4w < 0
→ 다음날 시가 숏

이번 분석: hold = 1, 2, ..., 30일 각 시점에서의 숏 수익 분포 측정.
- 평균, p10, p25, p50(중위), p75, p90, 윈율, 표본수
- 강제청산 -100% 캡 적용
- 신호 20일 dedup
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"

RALLY_LOOKBACK = 7      # 최근 N일
NEAR_PCT = 0.08         # MA20w ±Y%
DEDUP_DAYS = 15

# 두 시나리오
RULES = {
    "실용판_7일_플20pct": 0.20,
    "강버전_7일_플50pct": 0.50,
}


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


def collect_signals(files, rally_pct_threshold):
    """전체 캐시에서 신호 잡고 진입가/이후 30일 close 시리즈 수집."""
    all_entries = []      # (entry_price, [close_1, close_2, ..., close_30])
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

        entry = d["open"].shift(-1)
        n = len(d)
        sig_idx = np.where(sig.fillna(False).values)[0]
        for i in sig_idx:
            ep = entry.iloc[i] if i + 1 < n else np.nan
            if pd.isna(ep):
                continue
            # 1~30일 후 close (i+1 진입 기준으로 i+1+h 시점의 close)
            closes_after = []
            for h in range(1, 31):
                tgt = i + 1 + h
                if tgt < n:
                    closes_after.append(d["close"].iloc[tgt])
                else:
                    closes_after.append(np.nan)
            all_entries.append((ep, closes_after))
    return all_entries


def aggregate_by_hold(entries):
    """hold=1..30 일별 숏 수익 분포 집계."""
    rows = []
    for h in range(1, 31):
        rets = []
        for ep, closes in entries:
            cl = closes[h - 1]
            if pd.isna(cl) or pd.isna(ep):
                continue
            r = -(cl / ep - 1)
            r = max(r, -1.0)  # 강제청산 캡
            rets.append(r)
        if not rets:
            continue
        s = pd.Series(rets)
        rows.append({
            "보유_일": h,
            "표본수": int(len(s)),
            "윈율": float((s > 0).mean()),
            "평균_숏수익": float(s.mean()),
            "p10_숏수익": float(s.quantile(0.10)),
            "p25_숏수익": float(s.quantile(0.25)),
            "중위_p50_숏수익": float(s.quantile(0.50)),
            "p75_숏수익": float(s.quantile(0.75)),
            "p90_숏수익": float(s.quantile(0.90)),
            "표준편차": float(s.std()),
            "최대손실": float(s.min()),
        })
    return pd.DataFrame(rows)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CACHE_DIR.glob("*.parquet"))
    print(f"심볼 {len(files)}개")

    for name, threshold in RULES.items():
        print(f"\n수집 중: {name} (rally ≥ +{threshold:.0%})")
        entries = collect_signals(files, threshold)
        print(f"신호 (dedup 후): {len(entries)} 건")

        out = aggregate_by_hold(entries)
        print()
        print("=" * 110)
        print(f"[{name}]  룰: 최근 7일 +{threshold:.0%}↑ 급등 + MA20w ±8% + slope < 0  →  보유 1~30일 분포")
        print("=" * 110)
        print(out.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

        out_path = ROOT / "scripts" / "out" / f"short_hold_dist_{name}.csv"
        out.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"\nCSV: {out_path}")


if __name__ == "__main__":
    main()
