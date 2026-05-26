"""주식 (KR/US) 일봉 백테스트 harness — 자산 무관, 전략 plug-in.

기존 ``scripts/misc/kr_backtest_numeric.backtest()`` 의 일반화:
  - cache_dir 와 glob pattern 으로 자산별 캐시 위치 흡수
  - scoring_fns dict 로 여러 전략을 한 번에 채점 (데이터 로드 1회)
  - hold_periods 별 fwd_ret 계산
  - extra_cols 로 결과에 포함할 indicator 컬럼 선택

사용 (예시):
    from scripts._common.backtest_runner import run_backtest, analyze_threshold_multi
    from scripts._common.indicators import compute_indicators, compute_weekly_acc
    from scripts.kr.trend_pullback.scoring import score_pullback_v3
    from scripts.kr.trend_chase.scoring import score_chase_v5_1

    bt = run_backtest(
        cache_dir=Path("data/cache/kr"),
        glob_pattern="[0-9]*.parquet",
        start=pd.Timestamp("2025-11-26"), end=pd.Timestamp("2026-05-26"),
        scoring_fns={"pb_v3": score_pullback_v3, "ch_v51": score_chase_v5_1},
        hold_periods=(5, 10, 20, 30, 60),
    )
    analyze_threshold_multi(bt, "pb_v3", 45, "PB v3")
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Iterable, Optional

import numpy as np
import pandas as pd

from scripts._common.indicators import compute_indicators, compute_weekly_acc


# ─────────────────────────────────────────────────────────────
# Backtest
# ─────────────────────────────────────────────────────────────
def run_backtest(
    cache_dir: Path,
    start: pd.Timestamp,
    end: pd.Timestamp,
    scoring_fns: Dict[str, Callable[[pd.DataFrame], pd.Series]],
    *,
    glob_pattern: str = "[0-9]*.parquet",
    hold_periods: Iterable[int] = (5, 10, 20, 30, 60),
    indicators_fn: Callable[[pd.DataFrame], pd.DataFrame] = compute_indicators,
    weekly_acc_fn: Optional[Callable[[pd.DataFrame], pd.Series]] = compute_weekly_acc,
    extra_cols: Optional[list] = None,
    min_bars: int = 120,
    verbose: bool = True,
) -> pd.DataFrame:
    """모든 종목 × 일자 × scoring_fns 채점 + fwd_ret 측정.

    Args:
      cache_dir     : 자산 캐시 디렉터리 (e.g. data/cache/kr)
      start, end    : 백테스트 채점 기간 (inclusive)
      scoring_fns   : ``{score_col: fn(df) -> Series}`` — fn 은 indicators 가 add 된
                      df 를 받아 행 단위 점수 Series 반환.
      glob_pattern  : 캐시 파일 패턴 (KR: "[0-9]*.parquet", US: "*.parquet" 등)
      hold_periods  : ``fwd_ret_{h}`` 컬럼들로 추가될 holding 기간
      indicators_fn : compute_indicators (KR/US 공통). None 이면 적용 X.
      weekly_acc_fn : compute_weekly_acc — 주봉 acc_w 컬럼 추가. None 이면 skip.
      extra_cols    : 결과에 포함할 indicator 컬럼 이름들. None 이면 default set.
      min_bars      : 종목당 최소 데이터 길이 (이 미만은 skip).

    Returns:
      long-format DataFrame: ``[date, symbol, <score_cols>, <extra_cols>, fwd_ret_*]``
    """
    syms = sorted(p.stem for p in cache_dir.glob(glob_pattern))
    if verbose:
        print(f"종목 수: {len(syms)} / cutoff 기간 {start.date()} ~ {end.date()}")
        print(f"전략: {list(scoring_fns.keys())} / hold: {list(hold_periods)} 거래일\n")

    if extra_cols is None:
        extra_cols = [
            "Close", "bull_stack", "bear_stack",
            "dist_ma10", "dist_ma20", "ret_30d", "ret_90d", "from_high_1y",
            "acc_d", "vol_recent_vs_prior", "recent_strong_bull_10d",
            "ma10_touch_recent_5d", "ma10_strong_up", "today_strong_bull",
            "bullish_holding", "today_chg",
        ]

    score_cols = list(scoring_fns.keys())
    hold_list = list(hold_periods)

    rows = []
    for i, sym in enumerate(syms):
        if verbose and i % 100 == 0:
            print(f"  [{i}/{len(syms)}] processing...")
        try:
            df = pd.read_parquet(cache_dir / f"{sym}.parquet")
            if len(df) < min_bars:
                continue
            if indicators_fn is not None:
                df = indicators_fn(df)
            if weekly_acc_fn is not None:
                df["acc_w"] = weekly_acc_fn(df)
            for col, fn in scoring_fns.items():
                df[col] = fn(df)
            for h in hold_list:
                df[f"fwd_ret_{h}"] = df["Close"].shift(-h) / df["Close"] - 1

            mask = (df.index >= start) & (df.index <= end)
            cols = score_cols + [c for c in extra_cols if c in df.columns]
            cols += [f"fwd_ret_{h}" for h in hold_list]
            sub = df.loc[mask, cols]
            if sub.empty:
                continue
            sub = sub.reset_index().rename(columns={"Date": "date", "index": "date"})
            sub["symbol"] = sym
            rows.append(sub)
        except Exception as e:
            if verbose:
                print(f"  [warn] {sym}: {e}")
            continue

    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    if verbose:
        print(f"\n총 (종목 × 일자) 샘플: {len(out):,}")
    return out


# ─────────────────────────────────────────────────────────────
# Analyze
# ─────────────────────────────────────────────────────────────
def analyze_threshold_multi(
    bt: pd.DataFrame,
    score_col: str,
    threshold: float,
    name: str,
    hold_periods: Iterable[int] = (5, 10, 20, 30, 60),
) -> None:
    """score>=threshold cohort 의 holding 기간별 mean/median/win/sharpe."""
    sub = bt[bt[score_col] >= threshold]
    n = len(sub)
    if n == 0:
        print(f"\n[{name}] threshold {threshold}: 샘플 없음")
        return
    print(f"\n[{name}] threshold ≥ {threshold}  (샘플 {n:,})")
    print(f"  {'hold':>6} {'n':>6} {'mean':>9} {'median':>9} {'win%':>7} {'std':>7} {'sharpe':>7}")
    for h in hold_periods:
        col = f"fwd_ret_{h}"
        valid = sub[col].dropna()
        if len(valid) == 0:
            continue
        mean_r = valid.mean()
        med_r = valid.median()
        win = (valid > 0).mean()
        std = valid.std()
        sharpe = mean_r / std if std > 0 else 0
        print(f"  D+{h:>3}  {len(valid):>6,} {mean_r*100:>+8.2f}% {med_r*100:>+8.2f}% "
              f"{win*100:>6.1f}% {std*100:>6.2f}% {sharpe:>7.3f}")


def analyze_baseline_multi(
    bt: pd.DataFrame,
    hold_periods: Iterable[int] = (5, 10, 20, 30, 60),
) -> None:
    """전체 시장 baseline (필터 없음)."""
    print(f"\n=== Baseline (전체 샘플) ===")
    print(f"  {'hold':>6} {'n':>7} {'mean':>9} {'median':>9} {'win%':>7}")
    for h in hold_periods:
        col = f"fwd_ret_{h}"
        valid = bt[col].dropna()
        if len(valid) == 0:
            continue
        print(f"  D+{h:>3}  {len(valid):>7,} {valid.mean()*100:>+8.2f}% "
              f"{valid.median()*100:>+8.2f}% {(valid>0).mean()*100:>6.1f}%")


def analyze_quantile_multi(
    bt: pd.DataFrame,
    score_col: str,
    name: str,
    hold_periods: Iterable[int] = (5, 10, 20, 30, 60),
    n_q: int = 10,
) -> None:
    """점수 분위별 (n_q 분위) 평균 수익률 — 차별력 검증용."""
    sub = bt[bt[score_col] > 0].copy()
    if sub.empty:
        return
    sub["q"] = pd.qcut(sub[score_col], n_q, duplicates="drop", labels=False)
    for h in hold_periods:
        col = f"fwd_ret_{h}"
        sub_h = sub.dropna(subset=[col])
        if sub_h.empty:
            continue
        g = sub_h.groupby("q").agg(
            n=(col, "size"),
            smin=(score_col, "min"),
            smax=(score_col, "max"),
            mean=(col, "mean"),
            median=(col, "median"),
            win=(col, lambda x: (x > 0).mean()),
            std=(col, "std"),
        )
        g["mean%"] = (g["mean"] * 100).round(2)
        g["med%"] = (g["median"] * 100).round(2)
        g["win%"] = (g["win"] * 100).round(1)
        g["sharpe"] = (g["mean"] / g["std"]).round(3)
        print(f"\n[{name}] D+{h} 점수 분위별 수익률 (n_q={len(g)})")
        print(g[["n", "smin", "smax", "mean%", "med%", "win%", "sharpe"]].to_string())


def analyze_component_correlation_multi(
    bt: pd.DataFrame,
    score_col: str,
    name: str,
    hold_periods: Iterable[int] = (5, 10, 20, 30, 60),
    indicator_cols: Optional[list] = None,
    score_threshold: float = 40,
) -> None:
    """지표별 fwd_ret 상관 — 점수 cohort 안에서 어느 지표가 실제 alpha 에 기여하는지."""
    if indicator_cols is None:
        indicator_cols = [
            "bull_stack", "bear_stack", "dist_ma10", "dist_ma20",
            "ret_30d", "ret_90d", "from_high_1y", "acc_d", "acc_w",
            "vol_recent_vs_prior", "recent_strong_bull_10d",
        ]
    cols = [c for c in indicator_cols if c in bt.columns] + [score_col]
    sub = bt[bt[score_col] >= score_threshold].copy()
    if sub.empty:
        print(f"\n[{name}] 점수≥{score_threshold} 샘플 없음")
        return
    rows = {}
    for h in hold_periods:
        col = f"fwd_ret_{h}"
        sub_h = sub.dropna(subset=[col])
        if sub_h.empty:
            continue
        rows[f"D+{h}"] = sub_h[cols + [col]].corr()[col].drop(col)
    out = pd.DataFrame(rows).round(3)
    print(f"\n=== [{name}] 지표별 fwd_ret 상관 (점수≥{score_threshold} 그룹) ===")
    print(out.to_string())
