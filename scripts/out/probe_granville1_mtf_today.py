"""오늘 시점 — 코인별 그랜빌 1법칙 후보 (주봉 10선 우선, 없으면 일봉 20선).

룰:
1) 주봉 MA10 사용 가능 (≥ 10주 + 윈도우 N_W=10 → 약 25주 데이터) → 1w, MA10, N=10
2) 불가능하면 일봉 MA20 사용 (≥ 20일 + 윈도우 N_D=15) → 1d, MA20, N=15

검출 룰 (보강):
- a_pct  ≥ A_MIN     (U자 곡률 충분, TF별 다름)
- vertex_pos < 0.85  (vertex가 윈도우 끝에 너무 가까운 건 제외 — 아직 vertex 도달도 안 한 false positive 차단)
- **MA[-1] > MA[-3]** (실측: MA가 실제로 위로 돌아섰음 — BILLUSDT 같은 "감속 중 하락" 제거)
- R² ≥ 0.85

가격이 MA 근처에 있어야 1법칙 (이미 한참 위면 추격 자리, 1법칙 X):
- |px_vs_ma| ≤ 10%
"""
import sys
from pathlib import Path
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from typing import Optional
import numpy as np
import pandas as pd

from data.resample import load as load_crypto

ROOT = Path(".").resolve()
CACHE = ROOT / "data" / "cache" / "crypto" / "1d"
OUT = ROOT / "scripts" / "out"

# TF별 파라미터
N_WEEK = 10        # 주봉 윈도우
MA_WEEK = 10       # 주봉 MA
N_DAY = 15         # 일봉 윈도우
MA_DAY = 20        # 일봉 MA

# 검출 임계값 (TF별)
A_MIN_W = 0.20     # 주봉: 곡률 더 크게 (변동성 크고 봉수 적음)
A_MIN_D = 0.07     # 일봉: 기존
R2_MIN = 0.85
VERTEX_MAX = 0.85  # vertex가 윈도우의 0.85 이상이면 제외 (아직 vertex 도달 X)
PX_GAP_MAX = 10.0  # |px_vs_ma| <= 10%


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
        "vertex_pos": float(vertex_x / (n - 1)) if not np.isnan(vertex_x) else float("nan"),
        "r2": float(r2),
    }


def check_bounce(ma_series: np.ndarray, fit: dict, a_min: float) -> Optional[str]:
    """1법칙 후보면 'pass', 아니면 reject 사유 문자열."""
    if fit["r2"] < R2_MIN:
        return f"low_r2({fit['r2']:.2f})"
    if fit["a_pct"] < a_min:
        return f"low_a({fit['a_pct']:.3f})"
    if not (0.30 <= fit["vertex_pos"] <= VERTEX_MAX):
        return f"vertex_out({fit['vertex_pos']:.2f})"
    # 실측: MA[-1] > MA[-3] (위로 돌아섰는지)
    if ma_series[-1] <= ma_series[-3]:
        return f"ma_not_rising({(ma_series[-1]/ma_series[-3]-1)*100:+.2f}%)"
    return "pass"


