"""단일 일봉이 주봉 MA20w 를 wick test 하는 패턴 — 숏 백테스트.

룰 (사용자 명확화):
- 단일 일봉 t 에서 high 가 주봉 MA20w 에 닿음 (윗꼬리 spike)
- 동시에 그 일봉의 low 가 MA20w 보다 X% 이상 아래
  → 즉 "하루 만에 MA20w 아래에서 위로 강하게 솟구쳤다"
- MA20w slope_4w < 0 (장기 추세 약세)
- → 다음날 시가 숏, hold 후 청산

조건 정형화:
- high[t] >= MA20w[t]                     (high 가 MA20w 위로 닿음)
- low[t]  <= MA20w[t] * (1 - X)            (low 가 MA20w 의 (1-X) 배 이하)
- ma20w_slope_4w[t] < 0

그리드:
- (MA20w - low) / MA20w 이상 임계 X: {0.05, 0.10, 0.15, 0.20, 0.30}
- hold: {7, 14, 30}
- close 추가 게이트 옵션: {없음, close < MA20w (= 위로 갔다가 도로 내려옴)}

신규 상장 150일 컷, 20일 dedup, 강제청산 -100% 캡.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"

LOW_GAP_THRESHOLDS = [0.05, 0.10, 0.15, 0.20, 0.30]
HOLD_DAYS_LIST = [7, 14, 30]
DEDUP_DAYS = 15

CLOSE_GATES = {
    "close_무관": None,
    "close_lt_MA20w": "below",       # close 가 MA20w 아래 (= 다시 내려옴)
    "close_lt_MA20w_minus_3pct": -0.03,  # close 가 MA20w 보다 3% 이상 아래 (강한 reject)
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


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CACHE_DIR.glob("*.parquet"))
    print(f"심볼 {len(files)}개")

    # (low_gap_threshold, close_gate, hold_days) → list of short returns
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

        d = attach_weekly_ma20(df)

        cond_high_touch = d["high"] >= d["ma20w"]
        cond_slope = d["ma20w_slope_4w"] < 0
        entry = d["open"].shift(-1)

        for X in LOW_GAP_THRESHOLDS:
            cond_low_below = d["low"] <= d["ma20w"] * (1 - X)
            for gate_name, gate_value in CLOSE_GATES.items():
                if gate_value is None:
                    cond_close = pd.Series(True, index=d.index)
                elif gate_value == "below":
                    cond_close = d["close"] < d["ma20w"]
                else:
                    cond_close = d["close"] <= d["ma20w"] * (1 + gate_value)
                sig_raw = cond_high_touch & cond_low_below & cond_slope & cond_close
                if not sig_raw.any():
                    continue
                sig = dedup_signals(sig_raw, DEDUP_DAYS)
                for H in HOLD_DAYS_LIST:
                    exit_ = d["close"].shift(-(1 + H))
                    short_ret = -(exit_ / entry - 1)
                    s = short_ret[sig.fillna(False)].dropna()
                    if len(s) == 0:
                        continue
                    key = (X, gate_name, H)
                    results.setdefault(key, []).append(s)

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(files)}")

    rows = []
    for (X, gate_name, H), parts in results.items():
        s = pd.concat(parts)
        if len(s) < 30:
            continue
        s_capped = s.clip(lower=-1.0)
        rows.append({
            "MA20w_저점_갭_이상_pct": f"{X*100:.0f}%",
            "close_조건": gate_name,
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
        "MA20w_저점_갭_이상_pct", "close_조건", "숏보유_일"
    ])

    print()
    print("=" * 130)
    print("전체 결과:")
    print("=" * 130)
    print(out.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("close 조건 'close_무관' 만 비교 (hold 30일):")
    print("=" * 130)
    a = out[(out["close_조건"] == "close_무관") & (out["숏보유_일"] == 30)]
    print(a.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("close 조건 'close_lt_MA20w' 만 비교 (hold 30일):")
    print("=" * 130)
    b = out[(out["close_조건"] == "close_lt_MA20w") & (out["숏보유_일"] == 30)]
    print(b.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("close 조건 'close_lt_MA20w_minus_3pct' 만 비교 (hold 30일):")
    print("=" * 130)
    c = out[(out["close_조건"] == "close_lt_MA20w_minus_3pct") & (out["숏보유_일"] == 30)]
    print(c.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("Top 15 by 평균_숏수익_capped (표본 ≥ 50):")
    print("=" * 130)
    top = out[out["표본수"] >= 50].nlargest(15, "평균_숏수익_capped")
    print(top.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    out_path = ROOT / "scripts" / "out" / "short_wick_test_ma20w.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_path}")


if __name__ == "__main__":
    main()
