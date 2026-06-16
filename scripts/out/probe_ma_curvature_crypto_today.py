"""오늘 시점 — 모든 Bitget USDT-M 코인의 MA20 quadratic fit 계수.

각 코인의 마지막(=오늘) 일봉을 기준으로 최근 N=15봉의 MA20 에 2차 적합:
y = a*x^2 + b*x + c, x = 0..N-1
정규화: a_pct = a / y_mean * 100  (% per bar^2)
        b_pct = b / y_mean * 100  (% per bar)

분류 임계값은 KR 케이스 스크립트와 동일.
"""
import sys
from pathlib import Path
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from typing import Optional
import numpy as np
import pandas as pd

ROOT = Path(".").resolve()
CACHE = ROOT / "data" / "cache" / "crypto" / "1d"
OUT = ROOT / "scripts" / "out"

WINDOW = 15
MA_LEN = 20
R2_MIN = 0.70
A_TREND_MAX = 0.02
A_BOUNCE_MIN = 0.04
B_TREND_MIN = 0.20


def fit_quadratic(y: np.ndarray) -> dict:
    n = len(y)
    x = np.arange(n, dtype=float)
    a, b, c = np.polyfit(x, y, 2)
    y_pred = a * x * x + b * x + c
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    vertex_x = -b / (2 * a) if abs(a) > 1e-15 else float("nan")
    y_mean = float(y.mean())
    return {
        "a_pct": float(a / y_mean * 100) if y_mean > 0 else float("nan"),
        "b_pct": float(b / y_mean * 100) if y_mean > 0 else float("nan"),
        "vertex_x": float(vertex_x),
        "vertex_pos": float(vertex_x / (n - 1)) if not np.isnan(vertex_x) else float("nan"),
        "r2": float(r2),
        "y_mean": y_mean,
    }


def classify(fit: dict) -> Optional[str]:
    if fit["r2"] < R2_MIN:
        return "noisy"
    a = fit["a_pct"]
    b = fit["b_pct"]
    vp = fit["vertex_pos"]
    if abs(a) < A_TREND_MAX and b > B_TREND_MIN:
        return "case1_uptrend"
    if abs(a) < A_TREND_MAX and b < -B_TREND_MIN:
        return "case2_downtrend"
    if a > A_BOUNCE_MIN and 0.3 <= vp <= 1.1:
        return "case3_bounce_up"
    if a < -A_BOUNCE_MIN and 0.3 <= vp <= 1.1:
        return "case4_bounce_down"
    return "ambiguous"


def main():
    files = sorted(CACHE.glob("*.parquet"))
    rows = []
    last_dates = []
    for p in files:
        sym = p.stem
        try:
            df = pd.read_parquet(p)
        except Exception:
            continue
        if df is None or df.empty or "close" not in df.columns:
            continue
        df = df.sort_values("timestamp") if "timestamp" in df.columns else df.sort_index()
        # timestamp ms → datetime
        if "timestamp" in df.columns:
            df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
            df = df.set_index("dt")
        df["MA20"] = df["close"].rolling(MA_LEN).mean()
        if len(df) < MA_LEN + WINDOW:
            continue
        y = df["MA20"].values[-WINDOW:]
        if np.isnan(y).any():
            continue
        fit = fit_quadratic(y)
        cat = classify(fit)
        last_dt = df.index[-1]
        last_dates.append(last_dt)
        last_close = float(df["close"].iloc[-1])
        last_ma20 = float(df["MA20"].iloc[-1])
        rows.append({
            "symbol": sym,
            "last_date": str(last_dt.date()),
            "close": last_close,
            "ma20": last_ma20,
            "px_vs_ma20_pct": (last_close / last_ma20 - 1) * 100,
            "category": cat,
            **fit,
        })

    out_df = pd.DataFrame(rows)
    if out_df.empty:
        print("no rows"); return

    # 정렬 보조: category 우선순위
    order_map = {
        "case3_bounce_up": 0,    # 1법칙 (관심)
        "case1_uptrend": 1,
        "case4_bounce_down": 2,  # 4법칙
        "case2_downtrend": 3,
        "ambiguous": 4,
        "noisy": 5,
    }
    out_df["_ord"] = out_df["category"].map(order_map).fillna(9).astype(int)
    out_df = out_df.sort_values(["_ord", "a_pct"], ascending=[True, False]).drop(columns=["_ord"])

    csv_path = OUT / "_probe_ma_curvature_crypto_today.csv"
    out_df.to_csv(csv_path, index=False)

    print(f"symbols evaluated: {len(out_df)}")
    print(f"latest data date range: min={min(last_dates).date()}  max={max(last_dates).date()}")
    print()
    print("=== category 분포 ===")
    print(out_df["category"].value_counts().to_string())
    print()
    print(f"saved: {csv_path}")

    # 케이스별 분포 (KR과 비교용)
    print("\n=== 케이스별 계수 분포 (median [p25, p75]) ===")
    stats = []
    for cat, g in out_df.groupby("category"):
        if cat in ("noisy", "ambiguous"): continue
        def fmt(s):
            s = s.dropna()
            if s.empty: return "-"
            return f"{s.median():+.4f} [{s.quantile(0.25):+.4f}, {s.quantile(0.75):+.4f}]"
        stats.append({
            "category": cat, "n": len(g),
            "a_pct": fmt(g["a_pct"]),
            "b_pct": fmt(g["b_pct"]),
            "vertex_pos": fmt(g["vertex_pos"]),
            "r2": fmt(g["r2"]),
        })
    print(pd.DataFrame(stats).to_string(index=False))

    # case3 (1법칙) top 20
    print("\n=== case3_bounce_up (그랜빌 1법칙) TOP 20  — a_pct 큰 순 ===")
    c3 = out_df[out_df["category"] == "case3_bounce_up"].head(20).copy()
    show = c3[["symbol", "last_date", "close", "ma20", "px_vs_ma20_pct",
               "a_pct", "b_pct", "vertex_pos", "r2"]]
    print(show.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))

    # case1 top 10 (참고)
    print("\n=== case1_uptrend (참고) TOP 10  — b_pct 큰 순 ===")
    c1 = out_df[out_df["category"] == "case1_uptrend"].sort_values("b_pct", ascending=False).head(10)
    show1 = c1[["symbol", "last_date", "close", "ma20", "px_vs_ma20_pct",
                "a_pct", "b_pct", "r2"]]
    print(show1.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))


if __name__ == "__main__":
    main()
