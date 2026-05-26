"""v3 점수의 차별력 추가 검증.

기존 백테스트 parquet 을 재사용해 다음을 검증:
1. 점수 vs baseline 초과수익률 (alpha)
2. 점수 분포 (얼마나 많은 종목이 어느 점수대?)
3. 양극화 패턴 (mean vs median 갭, 극단 outlier 영향)
4. Threshold 별 sharpe / 샘플수 trade-off
5. v2 → v3 가 어디서 개선되었나 (지표별 기여도)
"""
from __future__ import annotations

import sys
from pathlib import Path

import argparse

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.stdout.reconfigure(encoding="utf-8")

# Default: 최신 kr_backtest_all_*.parquet 또는 (없으면) 옛 kr_backtest_numeric_*.parquet
OUT_DIR = ROOT / "scripts" / "out"
HOLD = 60


def _default_bt_path() -> Path:
    candidates = sorted(OUT_DIR.glob("kr_backtest_all_*.parquet"), reverse=True)
    if candidates:
        return candidates[0]
    candidates = sorted(OUT_DIR.glob("kr_backtest_numeric_*.parquet"), reverse=True)
    if candidates:
        return candidates[0]
    return OUT_DIR / "kr_backtest_all_<latest>.parquet"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bt-path", type=Path, default=None,
                    help="백테스트 결과 parquet 경로 (default: 최신 kr_backtest_all_*.parquet)")
    args = ap.parse_args()
    bt_path = args.bt_path or _default_bt_path()
    print(f"[v3_score_validation] reading {bt_path}\n")
    bt = pd.read_parquet(bt_path)
    sub = bt.dropna(subset=[f"fwd_ret_{HOLD}"]).copy()
    baseline_mean = sub[f"fwd_ret_{HOLD}"].mean()
    baseline_med = sub[f"fwd_ret_{HOLD}"].median()
    baseline_win = (sub[f"fwd_ret_{HOLD}"] > 0).mean()
    print(f"=== v3 점수 차별력 검증 (D+{HOLD}) ===\n")
    print(f"Baseline (전체 {len(sub):,}): mean {baseline_mean*100:+.2f}%, median {baseline_med*100:+.2f}%, win {baseline_win*100:.1f}%\n")

    # 1) 점수 분포
    print("─── 1. v3 점수 분포 ───")
    for name, col in (("PULLBACK", "pb_score_v3"), ("CHASE", "ch_score_v3")):
        s = sub[col]
        print(f"\n[{name}] mean {s.mean():.1f} / median {s.median():.0f} / max {s.max():.0f} / std {s.std():.1f}")
        bins = [-50, 0, 10, 20, 30, 40, 50, 60, 100]
        cuts = pd.cut(s, bins=bins).value_counts().sort_index()
        for interval, n in cuts.items():
            print(f"  {interval}: {n:,} ({n/len(s)*100:.1f}%)")

    # 2) Threshold sweep — 더 촘촘히
    print("\n\n─── 2. Threshold sweep (촘촘) ───")
    for name, col in (("PULLBACK", "pb_score_v3"), ("CHASE", "ch_score_v3")):
        print(f"\n[{name}]")
        print(f"  {'th':>5} {'n':>7} {'mean%':>8} {'med%':>8} {'win%':>7} {'std%':>7} {'sharpe':>7} {'alpha%':>8}")
        for th in range(0, int(sub[col].max()) + 1, 5):
            cohort = sub[sub[col] >= th]
            if len(cohort) < 50:
                continue
            r = cohort[f"fwd_ret_{HOLD}"]
            mean = r.mean()
            med = r.median()
            win = (r > 0).mean()
            std = r.std()
            sharpe = mean / std if std > 0 else 0
            alpha = mean - baseline_mean
            print(f"  {th:>5} {len(r):>7,} {mean*100:>+7.2f}% {med*100:>+7.2f}% "
                  f"{win*100:>6.1f}% {std*100:>6.2f}% {sharpe:>7.3f} {alpha*100:>+7.2f}%")

    # 3) 양극화 분석 — outlier 영향
    print("\n\n─── 3. 양극화 / outlier 영향 ───")
    for name, col, th in (("PULLBACK", "pb_score_v3", 45), ("CHASE", "ch_score_v3", 13)):
        cohort = sub[sub[col] >= th]
        if cohort.empty:
            continue
        r = cohort[f"fwd_ret_{HOLD}"]
        # outlier 제거 (상하위 5%)
        p5, p95 = r.quantile([0.05, 0.95])
        r_trim = r[(r >= p5) & (r <= p95)]
        print(f"\n[{name}] threshold ≥{th} (n={len(r):,})")
        print(f"  원본       : mean {r.mean()*100:+.2f}%, median {r.median()*100:+.2f}%, std {r.std()*100:.2f}%")
        print(f"  outlier 제거: mean {r_trim.mean()*100:+.2f}%, median {r_trim.median()*100:+.2f}%, std {r_trim.std()*100:.2f}%")
        print(f"  P5  : {p5*100:+.2f}%")
        print(f"  P25 : {r.quantile(0.25)*100:+.2f}%")
        print(f"  P75 : {r.quantile(0.75)*100:+.2f}%")
        print(f"  P95 : {p95*100:+.2f}%")

    # 4) 지표별 D+60 평균 수익률 (단일 변수 효과)
    print("\n\n─── 4. 핵심 지표 단일 효과 (D+60 평균) ───")
    for indicator, bins, labels in [
        ("ret_90d", [-np.inf, 0, 0.1, 0.3, 0.5, 1.0, np.inf], ["<0", "0~10%", "10~30%", "30~50%", "50~100%", ">100%"]),
        ("ret_30d", [-np.inf, -0.05, 0, 0.05, 0.15, 0.30, 0.50, np.inf], ["<-5%", "-5~0", "0~5%", "5~15%", "15~30%", "30~50%", ">50%"]),
        ("from_high_1y", [-np.inf, -0.5, -0.3, -0.15, -0.05, 0, np.inf], ["<-50%", "-50~-30%", "-30~-15%", "-15~-5%", "-5~0%", "≥0%"]),
        ("vol_recent_vs_prior", [0, 0.5, 0.8, 1.2, 1.5, 2.0, np.inf], ["<0.5", "0.5~0.8", "0.8~1.2", "1.2~1.5", "1.5~2.0", ">2.0"]),
    ]:
        sub_i = sub.dropna(subset=[indicator])
        sub_i["bin"] = pd.cut(sub_i[indicator], bins=bins, labels=labels)
        g = sub_i.groupby("bin", observed=True)[f"fwd_ret_{HOLD}"].agg(["count", "mean", "median"])
        g["mean_pct"] = (g["mean"] * 100).round(2)
        g["med_pct"] = (g["median"] * 100).round(2)
        g["vs_baseline"] = ((g["mean"] - baseline_mean) * 100).round(2)
        print(f"\n[{indicator}] D+{HOLD} 평균")
        print(g[["count", "mean_pct", "med_pct", "vs_baseline"]].to_string())

    # 5) recent_strong_bull_10d / bull_stack 효과
    print("\n\n─── 5. Binary 지표 효과 ───")
    for ind in ["recent_strong_bull_10d", "bull_stack", "bear_stack"]:
        for val in (0, 1):
            cohort = sub[sub[ind] == val]
            if len(cohort) < 100:
                continue
            r = cohort[f"fwd_ret_{HOLD}"]
            print(f"  {ind}={val}: n={len(r):,}, mean {r.mean()*100:+.2f}%, win {(r>0).mean()*100:.1f}%, vs baseline {((r.mean()-baseline_mean)*100):+.2f}%p")


if __name__ == "__main__":
    main()
