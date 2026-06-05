"""왜 숏 수익이 평균 음수인가? 4가지 가설 검증.

가설:
1. 생존 편향 — 현재 캐시 = 살아있는 심볼만 → 0 간 코인 빠짐 → 평균 return 양 편향
2. 강세장 구간 포함 — 2020~2026 중 강세장(2020-21, 2023-24) 비중 큼
3. 단기 hold 한계 — 5/10/20일은 일상 변동성, 추세 효과 약함
4. 이상치 (max_loss -13.9 = -1390%) — 특정 알트 펌프 케이스
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CACHE_DIR.glob("*.parquet"))
    print(f"심볼 {len(files)}개\n")

    # 1. 단순 buy & hold 평균 일일 수익률 (생존 편향 확인용)
    print("=" * 60)
    print("[1] 전체 캐시: 단순 일간 수익률 분포 (룰 무관)")
    print("=" * 60)
    daily_rets_all = []
    period_buckets = {"2020-2021": [], "2022": [], "2023-2024": [], "2025-2026": []}
    for f in files:
        df = pd.read_parquet(f)
        if len(df) < 30:
            continue
        df = df.sort_values("timestamp").reset_index(drop=True)
        df["dt"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["ret"] = df["close"].pct_change()
        daily_rets_all.append(df["ret"].dropna())
        # 구간별
        for label, (start, end) in [
            ("2020-2021", ("2020-01-01", "2021-12-31")),
            ("2022", ("2022-01-01", "2022-12-31")),
            ("2023-2024", ("2023-01-01", "2024-12-31")),
            ("2025-2026", ("2025-01-01", "2026-12-31")),
        ]:
            mask = (df["dt"] >= start) & (df["dt"] <= end)
            r = df.loc[mask, "ret"].dropna()
            if len(r):
                period_buckets[label].append(r)

    all_rets = pd.concat(daily_rets_all)
    print(f"전체 일간 수익 표본: {len(all_rets):,}개")
    print(f"  mean: {all_rets.mean():.5f}  (양수 = 평균적으로 상승)")
    print(f"  median: {all_rets.median():.5f}")
    print(f"  P(ret > 0): {(all_rets > 0).mean():.4f}")
    print(f"  P(ret < -5%): {(all_rets < -0.05).mean():.4f}")
    print(f"  P(ret > +5%): {(all_rets > +0.05).mean():.4f}")
    print()
    print("구간별 평균 일간 수익:")
    for label, parts in period_buckets.items():
        if parts:
            s = pd.concat(parts)
            print(f"  {label}: n={len(s):,}  mean={s.mean():.5f}  median={s.median():.5f}  P(>0)={(s>0).mean():.3f}")

    # 2. 20일 forward return 분포 (룰 무관)
    print()
    print("=" * 60)
    print("[2] 룰 무관: 모든 시점에서 t+1 진입 → t+21 청산 (롱 기준)")
    print("=" * 60)
    fwd_rets = []
    for f in files:
        df = pd.read_parquet(f)
        if len(df) < 50:
            continue
        df = df.sort_values("timestamp").reset_index(drop=True)
        entry = df["open"].shift(-1)
        exit_ = df["close"].shift(-21)
        fwd = (exit_ / entry - 1).dropna()
        fwd_rets.append(fwd)
    fwd_all = pd.concat(fwd_rets)
    print(f"20d forward return (롱):")
    print(f"  n={len(fwd_all):,}")
    print(f"  mean: {fwd_all.mean():.4f}  ← 양수면 평균적으로 오른다")
    print(f"  median: {fwd_all.median():.4f}")
    print(f"  P(ret > 0): {(fwd_all > 0).mean():.4f}")
    print(f"  → 숏 입장: mean = {-fwd_all.mean():.4f}, P(이김)={(fwd_all<0).mean():.4f}")

    # 3. 이상치 확인 — 20일 forward return 최악/최선
    print()
    print("=" * 60)
    print("[3] 이상치: 20d forward return 극값 (단일 트레이드)")
    print("=" * 60)
    print(f"  롱 max gain: {fwd_all.max():.2f} ({fwd_all.max()*100:.1f}%)")
    print(f"  롱 max loss: {fwd_all.min():.2f} ({fwd_all.min()*100:.1f}%)")
    print(f"  → 숏 max loss = -롱 max gain = {-fwd_all.max():.2f}")
    print(f"  P(롱 ret > +100%): {(fwd_all > 1.0).mean():.5f}  ← 이게 숏 -100% 손실")
    print(f"  P(롱 ret > +500%): {(fwd_all > 5.0).mean():.5f}  ← 이게 숏 -500% 손실 (사실상 청산)")

    # 4. 신규 상장 vs 오래된 심볼
    print()
    print("=" * 60)
    print("[4] 신규 상장 효과: 데이터 길이별 평균 20d forward return")
    print("=" * 60)
    by_age = {"신규(<200d)": [], "중간(200-500d)": [], "오래된(>500d)": []}
    for f in files:
        df = pd.read_parquet(f)
        if len(df) < 50:
            continue
        df = df.sort_values("timestamp").reset_index(drop=True)
        n = len(df)
        if n < 200:
            label = "신규(<200d)"
        elif n < 500:
            label = "중간(200-500d)"
        else:
            label = "오래된(>500d)"
        entry = df["open"].shift(-1)
        exit_ = df["close"].shift(-21)
        fwd = (exit_ / entry - 1).dropna()
        if len(fwd):
            by_age[label].append(fwd)
    for label, parts in by_age.items():
        if parts:
            s = pd.concat(parts)
            print(f"  {label}: n_심볼={len(parts):3d}  표본={len(s):>7,}  mean_롱={s.mean():+.4f}  P(>0)={(s>0).mean():.3f}")

    # 5. 약세장만 골라서 — 2022년만 + 2025-12 ~ 현재
    print()
    print("=" * 60)
    print("[5] 약세장 구간만 — 같은 검출기 룰 다시 (S3 MA rejection 만 빠르게)")
    print("=" * 60)
    bear_periods = [("2022-01-01", "2022-12-31"), ("2025-12-01", "2026-12-31")]
    bear_rets = []
    for f in files:
        df = pd.read_parquet(f)
        if len(df) < 100:
            continue
        df = df.sort_values("timestamp").reset_index(drop=True)
        df["dt"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["ma20"] = df["close"].rolling(20).mean()
        df["high"] = df["high"]
        df["ma20_slope"] = df["ma20"] / df["ma20"].shift(20) - 1
        # S3 신호
        near_ma20 = (df["high"] >= df["ma20"] * 0.98) & (df["close"] < df["ma20"])
        touch_40 = near_ma20.rolling(40).sum()
        sig = (touch_40 >= 3) & (df["ma20_slope"] < 0) & (df["close"] < df["ma20"])
        # 약세장 마스크
        mask = pd.Series(False, index=df.index)
        for start, end in bear_periods:
            mask |= (df["dt"] >= start) & (df["dt"] <= end)
        sig = sig & mask
        if not sig.any():
            continue
        entry = df["open"].shift(-1)
        exit_ = df["close"].shift(-21)
        short_ret = -(exit_ / entry - 1)
        bear_rets.append(short_ret[sig.fillna(False)].dropna())
    if bear_rets:
        s = pd.concat(bear_rets)
        print(f"S3 in bear periods only (2022 + 2025-12~):")
        print(f"  n={len(s):,}  mean_short_ret={s.mean():+.4f}  win_rate={(s>0).mean():.4f}")
        print(f"  median={s.median():+.4f}  std={s.std():.4f}")


if __name__ == "__main__":
    main()