def eval_symbol(sym: str) -> Optional[dict]:
    # 1) 주봉 MA10 시도
    try:
        df_w = load_crypto(sym, "1w")
    except Exception:
        df_w = None
    if df_w is not None and len(df_w) >= MA_WEEK + N_WEEK:
        df_w = df_w.copy()
        df_w["MA"] = df_w["close"].rolling(MA_WEEK).mean()
        ma = df_w["MA"].values[-N_WEEK:]
        if not np.isnan(ma).any():
            last_close = float(df_w["close"].iloc[-1])
            last_ma = float(df_w["MA"].iloc[-1])
            fit = fit_quadratic(ma)
            ma_slope_3 = (ma[-1] / ma[-3] - 1) * 100
            verdict = check_bounce(ma, fit, A_MIN_W)
            return {
                "symbol": sym, "tf": "1w", "ma_len": MA_WEEK, "window": N_WEEK,
                "last_date": str(df_w.index[-1].date()) if hasattr(df_w.index[-1], "date")
                              else str(pd.Timestamp(df_w["timestamp"].iloc[-1], unit="ms").date()),
                "close": last_close, "ma": last_ma,
                "px_vs_ma_pct": (last_close / last_ma - 1) * 100,
                "ma_slope_last3_pct": ma_slope_3,
                "verdict": verdict, **fit,
            }
    # 2) 일봉 MA20 fallback
    try:
        df_d = load_crypto(sym, "1d")
    except Exception:
        return None
    if df_d is None or len(df_d) < MA_DAY + N_DAY:
        return None
    df_d = df_d.copy()
    df_d["MA"] = df_d["close"].rolling(MA_DAY).mean()
    ma = df_d["MA"].values[-N_DAY:]
    if np.isnan(ma).any():
        return None
    last_close = float(df_d["close"].iloc[-1])
    last_ma = float(df_d["MA"].iloc[-1])
    fit = fit_quadratic(ma)
    ma_slope_3 = (ma[-1] / ma[-3] - 1) * 100
    verdict = check_bounce(ma, fit, A_MIN_D)
    return {
        "symbol": sym, "tf": "1d", "ma_len": MA_DAY, "window": N_DAY,
        "last_date": str(df_d.index[-1].date()) if hasattr(df_d.index[-1], "date")
                      else str(pd.Timestamp(df_d["timestamp"].iloc[-1], unit="ms").date()),
        "close": last_close, "ma": last_ma,
        "px_vs_ma_pct": (last_close / last_ma - 1) * 100,
        "ma_slope_last3_pct": ma_slope_3,
        "verdict": verdict, **fit,
    }


def main():
    files = sorted(CACHE.glob("*.parquet"))
    rows = []
    for p in files:
        sym = p.stem
        try:
            row = eval_symbol(sym)
        except Exception as e:
            continue
        if row is not None:
            rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        print("no rows"); return

    csv_path = OUT / "_probe_granville1_mtf_today.csv"
    df.to_csv(csv_path, index=False)
    print(f"symbols evaluated: {len(df)}")
    print(f"TF 사용: {df['tf'].value_counts().to_dict()}")
    print(f"\n=== verdict 분포 ===")
    print(df["verdict"].apply(lambda v: v if v == "pass" else v.split("(")[0]).value_counts().to_string())

    # pass 만
    passed = df[df["verdict"] == "pass"].copy()
    # 가격 갭 추가 필터
    passed_clean = passed[passed["px_vs_ma_pct"].abs() <= PX_GAP_MAX].copy()
    print(f"\n=== 1법칙 후보 ===")
    print(f"  pass (모두):          {len(passed)}")
    print(f"  pass + |gap|≤{PX_GAP_MAX}%:  {len(passed_clean)}")

    print(f"\n=== TF별 후보 (gap 필터 후) ===")
    print(passed_clean["tf"].value_counts().to_string())

    # 정렬: TF별, a_pct 큰 순
    passed_clean = passed_clean.sort_values(["tf", "a_pct"], ascending=[True, False])
    print(f"\n=== 주봉 MA10 후보 (TF=1w) ===")
    sub_w = passed_clean[passed_clean["tf"] == "1w"]
    if not sub_w.empty:
        show = sub_w[["symbol", "last_date", "close", "ma", "px_vs_ma_pct",
                      "a_pct", "b_pct", "vertex_pos", "ma_slope_last3_pct", "r2"]]
        print(show.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))
    else:
        print("(none)")

    print(f"\n=== 일봉 MA20 fallback 후보 (TF=1d) ===")
    sub_d = passed_clean[passed_clean["tf"] == "1d"]
    if not sub_d.empty:
        show = sub_d[["symbol", "last_date", "close", "ma", "px_vs_ma_pct",
                      "a_pct", "b_pct", "vertex_pos", "ma_slope_last3_pct", "r2"]]
        print(show.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))
    else:
        print("(none)")

    print(f"\nsaved: {csv_path}")


if __name__ == "__main__":
    main()
