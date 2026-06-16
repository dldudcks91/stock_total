"""MA20에 N=15봉 2차 적합 — 4 케이스(상승추세/하방추세/하방반등/상방반전) 계수 분포 + 예시.

목적: 그랜빌 1법칙 검출에 2차 적합이 유효한지, 각 상황에서 계수가 어떻게 분포하는지 본다.

룰:
- 윈도우 = 최근 N=15봉의 MA20
- y = a*x^2 + b*x + c, x = 0..N-1
- 정규화: a_pct = a / y_mean * 100  (MA 평균 대비 % per bar^2)
            b_pct = b / y_mean * 100  (% per bar)
- vertex_x = -b / (2a),  vertex_pos = vertex_x / (N-1)  (윈도우 내 상대 위치)
- R²로 적합 품질 필터

분류 (R² >= 0.7 가정):
  case1_uptrend      : |a_pct| < 0.02, b_pct > +0.2
  case2_downtrend    : |a_pct| < 0.02, b_pct < -0.2
  case3_bounce_up    : a_pct > +0.04, vertex_pos in [0.3, 1.1]   (U자, vertex가 윈도우 중~후반)
  case4_bounce_down  : a_pct < -0.04, vertex_pos in [0.3, 1.1]   (∩자)
"""
import sys
from pathlib import Path
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

import random
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ROOT = Path(".").resolve()
CACHE = ROOT / "data" / "cache" / "kr"
OUT = ROOT / "scripts" / "out"

WINDOW = 15
MA_LEN = 20
R2_MIN = 0.70

# 분류 임계값 (정규화 단위: MA 평균 대비 %)
A_TREND_MAX = 0.02   # |a_pct| < 0.02면 거의 선형 (추세)
A_BOUNCE_MIN = 0.04  # |a_pct| > 0.04면 명확한 곡률 (반등/반전)
B_TREND_MIN = 0.20   # |b_pct| > 0.20면 명확한 기울기


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
        "a": float(a), "b": float(b), "c": float(c),
        "a_pct": float(a / y_mean * 100) if y_mean > 0 else float("nan"),
        "b_pct": float(b / y_mean * 100) if y_mean > 0 else float("nan"),
        "vertex_x": float(vertex_x),
        "vertex_pos": float(vertex_x / (n - 1)) if not np.isnan(vertex_x) else float("nan"),
        "r2": float(r2),
        "y_mean": y_mean,
    }


def classify(fit: dict) -> Optional[str]:
    if fit["r2"] < R2_MIN:
        return None
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
    return None


def load_ma20(ticker: str) -> Optional[pd.DataFrame]:
    p = CACHE / f"{ticker}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if df is None or df.empty or "Close" not in df.columns:
        return None
    df = df.sort_index()
    df["MA20"] = df["Close"].rolling(MA_LEN).mean()
    return df


