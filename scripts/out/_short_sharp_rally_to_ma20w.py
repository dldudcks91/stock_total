"""주봉 MA20w 기준 — 단기 sharp rally (dead cat bounce) 숏 그리드.

전략 원칙 (사용자 원안):
- 가격이 주봉 MA20w 아래로 깊이 박혀 있다가
- **갑자기** (며칠 내) 급반등하여 MA20w 근처 터치
- 그 자리에서 숏

룰 정의:
1. 단기_급반등_기간_일 N 안에 close 가 +단기_급반등_폭_pct 이상 급등
2. 그 급반등 직전 (= N일 전) 의 가격은 MA20w 대비 -급반등_직전_이격_이하_pct 이상 이격
3. 현재 close 가 MA20w ±현재_MA20w_근접_pct 이내
4. MA20w slope_4w < 0 (장기 추세 여전히 약세)
5. → 다음날 시가에 숏, 숏보유_일 후 청산

그리드:
- 단기_급반등_기간_일 N:        {3, 5, 7, 10}
- 단기_급반등_폭_pct A:           {0.20, 0.30, 0.50}
- 급반등_직전_이격_이하_pct Z:   {0.10, 0.20, 0.30}
- 현재_MA20w_근접_pct Y:          {0.03, 0.05, 0.08}
- 숏보유_일 H:                    {10, 20, 40}

신규 상장 150일 컷. 중복 신호 20일 dedup. 강제청산 -100% 캡.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"

SHORT_RALLY_DAYS = [3, 5, 7, 10]
SHORT_RALLY_PCT = [0.20, 0.30, 0.50]
PRE_RALLY_DIST = [0.10, 0.20, 0.30]
NOW_NEAR_PCT = [0.03, 0.05, 0.08]
HOLD_DAYS_LIST = [10, 20, 40]

DEDUP_DAYS = 15


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


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CACHE_DIR.glob("*.parquet"))
    print(f"심볼 {len(files)}개")

    results: dict[tuple, list[pd.Series]] = {}
    results_raw: dict[tuple, list[pd.Series]] = {}

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
        d["dist_to_ma20w"] = d["close"] / d["ma20w"] - 1

        entry = d["open"].shift(-1)

        for N in SHORT_RALLY_DAYS:
            # 단기 급반등 폭 = 최근 N일 동안의 가격 변화
            rally_pct = d["close"] / d["close"].shift(N) - 1
            # 급반등 직전 시점의 이격 = N일 전 시점의 dist
            pre_dist = d["dist_to_ma20w"].shift(N)
            for A in SHORT_RALLY_PCT:
                cond_rally = rally_pct >= A
                for Z in PRE_RALLY_DIST:
                    cond_pre = pre_dist <= -Z
                    for Y in NOW_NEAR_PCT:
                        cond_now = d["dist_to_ma20w"].abs() <= Y
                        cond_slope = d["ma20w_slope_4w"] < 0
                        sig_raw = cond_rally & cond_pre & cond_now & cond_slope
                        if not sig_raw.any():
                            continue
                        sig = dedup_signals(sig_raw, DEDUP_DAYS)
                        for H in HOLD_DAYS_LIST:
                            exit_ = d["close"].shift(-(1 + H))
                            short_ret = -(exit_ / entry - 1)
                            s = short_ret[sig.fillna(False)].dropna()
                            s_raw = short_ret[sig_raw.fillna(False)].dropna()
                            if len(s) == 0:
                                continue
                            key = (N, A, Z, Y, H)
                            results.setdefault(key, []).append(s)
                            results_raw.setdefault(key, []).append(s_raw)

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(files)}")

    rows = []
    for key, parts in results.items():
        N, A, Z, Y, H = key
        s = pd.concat(parts)
        s_raw = pd.concat(results_raw[key])
        if len(s) < 30:
            continue
        s_capped = s.clip(lower=-1.0)
        rows.append({
            "단기_급반등_기간_일": N,
            "단기_급반등_폭_pct": A,
            "급반등_직전_이격_이하_pct": Z,
            "현재_MA20w_근접_pct": Y,
            "숏보유_일": H,
            "표본수_중복제거": int(len(s)),
            "표본수_원본": int(len(s_raw)),
            "윈율": float((s > 0).mean()),
            "평균_숏수익_capped": float(s_capped.mean()),
            "중위_숏수익": float(s.median()),
            "p25_숏수익": float(s.quantile(0.25)),
            "p75_숏수익": float(s.quantile(0.75)),
            "표준편차": float(s.std()),
            "최대손실": float(s.min()),
            "Sharpe_like": float(s.mean() / s.std()) if s.std() > 0 else np.nan,
        })

    out = pd.DataFrame(rows).sort_values([
        "단기_급반등_기간_일", "단기_급반등_폭_pct", "급반등_직전_이격_이하_pct",
        "현재_MA20w_근접_pct", "숏보유_일"
    ])

    print()
    print("=" * 130)
    print("Top 25 by 평균_숏수익_capped (표본 ≥ 50):")
    print("=" * 130)
    top = out[out["표본수_중복제거"] >= 50].nlargest(25, "평균_숏수익_capped")
    print(top.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print()
    print("=" * 130)
    print("Top 20 by Sharpe_like (표본 ≥ 100):")
    print("=" * 130)
    top_s = out[out["표본수_중복제거"] >= 100].nlargest(20, "Sharpe_like")
    print(top_s.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print()
    print("=" * 130)
    print("Top 20 by 윈율 (표본 ≥ 100):")
    print("=" * 130)
    top_w = out[out["표본수_중복제거"] >= 100].nlargest(20, "윈율")
    print(top_w.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    out_path = ROOT / "scripts" / "out" / "short_sharp_rally_to_ma20w_grid.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_path}")
    print(f"전체 룰 조합: {len(out)}")


if __name__ == "__main__":
    main()
