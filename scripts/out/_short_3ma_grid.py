"""3개 MA × 깊이·반등 그리드 — 표본 확장 비교.

MA: MA20w (주봉 → 일봉 ffill) / MA100d / MA200d
깊이 임계: {20%, 25%, 30%}
반등기간: {10일, 20일}
hold: 7일 (단기 hold 확정)
진입가: MA (limit short)
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
CACHE = ROOT / "data" / "cache" / "crypto" / "1d"

DEPTHS = [0.20, 0.25, 0.30]
LOOKBACKS = [10, 20]
HOLD = 7
DEDUP = 20


def attach_mas(df):
    d = df.copy()
    d["dt"] = pd.to_datetime(d["timestamp"], unit="ms")
    w = (d.set_index("dt").resample("W-MON", label="left", closed="left")
         .agg({"close": "last"}).dropna())
    w["ma20w"] = w["close"].rolling(20, min_periods=20).mean()
    w["ma20w_slope"] = w["ma20w"] / w["ma20w"].shift(4) - 1
    wm = w[["ma20w", "ma20w_slope"]].shift(1).reindex(d["dt"].dt.normalize().values, method="ffill")
    d["ma20w"] = wm["ma20w"].values
    d["ma20w_slope"] = wm["ma20w_slope"].values
    d["ma100d"] = d["close"].rolling(100, min_periods=100).mean()
    d["ma200d"] = d["close"].rolling(200, min_periods=200).mean()
    d["ma100d_slope"] = d["ma100d"] / d["ma100d"].shift(50) - 1
    d["ma200d_slope"] = d["ma200d"] / d["ma200d"].shift(100) - 1
    return d


def dedup(sig, days):
    idx = np.where(sig)[0]
    if len(idx) == 0:
        return np.zeros_like(sig, dtype=bool)
    keep = [idx[0]]
    for i in idx[1:]:
        if i - keep[-1] >= days:
            keep.append(i)
    out = np.zeros_like(sig, dtype=bool)
    out[keep] = True
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CACHE.glob("*.parquet"))
    print(f"심볼 {len(files)}개\n")

    # (ma_label, depth, lookback) → list of short_returns
    results = {}
    for f in files:
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if len(df) < 300:
            continue
        df = df.sort_values("timestamp").reset_index(drop=True)
        df = df.iloc[200:].reset_index(drop=True)
        if len(df) < 100:
            continue
        d = attach_mas(df)
        n = len(d)

        for ma_label, ma_col, slope_col in [
            ("MA20w", "ma20w", "ma20w_slope"),
            ("MA100d", "ma100d", "ma100d_slope"),
            ("MA200d", "ma200d", "ma200d_slope"),
        ]:
            ma = d[ma_col]
            slope = d[slope_col]
            for X in DEPTHS:
                for N in LOOKBACKS:
                    low_min = d["low"].shift(1).rolling(N, min_periods=N).min()
                    sig = ((low_min <= ma * (1 - X)) & (d["high"] >= ma) & (slope < 0))
                    sig = dedup(sig.fillna(False).values, DEDUP)
                    rets = []
                    for t in np.where(sig)[0]:
                        if t + HOLD >= n:
                            continue
                        entry = ma.iloc[t]
                        exit_p = d["close"].iloc[t + HOLD]
                        if pd.isna(entry) or pd.isna(exit_p):
                            continue
                        ret = -(exit_p / entry - 1)
                        rets.append(max(ret, -1.0))
                    key = (ma_label, X, N)
                    results.setdefault(key, []).extend(rets)

    rows = []
    for (ma_label, X, N), rets in results.items():
        if not rets:
            continue
        s = pd.Series(rets)
        rows.append({
            "MA": ma_label,
            "깊이_pct": int(X * 100),
            "반등기간_일": N,
            "표본수": int(len(s)),
            "윈율": float((s > 0).mean()),
            "평균_숏수익": float(s.mean()),
            "중위_숏수익": float(s.median()),
            "p25": float(s.quantile(0.25)),
            "p75": float(s.quantile(0.75)),
            "표준편차": float(s.std()),
            "최대손실": float(s.min()),
            "Sharpe": float(s.mean() / s.std()) if s.std() > 0 else np.nan,
            "squeeze_플20이상_손실_비율": float((s <= -0.20).mean()),
        })

    out = pd.DataFrame(rows).sort_values(["MA", "깊이_pct", "반등기간_일"])
    print("=" * 130)
    print("3개 MA × 깊이 × 반등기간 (hold 7일, 진입 = MA limit short):")
    print("=" * 130)
    print(out.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    out_path = ROOT / "scripts" / "out" / "short_3ma_depth_grid.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_path}")


if __name__ == "__main__":
    main()