def main():
    random.seed(42)
    files = sorted(CACHE.glob("[0-9]*.parquet"))
    tickers = [p.stem for p in files if len(p.stem) == 6 and p.stem.isdigit()]
    sample = random.sample(tickers, min(250, len(tickers)))
    print(f"sample size: {len(sample)}")

    # 케이스별 후보 누적
    rows = []  # 모든 분류된 fit
    for tk in sample:
        df = load_ma20(tk)
        if df is None or len(df) < 400:
            continue
        # 최근 2년만
        df = df.iloc[-500:]
        ma = df["MA20"].values
        idx = df.index
        # 매 시점 t에서 [t-WINDOW+1 .. t] 윈도우
        for i in range(WINDOW + MA_LEN, len(ma)):
            y = ma[i - WINDOW + 1: i + 1]
            if np.isnan(y).any():
                continue
            fit = fit_quadratic(y)
            cat = classify(fit)
            if cat is None:
                continue
            rows.append({
                "ticker": tk,
                "date": str(idx[i].date()),
                "category": cat,
                **fit,
            })

    df_all = pd.DataFrame(rows)
    if df_all.empty:
        print("no matches"); return

    csv_path = OUT / "_probe_ma_curvature_cases.csv"
    df_all.to_csv(csv_path, index=False)
    print(f"saved: {csv_path}  ({len(df_all)} rows)")

    # 케이스별 통계
    print("\n=== 케이스별 매칭 수 ===")
    print(df_all["category"].value_counts())

    print("\n=== 케이스별 계수 분포 (median / [p25, p75]) ===")
    stats = []
    for cat, g in df_all.groupby("category"):
        def fmt(s):
            return f"{s.median():+.4f} [{s.quantile(0.25):+.4f}, {s.quantile(0.75):+.4f}]"
        stats.append({
            "category": cat,
            "n": len(g),
            "a_pct": fmt(g["a_pct"]),
            "b_pct": fmt(g["b_pct"]),
            "vertex_pos": fmt(g["vertex_pos"].dropna()),
            "r2": fmt(g["r2"]),
        })
    stats_df = pd.DataFrame(stats)
    print(stats_df.to_string(index=False))

    # 각 케이스 best 예시 1개 선정 + 차트
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    case_order = ["case1_uptrend", "case2_downtrend", "case3_bounce_up", "case4_bounce_down"]
    title_kr = {
        "case1_uptrend":     "1. UPTREND  (|a| small, b>0)",
        "case2_downtrend":   "2. DOWNTREND  (|a| small, b<0)",
        "case3_bounce_up":   "3. BOUNCE UP  (a>0, U-shape, Granville #1)",
        "case4_bounce_down": "4. ROLL OVER  (a<0, n-shape, Granville #4)",
    }

    for ax, cat in zip(axes.flat, case_order):
        sub = df_all[df_all["category"] == cat].copy()
        if sub.empty:
            ax.set_title(f"{title_kr[cat]}  (no match)"); continue
        # best 선정: |a_pct| 큰 + r2 높은 케이스 우선 (반등군은 그게 명확함)
        if "bounce" in cat:
            sub["score"] = sub["a_pct"].abs() * sub["r2"]
        else:
            sub["score"] = sub["b_pct"].abs() * sub["r2"]
        # 같은 종목·같은 구간 여러 행 있을 수 있으니 종목당 best 1개
        sub = sub.sort_values("score", ascending=False).drop_duplicates("ticker").head(1)
        row = sub.iloc[0]
        tk, dt = row["ticker"], pd.Timestamp(row["date"])
        df = load_ma20(tk)
        # 윈도우 = dt 기준 직전 WINDOW봉
        end_loc = df.index.get_loc(dt)
        win_idx = df.index[end_loc - WINDOW + 1: end_loc + 1]
        win_y = df.loc[win_idx, "MA20"].values
        # 적합 곡선 (윈도우 내부)
        x = np.arange(WINDOW)
        a, b, c = row["a"], row["b"], row["c"]
        y_fit = a * x * x + b * x + c
        # 차트 = 윈도우 앞뒤 30봉 + MA20 + 윈도우 강조 + 적합 곡선
        ctx = df.iloc[max(0, end_loc - WINDOW - 20): end_loc + 20]
        ax.plot(ctx.index, ctx["Close"], color="lightgray", lw=1, label="Close")
        ax.plot(ctx.index, ctx["MA20"], color="steelblue", lw=1.5, label="MA20")
        ax.plot(win_idx, win_y, color="orange", lw=3, label=f"window (N={WINDOW})")
        ax.plot(win_idx, y_fit, color="red", lw=2, linestyle="--", label="quadratic fit")
        ax.axvline(dt, color="black", lw=0.8, alpha=0.3)
        ax.set_title(
            f"{title_kr[cat]}\n"
            f"{tk}  {dt.date()}  |  "
            f"a_pct={row['a_pct']:+.3f}, b_pct={row['b_pct']:+.3f}, "
            f"vertex_pos={row['vertex_pos']:+.2f}, R²={row['r2']:.3f}",
            fontsize=10,
        )
        ax.legend(loc="best", fontsize=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        ax.tick_params(axis="x", rotation=0, labelsize=8)
        ax.grid(alpha=0.3)

    fig.suptitle(
        f"MA20 quadratic fit cases  (window={WINDOW} bars, MA={MA_LEN}, R²≥{R2_MIN})",
        fontsize=12, fontweight="bold",
    )
    fig.tight_layout()
    out = OUT / "_probe_ma_curvature_cases.png"
    fig.savefig(out, dpi=100, bbox_inches="tight")
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
