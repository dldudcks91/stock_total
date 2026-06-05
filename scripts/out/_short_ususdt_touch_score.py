"""일봉 단위 MA20w 터치 순간 limit short 백테스트.

룰 (사용자 의도 정확히):
- 매 일봉 t 에서 측정 (룩어헤드 없음, 그 일봉 시작 시점에 limit 걸음)
- 조건:
  1. 직전 N주 동안의 일봉 low 의 min ≤ MA20w[t] × (1 - X)
     (= 직전 N주 안에 MA20w 대비 -X% 이상 깊이 빠진 적 있음)
  2. 오늘 일봉의 high ≥ MA20w[t]
     (= 그 일봉 안에서 MA20w 에 도달함 → limit short 체결됨)
  3. MA20w slope_4w < 0  (계산은 직전 주봉 마감 기준)
- 진입가: MA20w (limit order 체결 가정)
- 청산: H일 후 일봉 close
- 강제청산: 단일 트레이드 -100% 캡
- 신규 상장 150일 컷
- dedup: 20일

그리드:
- 깊이 임계 X: {0.20, 0.30, 0.40, 0.50}
- 직전 N주 lookback (일봉 환산): {2주=10일, 4주=20일, 8주=40일, 12주=60일}
- hold: {10, 20, 30, 40}
- close 게이트: 옵션 — 진입 일봉의 close < MA20w 필수 / 무관 (현재는 신호 일봉의 close 미확인 시점에 limit 걸기 때문)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"

DEPTH_THRESHOLDS = [0.10, 0.20, 0.30, 0.40, 0.50]
LOOKBACK_DAYS_LIST = [10, 20, 40, 60]
HOLD_DAYS_LIST = [1, 2, 3, 4, 5, 6, 7]
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
    # MA20w 은 직전 주봉 마감 기준 — 일봉 인덱스에 forward-fill (단, 1주 lag)
    # 룩어헤드 회피: 현재 일봉에서 사용 가능한 MA20w 는 이번 주 시작 전 (= 직전 주봉 마감) 값
    weekly_ma = weekly[["ma20w", "ma20w_slope_4w"]].shift(1).reindex(
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


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CACHE_DIR.glob("*.parquet"))
    print(f"심볼 {len(files)}개")

    results: dict[tuple, list[float]] = {}

    for i, f in enumerate(files):
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

        cond_high_touch = d["high"] >= d["ma20w"]
        cond_slope = d["ma20w_slope_4w"] < 0

        for N_days in LOOKBACK_DAYS_LIST:
            # 직전 N일 (= N/5 주) 의 일봉 low 의 min (오늘 빼고 어제까지)
            low_min_N = d["low"].shift(1).rolling(N_days, min_periods=N_days).min()
            for X in DEPTH_THRESHOLDS:
                # MA20w 대비 -X% 이상 깊이 빠진 적 있음
                cond_deep = low_min_N <= d["ma20w"] * (1 - X)
                sig_raw = cond_deep & cond_high_touch & cond_slope
                if not sig_raw.any():
                    continue
                sig = dedup_signals(sig_raw, DEDUP_DAYS)
                sig_idx = np.where(sig.fillna(False).values)[0]

                for H in HOLD_DAYS_LIST:
                    rets = []
                    for t in sig_idx:
                        entry = d["ma20w"].iloc[t]
                        if t + H >= n:
                            continue
                        exit_p = d["close"].iloc[t + H]
                        if pd.isna(entry) or pd.isna(exit_p):
                            continue
                        ret = -(exit_p / entry - 1)
                        ret = max(ret, -1.0)
                        rets.append(ret)
                    if not rets:
                        continue
                    key = (X, N_days, H)
                    results.setdefault(key, []).extend(rets)

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(files)}")

    print(f"전체 (X,N,H) 조합 결과 키 수: {len(results)}")
    rows = []
    for (X, N_days, H), rets in results.items():
        s = pd.Series(rets)
        if len(s) < 30:
            continue
        rows.append({
            "직전_저점_MA20w_이하_pct": int(X * 100),
            "반등기간_일": N_days,
            "숏보유_일": H,
            "표본수": int(len(s)),
            "윈율": float((s > 0).mean()),
            "평균_숏수익": float(s.mean()),
            "중위_숏수익": float(s.median()),
            "p10_숏수익": float(s.quantile(0.10)),
            "p25_숏수익": float(s.quantile(0.25)),
            "p75_숏수익": float(s.quantile(0.75)),
            "p90_숏수익": float(s.quantile(0.90)),
            "표준편차": float(s.std()),
            "최대손실": float(s.min()),
            "Sharpe_like": float(s.mean() / s.std()) if s.std() > 0 else np.nan,
        })

    print(f"표본수 ≥ 30 통과 룰 수: {len(rows)}")
    if not rows:
        print("(결과 없음 — 신호 조건이 너무 좁거나 슬립 룩어헤드 문제)")
        return

    out = pd.DataFrame(rows).sort_values(["직전_저점_MA20w_이하_pct", "반등기간_일", "숏보유_일"])

    print()
    print("=" * 130)
    print("전체 결과 (일봉 MA20w 터치 limit short, 진입가 = MA20w):")
    print("=" * 130)
    print(out.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    # 깊이 임계별 hold 1~7일 비교
    print()
    print("=" * 130)
    print("깊이 임계 30% + 반등기간 20일 — hold 1~7일 분포:")
    print("=" * 130)
    cmp = out[(out["직전_저점_MA20w_이하_pct"] == 30) & (out["반등기간_일"] == 20)]
    print(cmp.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("깊이 임계 40% + 반등기간 20일 — hold 1~7일 분포:")
    print("=" * 130)
    cmp = out[(out["직전_저점_MA20w_이하_pct"] == 40) & (out["반등기간_일"] == 20)]
    print(cmp.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("깊이 임계 50% + 반등기간 20일 — hold 1~7일 분포:")
    print("=" * 130)
    cmp = out[(out["직전_저점_MA20w_이하_pct"] == 50) & (out["반등기간_일"] == 20)]
    print(cmp.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("깊이 임계 10% 만 — 모든 반등기간 × 모든 hold:")
    print("=" * 130)
    cmp = out[out["직전_저점_MA20w_이하_pct"] == 10]
    print(cmp.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("깊이 임계 20% 만 — 모든 반등기간 × 모든 hold:")
    print("=" * 130)
    cmp = out[out["직전_저점_MA20w_이하_pct"] == 20]
    print(cmp.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("깊이 임계 30% 만 — 모든 반등기간 × 모든 hold:")
    print("=" * 130)
    cmp = out[out["직전_저점_MA20w_이하_pct"] == 30]
    print(cmp.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("Top 20 by Sharpe_like (표본수 ≥ 100):")
    print("=" * 130)
    top_s = out[out["표본수"] >= 100].nlargest(20, "Sharpe_like")
    print(top_s.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    out_path = ROOT / "scripts" / "out" / "short_daily_ma20w_touch_limit.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_path}")


if __name__ == "__main__":
    main()
