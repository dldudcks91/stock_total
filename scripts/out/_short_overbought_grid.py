"""숏 base rate 그리드: "얼마나 오른 후 들어가서, 얼마나 들고 있어야 숏 알파가 나오는가?"

원칙: 숏은 오를 때 친다.
- 신호: 과거 N일 수익률 ≥ +X% (이미 X% 이상 오른 상태)
- 진입: t+1 open
- 청산: t+1+H 의 close
- 숏 수익 = -(exit/entry - 1)

그리드:
- 과거 lookback N: {5, 10, 20, 40} 일
- 임계 X: {+20, +30, +50, +100, +200}%
- forward hold H: {5, 10, 20, 40, 60} 일

집계:
- mean / median 숏 수익
- 윈율 P(숏 수익 > 0)
- 표본 수

목표: 펌프 후 진입 + 짧은 hold 가 가장 강한지 확인. (사용자 직관: 숏은 오를 때 친다)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"

LOOKBACKS = [5, 10, 20, 40]
THRESHOLDS = [0.20, 0.30, 0.50, 1.00, 2.00]
HOLDS = [5, 10, 20, 40, 60]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CACHE_DIR.glob("*.parquet"))
    print(f"심볼 {len(files)}개")

    # (lookback, threshold, hold) → list of short returns
    results: dict[tuple, list[pd.Series]] = {}

    for i, f in enumerate(files):
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if len(df) < 100:
            continue
        df = df.sort_values("timestamp").reset_index(drop=True)
        # 신규 상장 70일 제외 (펌프 표본 오염 방지)
        df = df.iloc[70:].reset_index(drop=True)
        if len(df) < 50:
            continue

        entry = df["open"].shift(-1)

        for N in LOOKBACKS:
            past_ret = df["close"] / df["close"].shift(N) - 1
            for X in THRESHOLDS:
                sig = past_ret >= X
                if not sig.any():
                    continue
                for H in HOLDS:
                    exit_ = df["close"].shift(-(1 + H))
                    short_ret = -(exit_ / entry - 1)
                    s = short_ret[sig.fillna(False)].dropna()
                    if len(s) == 0:
                        continue
                    key = (N, X, H)
                    results.setdefault(key, []).append(s)

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(files)}")

    rows = []
    for (N, X, H), parts in results.items():
        s = pd.concat(parts)
        if len(s) < 30:
            continue
        # winsorize 1% (강제청산 -100% 이하는 실전 -100% 캡)
        # 단순화: 숏 손실 -1.0 이하면 -1.0 으로 캡 (강제청산)
        s_capped = s.clip(lower=-1.0)
        rows.append({
            "lookback_N": N,
            "threshold_X": X,
            "hold_H": H,
            "count": int(len(s)),
            "win_rate": float((s > 0).mean()),
            "mean_short": float(s.mean()),
            "mean_capped": float(s_capped.mean()),  # -100% 강제청산 캡
            "median_short": float(s.median()),
            "p25": float(s.quantile(0.25)),
            "p75": float(s.quantile(0.75)),
            "std": float(s.std()),
            "sharpe_like": float(s.mean() / s.std()) if s.std() > 0 else np.nan,
        })

    out = pd.DataFrame(rows).sort_values(["lookback_N", "threshold_X", "hold_H"])
    print()
    print("=" * 90)
    print("결과 (count ≥ 30 만):")
    print("=" * 90)
    print(out.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # 가장 강한 셀 top 10 (mean_capped 기준)
    print()
    print("=" * 90)
    print("Top 15 by mean_capped (강제청산 반영 후 평균 숏수익):")
    print("=" * 90)
    top = out.nlargest(15, "mean_capped")
    print(top.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print()
    print("=" * 90)
    print("Top 15 by median_short (이상치 영향 X):")
    print("=" * 90)
    top_med = out.nlargest(15, "median_short")
    print(top_med.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    out_path = ROOT / "scripts" / "out" / "short_overbought_grid.csv"
    out.to_csv(out_path, index=False)
    print(f"\nCSV: {out_path}")


if __name__ == "__main__":
    main()
