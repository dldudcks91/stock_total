"""일봉 가격 vs 주봉 MA20w 이격 기반 숏 그리드.

원안 (사용자):
- 주봉 MA20w (= 주봉 종가 기준 20주 단순이동평균) 을 큰 기준선으로 본다
- 일봉 가격이 이 선 대비 큰 음의 이격이었다가, 빠르게 반등해서 선 근처로 오면 그 자리에서 숏

핵심 — MA100d 와의 차이:
- MA20w 는 주봉 종가만 사용 → 일중 노이즈 X, 매주 월요일에만 갱신
- 즉 일봉 차원에서 보면 주 5일 동안 같은 값 유지되는 "수평 layer"
- MA100d 는 매일 갱신되는 100일 단순평균 (다른 선)

구현:
1. 일봉 OHLCV 로드
2. 주봉으로 리샘플 후 MA20w 계산
3. 주봉 MA20w 를 일봉 인덱스에 forward-fill (주 첫 일자 = 새 MA20w 값)
4. 일봉 close vs MA20w_ffill 이격도 측정
5. 그리드 백테스트

그리드 (전부 풀네임 컬럼):
- 이격_측정시점_일전: {20, 30, 40, 60}
- 과거_이격_이하_pct: {0.20, 0.30, 0.40, 0.50}
- 현재_근접_이내_pct: {0.03, 0.05, 0.08}
- 보유기간_일: {10, 20, 40, 60}

추세 게이트: MA20w slope (주봉 4주차분) < 0
중복 신호 제거: 같은 룰 20일 내 재진입 금지
강제청산 캡: 단일 트레이드 손실 -100% 클리핑
신규 상장 컷: 첫 150일 제외
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"

LOOKBACK_DAYS_LIST = [20, 30, 40, 60]
PAST_DIST_LIST = [0.20, 0.30, 0.40, 0.50]
NOW_NEAR_LIST = [0.03, 0.05, 0.08]
HOLD_DAYS_LIST = [10, 20, 40, 60]

DEDUP_DAYS = 20


def attach_weekly_ma20(df: pd.DataFrame) -> pd.DataFrame:
    """일봉 df 에 주봉 MA20w 를 forward-fill 로 붙임.

    df: timestamp(ms) + ohlcv. sorted by timestamp.
    반환: 같은 df 에 `ma20w` (일봉 인덱스에 매핑된 주봉 MA20w) 컬럼 추가
    """
    d = df.copy()
    d["dt"] = pd.to_datetime(d["timestamp"], unit="ms")
    # 주봉 리샘플 (월요일 시작)
    weekly = (
        d.set_index("dt")
        .resample("W-MON", label="left", closed="left")
        .agg({"close": "last"})
        .dropna()
    )
    weekly["ma20w"] = weekly["close"].rolling(20, min_periods=20).mean()
    weekly["ma20w_slope_4w"] = weekly["ma20w"] / weekly["ma20w"].shift(4) - 1
    # 일봉 인덱스에 매핑 — reindex + forward-fill
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
        # 신규 상장 150일 컷 (주봉 MA20w 안정화 위해 약 5개월+)
        df = df.iloc[150:].reset_index(drop=True)
        if len(df) < 100:
            continue

        d = attach_weekly_ma20(df)
        d["dist_to_ma20w"] = d["close"] / d["ma20w"] - 1  # 일봉 close vs 주봉MA20w

        entry = d["open"].shift(-1)

        for lookback_days in LOOKBACK_DAYS_LIST:
            past_dist = d["dist_to_ma20w"].shift(lookback_days)
            for past_dist_threshold in PAST_DIST_LIST:
                cond_past = past_dist <= -past_dist_threshold
                for now_near in NOW_NEAR_LIST:
                    cond_now = d["dist_to_ma20w"].abs() <= now_near
                    cond_slope = d["ma20w_slope_4w"] < 0
                    sig_raw = cond_past & cond_now & cond_slope
                    if not sig_raw.any():
                        continue
                    sig = dedup_signals(sig_raw, DEDUP_DAYS)
                    for hold_days in HOLD_DAYS_LIST:
                        exit_ = d["close"].shift(-(1 + hold_days))
                        short_ret = -(exit_ / entry - 1)
                        s = short_ret[sig.fillna(False)].dropna()
                        s_raw = short_ret[sig_raw.fillna(False)].dropna()
                        if len(s) == 0:
                            continue
                        key = (lookback_days, past_dist_threshold, now_near, hold_days)
                        results.setdefault(key, []).append(s)
                        results_raw.setdefault(key, []).append(s_raw)

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(files)}")

    rows = []
    for key, parts in results.items():
        lookback_days, past_dist_threshold, now_near, hold_days = key
        s = pd.concat(parts)
        s_raw = pd.concat(results_raw[key])
        if len(s) < 30:
            continue
        s_capped = s.clip(lower=-1.0)
        rows.append({
            "이격_측정시점_일전": lookback_days,
            "과거_이격_이하_pct": past_dist_threshold,
            "현재_근접_이내_pct": now_near,
            "보유기간_일": hold_days,
            "표본수_중복제거": int(len(s)),
            "표본수_원본": int(len(s_raw)),
            "윈율": float((s > 0).mean()),
            "평균_숏수익_capped": float(s_capped.mean()),
            "평균_숏수익_raw": float(s.mean()),
            "중위_숏수익": float(s.median()),
            "p25_숏수익": float(s.quantile(0.25)),
            "p75_숏수익": float(s.quantile(0.75)),
            "표준편차": float(s.std()),
            "최대손실": float(s.min()),
            "Sharpe_like": float(s.mean() / s.std()) if s.std() > 0 else np.nan,
        })

    out = pd.DataFrame(rows).sort_values([
        "이격_측정시점_일전", "과거_이격_이하_pct", "현재_근접_이내_pct", "보유기간_일"
    ])

    print()
    print("=" * 130)
    print("Top 20 by 평균_숏수익_capped (표본수_중복제거 ≥ 100):")
    print("=" * 130)
    top = out[out["표본수_중복제거"] >= 100].nlargest(20, "평균_숏수익_capped")
    print(top.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print()
    print("=" * 130)
    print("Top 20 by Sharpe_like (표본수_중복제거 ≥ 100):")
    print("=" * 130)
    top_s = out[out["표본수_중복제거"] >= 100].nlargest(20, "Sharpe_like")
    print(top_s.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    print()
    print("=" * 130)
    print("Top 20 by 윈율 (표본수_중복제거 ≥ 100):")
    print("=" * 130)
    top_w = out[out["표본수_중복제거"] >= 100].nlargest(20, "윈율")
    print(top_w.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    out_path = ROOT / "scripts" / "out" / "short_weekly_ma20w_rally_grid.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_path}")
    print(f"전체 룰 조합: {len(out)}")


if __name__ == "__main__":
    main()
