"""rally 정의 변형 비교 — "갑자기 급반등" 의 진짜 의미 잡기.

기존 정의 (문제 있음):
  rally = close[t] / close[t-7] - 1
  → 7일 전이 우연히 저점이 아니면 잘못 측정

새 정의 4종 비교:
  1. 일봉_저점_7일_low:   close[t] / min(low[t-7..t-1])  - 1
  2. 일봉_저점_14일_low:  close[t] / min(low[t-14..t-1]) - 1
  3. 주봉_저점_2주_low:    close[t] / min(주봉low[t-2주..t-1주]) - 1
  4. 주봉_저점_4주_low:    close[t] / min(주봉low[t-4주..t-1주]) - 1

공통 조건:
- 현재 close 가 주봉 MA20w ±8% 이내
- 주봉 MA20w slope_4w < 0
- 신규 상장 150일 컷
- 20일 dedup
- 강제청산 -100% 캡

그리드: rally_threshold × hold_days
  threshold ∈ {0.20, 0.30, 0.50}
  hold ∈ {7, 14, 30}
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"

NEAR_PCT = 0.08
DEDUP_DAYS = 20
RALLY_THRESHOLDS = [0.20, 0.30, 0.50]
HOLD_DAYS_LIST = [7, 14, 30]


def attach_weekly_ma20_and_low(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["dt"] = pd.to_datetime(d["timestamp"], unit="ms")
    weekly = (
        d.set_index("dt")
        .resample("W-MON", label="left", closed="left")
        .agg({"close": "last", "low": "min"})
        .dropna()
    )
    weekly["ma20w"] = weekly["close"].rolling(20, min_periods=20).mean()
    weekly["ma20w_slope_4w"] = weekly["ma20w"] / weekly["ma20w"].shift(4) - 1
    # 주봉 저점 2주/4주 (현재 주 제외, 직전 N주 안의 최저 low)
    weekly["low_min_2w"] = weekly["low"].shift(1).rolling(2).min()
    weekly["low_min_4w"] = weekly["low"].shift(1).rolling(4).min()
    # 일봉 인덱스에 forward-fill
    cols = ["ma20w", "ma20w_slope_4w", "low_min_2w", "low_min_4w"]
    weekly_ma = weekly[cols].reindex(d["dt"].dt.normalize().values, method="ffill")
    for c in cols:
        d[c] = weekly_ma[c].values
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

    # (rally_def_name, threshold, hold_days) → list of short returns
    results: dict[tuple, list[pd.Series]] = {}

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

        d = attach_weekly_ma20_and_low(df)
        d["dist_to_ma20w"] = d["close"] / d["ma20w"] - 1

        # rally 정의 4종 계산
        # 1. 일봉 7일 low 저점 대비
        low_min_7d = d["low"].shift(1).rolling(7).min()
        # 2. 일봉 14일 low 저점 대비
        low_min_14d = d["low"].shift(1).rolling(14).min()

        rally_defs = {
            "일봉_7일_저점": d["close"] / low_min_7d - 1,
            "일봉_14일_저점": d["close"] / low_min_14d - 1,
            "주봉_2주_저점": d["close"] / d["low_min_2w"] - 1,
            "주봉_4주_저점": d["close"] / d["low_min_4w"] - 1,
        }

        cond_near = d["dist_to_ma20w"].abs() <= NEAR_PCT
        cond_slope = d["ma20w_slope_4w"] < 0
        entry = d["open"].shift(-1)

        for def_name, rally in rally_defs.items():
            for thr in RALLY_THRESHOLDS:
                sig_raw = (rally >= thr) & cond_near & cond_slope
                if not sig_raw.any():
                    continue
                sig = dedup_signals(sig_raw, DEDUP_DAYS)
                for H in HOLD_DAYS_LIST:
                    exit_ = d["close"].shift(-(1 + H))
                    short_ret = -(exit_ / entry - 1)
                    s = short_ret[sig.fillna(False)].dropna()
                    if len(s) == 0:
                        continue
                    key = (def_name, thr, H)
                    results.setdefault(key, []).append(s)

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(files)}")

    rows = []
    for (def_name, thr, H), parts in results.items():
        s = pd.concat(parts)
        if len(s) < 30:
            continue
        s_capped = s.clip(lower=-1.0)
        rows.append({
            "rally_정의": def_name,
            "rally_임계_pct": f"+{thr*100:.0f}%",
            "숏보유_일": H,
            "표본수": int(len(s)),
            "윈율": float((s > 0).mean()),
            "평균_숏수익_capped": float(s_capped.mean()),
            "중위_숏수익": float(s.median()),
            "p10": float(s.quantile(0.10)),
            "p25": float(s.quantile(0.25)),
            "p75": float(s.quantile(0.75)),
            "p90": float(s.quantile(0.90)),
            "표준편차": float(s.std()),
            "최대손실": float(s.min()),
            "Sharpe_like": float(s.mean() / s.std()) if s.std() > 0 else np.nan,
        })

    out = pd.DataFrame(rows).sort_values([
        "rally_정의", "rally_임계_pct", "숏보유_일"
    ])

    print()
    print("=" * 130)
    print("전체 결과 (모든 정의 × 임계 × hold):")
    print("=" * 130)
    print(out.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    # 정의별 +50% 임계 / hold 30일 비교
    print()
    print("=" * 130)
    print("정의별 비교 (rally ≥ +50%, hold 30일) — 가장 강한 셋업 1:1 비교:")
    print("=" * 130)
    cmp = out[(out["rally_임계_pct"] == "+50%") & (out["숏보유_일"] == 30)]
    print(cmp.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("정의별 비교 (rally ≥ +30%, hold 30일):")
    print("=" * 130)
    cmp = out[(out["rally_임계_pct"] == "+30%") & (out["숏보유_일"] == 30)]
    print(cmp.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("정의별 비교 (rally ≥ +20%, hold 30일):")
    print("=" * 130)
    cmp = out[(out["rally_임계_pct"] == "+20%") & (out["숏보유_일"] == 30)]
    print(cmp.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    # Top 셀
    print()
    print("=" * 130)
    print("Top 15 by 평균_숏수익_capped (표본 ≥ 50):")
    print("=" * 130)
    top = out[out["표본수"] >= 50].nlargest(15, "평균_숏수익_capped")
    print(top.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    out_path = ROOT / "scripts" / "out" / "short_rally_def_compare.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_path}")


if __name__ == "__main__":
    main()
