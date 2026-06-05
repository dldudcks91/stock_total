"""주봉 MA20 반등-거부 숏 전략 그리드 백테스트.

전략 원칙:
1. 과거 K주 전에 MA20w 대비 이격이 크게 음수였다 (-X% 이하)
2. 현재 MA20w 근처로 반등했다 (|dist_now| ≤ Y%)
3. MA20w slope 가 여전히 음수 (Stage 4 정중앙, 추세 안 꺾임)
4. → t+1주 시가에 숏 진입, H주 hold 후 청산

그리드:
- K (얼마나 빠르게 반등?): {4, 8, 12} 주
- X (과거 이격 크기): {20, 30, 40, 50} %
- Y (현재 MA20w 근접): {3, 5} %
- H (hold 주): {2, 4, 8, 12} 주

신규 상장 효과 배제: 첫 30주(약 7개월) 데이터 컷.
강제청산 캡: -100% (실전 청산).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"

LOOKBACK_K = [4, 8, 12]          # 과거 이격 측정 시점 (주)
DIST_LOW_X = [0.20, 0.30, 0.40, 0.50]   # 과거 이격 -X% 이하
DIST_NOW_Y = [0.03, 0.05]                # 현재 MA20w 근접 ±Y%
HOLDS = [2, 4, 8, 12]            # 청산 주


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """1d → 1w 리샘플. timestamp ms → 주봉 OHLCV."""
    d = df.copy()
    d["dt"] = pd.to_datetime(d["timestamp"], unit="ms")
    d = d.set_index("dt").sort_index()
    w = d.resample("W-MON", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    })
    return w.dropna()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CACHE_DIR.glob("*.parquet"))
    print(f"심볼 {len(files)}개")

    results: dict[tuple, list[pd.Series]] = {}

    for i, f in enumerate(files):
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if len(df) < 250:  # 약 1년 이상
            continue

        w = to_weekly(df)
        if len(w) < 60:  # 약 60주 이상
            continue

        # 신규 상장 30주(약 7개월) 컷
        w = w.iloc[30:].reset_index(drop=True)
        if len(w) < 30:
            continue

        w["ma20w"] = w["close"].rolling(20, min_periods=20).mean()
        w["dist"] = w["close"] / w["ma20w"] - 1  # MA20w 대비 이격도
        w["slope_4w"] = w["ma20w"] / w["ma20w"].shift(4) - 1  # 4주 slope

        # 진입가 = 다음 주 시가
        entry = w["open"].shift(-1)

        for K in LOOKBACK_K:
            past_dist = w["dist"].shift(K)
            for X in DIST_LOW_X:
                cond_past = past_dist <= -X
                for Y in DIST_NOW_Y:
                    cond_now = w["dist"].abs() <= Y
                    cond_slope = w["slope_4w"] < 0
                    sig = cond_past & cond_now & cond_slope
                    if not sig.any():
                        continue
                    for H in HOLDS:
                        exit_ = w["close"].shift(-(1 + H))
                        short_ret = -(exit_ / entry - 1)
                        s = short_ret[sig.fillna(False)].dropna()
                        if len(s) == 0:
                            continue
                        key = (K, X, Y, H)
                        results.setdefault(key, []).append(s)

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(files)}")

    # 집계
    rows = []
    for (K, X, Y, H), parts in results.items():
        s = pd.concat(parts)
        if len(s) < 30:
            continue
        s_capped = s.clip(lower=-1.0)
        rows.append({
            "K_weeks_back": K,
            "X_dist_low_pct": X,
            "Y_dist_now_pct": Y,
            "H_hold_weeks": H,
            "count": int(len(s)),
            "win_rate": float((s > 0).mean()),
            "mean_short": float(s.mean()),
            "mean_capped": float(s_capped.mean()),
            "median_short": float(s.median()),
            "p25": float(s.quantile(0.25)),
            "p75": float(s.quantile(0.75)),
            "std": float(s.std()),
            "max_loss": float(s.min()),
            "sharpe_like": float(s.mean() / s.std()) if s.std() > 0 else np.nan,
        })

    out = pd.DataFrame(rows).sort_values(["K_weeks_back", "X_dist_low_pct", "Y_dist_now_pct", "H_hold_weeks"])
    print()
    print("=" * 100)
    print("전체 그리드 (count ≥ 30):")
    print("=" * 100)
    print(out.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print()
    print("=" * 100)
    print("Top 15 by mean_capped:")
    print("=" * 100)
    top = out.nlargest(15, "mean_capped")
    print(top.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print()
    print("=" * 100)
    print("Top 15 by sharpe_like (mean/std):")
    print("=" * 100)
    top_s = out.nlargest(15, "sharpe_like")
    print(top_s.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print()
    print("=" * 100)
    print("Top 15 by win_rate (count ≥ 100 만):")
    print("=" * 100)
    top_w = out[out["count"] >= 100].nlargest(15, "win_rate")
    print(top_w.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    out_path = ROOT / "scripts" / "out" / "short_ma20w_rally_grid.csv"
    out.to_csv(out_path, index=False)
    print(f"\nCSV: {out_path}")


if __name__ == "__main__":
    main()
