"""일봉 MA20 반등-거부 숏 그리드 — 표본 늘리기 + 중복 신호 정리.

주봉 MA20w 의 일봉 등가물 = MA100d (5배). MA20d 도 함께 비교.
- 일봉 MA100d (= 주봉 MA20w 등가) — 본 매치
- 일봉 MA50d — 더 빠른 추세
- 일봉 MA20d — 단기

그리드:
- ma_type: {"ma20", "ma50", "ma100"}
- K (lookback days): {20, 40, 60}  # 4주/8주/12주 등가
- X (dist 임계): {0.20, 0.30, 0.40, 0.50}
- Y (current 근접): {0.03, 0.05}
- H (hold days): {10, 20, 40, 60}  # 2주/4주/8주/12주 등가

신호 중복 제거: 같은 (symbol, ma_type, X, Y) 조합에서 연속 신호 중 첫 신호만 사용
(같은 트레이드 여러 번 잡히는 것 방지).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"

MA_LENGTHS = {"ma20": 20, "ma50": 50, "ma100": 100}
LOOKBACK_K = [20, 40, 60]
DIST_LOW_X = [0.20, 0.30, 0.40, 0.50]
DIST_NOW_Y = [0.03, 0.05]
HOLDS = [10, 20, 40, 60]

# 중복 신호 제거 — 같은 트레이드 N일 안에 재진입 막기
DEDUP_DAYS = 20  # 신호 발생 후 20일 내 같은 룰 재진입 금지


def dedup_signals(sig: pd.Series, dedup_days: int) -> pd.Series:
    """연속/근접 신호 제거. 신호일 t 발생 시 t~t+dedup_days 동안 다시 안 켜지게."""
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


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CACHE_DIR.glob("*.parquet"))
    print(f"심볼 {len(files)}개")

    results: dict[tuple, list[pd.Series]] = {}
    results_raw: dict[tuple, list[pd.Series]] = {}  # 중복 제거 전

    for i, f in enumerate(files):
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if len(df) < 250:
            continue
        df = df.sort_values("timestamp").reset_index(drop=True)
        # 신규 상장 첫 200일 컷 (MA100 + lookback 60 + buffer)
        df = df.iloc[150:].reset_index(drop=True)
        if len(df) < 100:
            continue

        entry = df["open"].shift(-1)

        for ma_name, ma_len in MA_LENGTHS.items():
            ma = df["close"].rolling(ma_len, min_periods=ma_len).mean()
            dist = df["close"] / ma - 1
            # slope: ma 가 같은 기간(20일) 변화율
            slope = ma / ma.shift(ma_len // 2) - 1

            for K in LOOKBACK_K:
                past_dist = dist.shift(K)
                for X in DIST_LOW_X:
                    cond_past = past_dist <= -X
                    for Y in DIST_NOW_Y:
                        cond_now = dist.abs() <= Y
                        cond_slope = slope < 0
                        sig_raw = cond_past & cond_now & cond_slope
                        if not sig_raw.any():
                            continue
                        sig = dedup_signals(sig_raw, DEDUP_DAYS)
                        for H in HOLDS:
                            exit_ = df["close"].shift(-(1 + H))
                            short_ret = -(exit_ / entry - 1)
                            # 중복 제거 후
                            s = short_ret[sig.fillna(False)].dropna()
                            s_raw = short_ret[sig_raw.fillna(False)].dropna()
                            if len(s) == 0:
                                continue
                            key = (ma_name, K, X, Y, H)
                            results.setdefault(key, []).append(s)
                            results_raw.setdefault(key, []).append(s_raw)

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(files)}")

    rows = []
    for key, parts in results.items():
        ma_name, K, X, Y, H = key
        s = pd.concat(parts)
        s_raw = pd.concat(results_raw[key])
        if len(s) < 30:
            continue
        s_capped = s.clip(lower=-1.0)
        rows.append({
            "ma": ma_name,
            "K_days": K,
            "X_dist_low": X,
            "Y_dist_now": Y,
            "H_hold": H,
            "count_dedup": int(len(s)),
            "count_raw": int(len(s_raw)),
            "win_rate": float((s > 0).mean()),
            "mean_short": float(s.mean()),
            "mean_capped": float(s_capped.mean()),
            "median_short": float(s.median()),
            "std": float(s.std()),
            "max_loss": float(s.min()),
            "sharpe_like": float(s.mean() / s.std()) if s.std() > 0 else np.nan,
        })

    out = pd.DataFrame(rows).sort_values(["ma", "K_days", "X_dist_low", "Y_dist_now", "H_hold"])

    print()
    print("=" * 110)
    print("Top 20 by mean_capped (count_dedup ≥ 100):")
    print("=" * 110)
    top = out[out["count_dedup"] >= 100].nlargest(20, "mean_capped")
    print(top.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print()
    print("=" * 110)
    print("Top 20 by sharpe_like (count_dedup ≥ 100):")
    print("=" * 110)
    top_s = out[out["count_dedup"] >= 100].nlargest(20, "sharpe_like")
    print(top_s.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print()
    print("=" * 110)
    print("MA100 (≈ 주봉 MA20w) 만 보기 — 사용자 원안:")
    print("=" * 110)
    ma100 = out[(out["ma"] == "ma100") & (out["count_dedup"] >= 50)].sort_values("mean_capped", ascending=False).head(15)
    print(ma100.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print()
    print("=" * 110)
    print("MA50 — 더 빠른 추세 (count_dedup ≥ 100):")
    print("=" * 110)
    ma50 = out[(out["ma"] == "ma50") & (out["count_dedup"] >= 100)].sort_values("mean_capped", ascending=False).head(15)
    print(ma50.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    out_path = ROOT / "scripts" / "out" / "short_ma_rally_daily_grid.csv"
    out.to_csv(out_path, index=False)
    print(f"\nCSV: {out_path}")
    print(f"전체 룰 조합: {len(out)}")


if __name__ == "__main__":
    main()
