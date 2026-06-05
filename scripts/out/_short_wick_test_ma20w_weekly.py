"""주봉 단위 wick test of MA20w 숏 백테스트.

룰 (주봉 버전):
- 주봉 candle t 의 high_w 가 MA20w 에 닿음 (high_w >= MA20w)
- 주봉 candle t 의 low_w 가 MA20w 보다 X% 이상 아래 (low_w <= MA20w * (1-X))
- MA20w slope_4w < 0
- → 다음 주봉 시가에 숏, N주 hold 후 청산

그리드:
- 임계 X (MA20w - 저점 / MA20w): {0.05, 0.10, 0.15, 0.20, 0.30}
- close 게이트: {무관, close_w < MA20w, close_w < MA20w * 0.97}
- 주봉 hold: {2, 4, 8, 12} 주

신규 상장 30주 컷 (MA20w 안정화).
주봉 4주 dedup.
강제청산 -100% 캡.
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
HOLD_WEEKS_LIST = [2, 4, 8, 12]
DEDUP_WEEKS = 4

CLOSE_GATES = {
    "close_무관": None,
    "close_lt_MA20w": "below",
    "close_lt_MA20w_minus_3pct": -0.03,
}


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """일봉 → 주봉 변환 + MA20w 계산."""
    d = df.copy()
    d["dt"] = pd.to_datetime(d["timestamp"], unit="ms")
    weekly = (
        d.set_index("dt")
        .resample("W-MON", label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    weekly["ma20w"] = weekly["close"].rolling(20, min_periods=20).mean()
    weekly["ma20w_slope_4w"] = weekly["ma20w"] / weekly["ma20w"].shift(4) - 1
    return weekly.reset_index(drop=False)


def dedup_signals(sig: pd.Series, dedup_weeks: int) -> pd.Series:
    idx = np.where(sig.fillna(False).values)[0]
    if len(idx) == 0:
        return sig
    keep = [idx[0]]
    for i in idx[1:]:
        if i - keep[-1] >= dedup_weeks:
            keep.append(i)
    out = pd.Series(False, index=sig.index)
    out.iloc[keep] = True
    return out


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
        if len(df) < 250:
            continue
        df = df.sort_values("timestamp").reset_index(drop=True)
        w = to_weekly(df)
        # 신규 상장 30주(약 7개월) 컷
        w = w.iloc[30:].reset_index(drop=True)
        if len(w) < 30:
            continue

        cond_high_touch = w["high"] >= w["ma20w"]
        cond_slope = w["ma20w_slope_4w"] < 0
        entry = w["open"].shift(-1)

        for X in LOW_GAP_THRESHOLDS:
            cond_low_below = w["low"] <= w["ma20w"] * (1 - X)
            for gate_name, gate_value in CLOSE_GATES.items():
                if gate_value is None:
                    cond_close = pd.Series(True, index=w.index)
                elif gate_value == "below":
                    cond_close = w["close"] < w["ma20w"]
                else:
                    cond_close = w["close"] <= w["ma20w"] * (1 + gate_value)
                sig_raw = cond_high_touch & cond_low_below & cond_slope & cond_close
                if not sig_raw.any():
                    continue
                sig = dedup_signals(sig_raw, DEDUP_WEEKS)
                for H in HOLD_WEEKS_LIST:
                    exit_ = w["close"].shift(-(1 + H))
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
            "숏보유_주": H,
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
        "MA20w_저점_갭_이상_pct", "close_조건", "숏보유_주"
    ])

    print()
    print("=" * 130)
    print("전체 결과 (주봉 단위):")
    print("=" * 130)
    print(out.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("close 조건 'close_무관' 만 비교 (hold 4주):")
    print("=" * 130)
    a = out[(out["close_조건"] == "close_무관") & (out["숏보유_주"] == 4)]
    print(a.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("close 조건 'close_무관' 만 비교 (hold 8주):")
    print("=" * 130)
    b = out[(out["close_조건"] == "close_무관") & (out["숏보유_주"] == 8)]
    print(b.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("close 조건 'close_lt_MA20w' 만 비교 (hold 4주):")
    print("=" * 130)
    c = out[(out["close_조건"] == "close_lt_MA20w") & (out["숏보유_주"] == 4)]
    print(c.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("Top 15 by 평균_숏수익_capped (표본 ≥ 30):")
    print("=" * 130)
    top = out[out["표본수"] >= 30].nlargest(15, "평균_숏수익_capped")
    print(top.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    out_path = ROOT / "scripts" / "out" / "short_wick_test_ma20w_weekly.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_path}")


if __name__ == "__main__":
    main()
