"""오늘 시점 — KR/US 종목의 그랜빌 1법칙 후보 (5개 TF/MA 조합 통합).

코인 버전 (probe_granville1_all_tf_today.py) 의 stocks 판본.
mtf_loader 로 자산별 1D 정규화 → 1W/1M 메모리 리샘플.

룰: N=10 통일, a_min=0.10 통일 (코인과 동일).
"""
import sys
from pathlib import Path
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from typing import Optional
import numpy as np
import pandas as pd

from scripts._common.mtf_loader import load_multi_tf

ROOT = Path(".").resolve()
OUT = ROOT / "scripts" / "out"

# N=10 통일, a_min=0.10 단일 임계값
N_WIN = 10
A_MIN = 0.10
COMBOS = [
    ("1D", 20, N_WIN, A_MIN, "1d_MA20"),
    ("1W", 10, N_WIN, A_MIN, "1w_MA10"),
    ("1W", 20, N_WIN, A_MIN, "1w_MA20"),
    ("1M", 10, N_WIN, A_MIN, "1M_MA10"),
    ("1M", 20, N_WIN, A_MIN, "1M_MA20"),
]
R2_MIN = 0.85
VERTEX_LO, VERTEX_HI = 0.30, 0.85
PX_GAP_MAX = 10.0


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


def eval_combo(tf_dict: dict, tf: str, ma_len: int, window: int, a_min: float, label: str) -> Optional[dict]:
    df = tf_dict.get(tf)
    if df is None or df.empty or len(df) < ma_len + window:
        return None
    df = df.copy()
    df["MA"] = df["close"].rolling(ma_len).mean()
    ma = df["MA"].values[-window:]
    if np.isnan(ma).any():
        return None
    last_close = float(df["close"].iloc[-1])
    last_ma = float(df["MA"].iloc[-1])
    fit = fit_quadratic(ma)
    ma_slope_3 = (ma[-1] / ma[-3] - 1) * 100
    px_gap = (last_close / last_ma - 1) * 100

    if fit["r2"] < R2_MIN:
        verdict = "low_r2"
    elif fit["a_pct"] < a_min:
        verdict = "low_a"
    elif not (VERTEX_LO <= fit["vertex_pos"] <= VERTEX_HI):
        verdict = "vertex_out"
    elif ma[-1] <= ma[-3]:
        verdict = "ma_not_rising"
    else:
        verdict = "pass"

    return {
        "combo": label, "tf": tf, "ma_len": ma_len, "window": window,
        "last_date": str(df.index[-1].date()),
        "close": last_close, "ma": last_ma, "px_vs_ma_pct": px_gap,
        "ma_slope_last3_pct": ma_slope_3,
        "verdict": verdict, **fit,
    }


def evaluate_asset(asset: str) -> pd.DataFrame:
    cache_dir = ROOT / "data" / "cache" / asset
    if asset == "kr":
        # 6자리 숫자만
        symbols = sorted(p.stem for p in cache_dir.glob("*.parquet")
                         if len(p.stem) == 6 and p.stem.isdigit())
    else:
        symbols = sorted(p.stem for p in cache_dir.glob("*.parquet"))

    rows = []
    failed = 0
    for sym in symbols:
        try:
            tfs = load_multi_tf(asset, sym)
        except Exception:
            failed += 1
            continue
        for tf, ma_len, window, a_min, label in COMBOS:
            try:
                row = eval_combo(tfs, tf, ma_len, window, a_min, label)
            except Exception:
                continue
            if row is not None:
                row["symbol"] = sym
                rows.append(row)
    print(f"[{asset}] symbols={len(symbols)}, failed_load={failed}, rows={len(rows)}")
    return pd.DataFrame(rows)


def report(asset: str, df: pd.DataFrame):
    if df.empty:
        print(f"[{asset}] no rows"); return
    csv_path = OUT / f"_probe_granville1_all_tf_today_{asset}.csv"
    df.to_csv(csv_path, index=False)

    print(f"\n========== {asset.upper()} ==========")
    print(f"=== 조합별 평가 가능 수 ===")
    print(df.groupby("combo").size().to_string())

    print(f"\n=== 조합별 verdict 분포 ===")
    pv = df.pivot_table(index="combo", columns="verdict", values="symbol", aggfunc="count", fill_value=0)
    print(pv.to_string())

    passed = df[df["verdict"] == "pass"].copy()
    passed_clean = passed[passed["px_vs_ma_pct"].abs() <= PX_GAP_MAX].copy()
    print(f"\n=== 1법칙 후보 ===")
    print(f"  pass (모두):          {len(passed)}")
    print(f"  pass + |gap|≤{PX_GAP_MAX}%:  {len(passed_clean)}")

    for tf, ma_len, window, a_min, label in COMBOS:
        sub = passed_clean[passed_clean["combo"] == label].sort_values("a_pct", ascending=False)
        # 상위 20개만
        n_show = min(20, len(sub))
        print(f"\n=== {label}  후보 (n={len(sub)}, top {n_show}) ===")
        if sub.empty:
            print("(none)"); continue
        show = sub.head(n_show)[["symbol", "last_date", "close", "ma", "px_vs_ma_pct",
                                  "a_pct", "b_pct", "vertex_pos", "ma_slope_last3_pct", "r2"]]
        print(show.to_string(index=False, float_format=lambda v: f"{v:+.4f}"))

    # 다중 TF 동시 통과
    multi = passed_clean.groupby("symbol")["combo"].apply(list).reset_index()
    multi["n_combos"] = multi["combo"].apply(len)
    multi = multi[multi["n_combos"] >= 2].sort_values("n_combos", ascending=False)
    print(f"\n=== {asset.upper()} 2개 이상 조합 동시 통과 (멀티 TF 정합) ===")
    if multi.empty:
        print("(none)")
    else:
        for _, r in multi.iterrows():
            print(f"  {r['symbol']:12s}  {r['n_combos']}개:  {', '.join(r['combo'])}")

    print(f"\nsaved: {csv_path}")


def main():
    for asset in ["kr", "us"]:
        df = evaluate_asset(asset)
        report(asset, df)


if __name__ == "__main__":
    main()
