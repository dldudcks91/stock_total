"""1374 관측치의 angle / residence 분포 → 각 필터 컷 기여도.

각 (eval_date, Symbol) 에 대해:
  1. 그 cutoff 까지 mtf 빌드
  2. 통과한 TF 중 (any) angle_MA_deg 와 residence (close>MA_main).tail(20).mean()
  3. 가장 좋은 TF (angle 가장 큰) 기준으로 기록

그 다음:
  - 둘 다 통과 (현재 68개 검증)
  - angle 만 통과 vs residence 만 통과
  - 어느 게 더 강하게 컷하는가
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.mtf_loader import load_normalized_daily, resample_multi_tf
from scripts._common.mtf_indicators import compute_mtf_indicators
from scripts._common.signals import _compute_range_threshold, PARTIAL_CONSEC_BARS
from scripts._common.tf_selector import determine_eval_kind, select_eval_tfs
from scripts._common.recommend_runner import EVAL_TFS, MIN_DAILY_BARS

ASSET = "kr"
ANGLE_MIN = 3.0
RES_MIN = 0.70
RES_WINDOW = 20

_DF_CACHE: dict = {}


def get_daily(sym: str):
    if sym not in _DF_CACHE:
        try:
            _DF_CACHE[sym] = load_normalized_daily(ASSET, sym)
        except Exception:
            _DF_CACHE[sym] = None
    return _DF_CACHE[sym]


def best_passing_tf(sym: str, cutoff: pd.Timestamp):
    """ma_touch 본룰 통과 TF 중 angle 가장 큰 것의 (angle, residence) 반환."""
    df_full = get_daily(sym)
    if df_full is None:
        return None
    df_d = df_full[df_full.index <= cutoff]
    if len(df_d) < MIN_DAILY_BARS or cutoff not in df_d.index:
        return None
    mtf = resample_multi_tf(df_d)
    allowed = set(select_eval_tfs(mtf))
    today_low = float(df_d["low"].iloc[-1])
    th = _compute_range_threshold(df_d)
    if pd.isna(th):
        return None

    best = None
    for tf in EVAL_TFS:
        df_tf = mtf[tf]
        kind = determine_eval_kind(df_tf)
        if (tf not in allowed) or kind == "skip":
            continue
        df_ind = compute_mtf_indicators(df_tf, kind)
        if len(df_ind) < 1:
            continue
        last = df_ind.iloc[-1]
        close = last["close"]
        ma10 = last["ma10"]
        sl10 = last["slope_pct_ma10"]
        if pd.isna(ma10) or pd.isna(sl10):
            continue

        if kind == "full":
            ma20 = last["ma20"]
            sl20 = last["slope_pct_ma20"]
            if pd.isna(ma20) or pd.isna(sl20):
                continue
            if not ((ma10 > ma20) and (close > ma20)):
                continue
            if not (sl10 > 0 and sl20 > 0):
                continue
            d10 = abs(today_low - ma10)
            d20 = abs(today_low - ma20)
            if not (d10 <= th or d20 <= th):
                continue
            angle = float(last.get("angle_ma20_deg", float("nan")))
            tail = df_ind.tail(RES_WINDOW)
            if len(tail) < RES_WINDOW:
                continue
            residence = float((tail["close"] > tail["ma20"]).mean())
        else:
            if not (close > ma10 and sl10 > 0):
                continue
            d10 = abs(today_low - ma10)
            if not (d10 <= th):
                continue
            tail3 = df_ind.tail(PARTIAL_CONSEC_BARS)
            if not (tail3["close"] > tail3["ma10"]).all():
                continue
            angle = float(last.get("angle_ma10_deg", float("nan")))
            tail = df_ind.tail(RES_WINDOW)
            if len(tail) < RES_WINDOW:
                continue
            residence = float((tail["close"] > tail["ma10"]).mean())

        if pd.isna(angle):
            continue
        if best is None or angle > best[1]:
            best = (tf, angle, residence)
    return best


def main():
    base_csv = Path(__file__).parent / "_backtest_ab_last_month.csv"
    df = pd.read_csv(base_csv, dtype={"Symbol": str})
    df["eval_date"] = pd.to_datetime(df["eval_date"])
    print(f"기존 1차 백테스트 관측치: {len(df)}")

    rows = []
    for i, r in enumerate(df.itertuples(), 1):
        best = best_passing_tf(r.Symbol, r.eval_date)
        if best is None:
            continue
        rows.append({
            "eval_date": r.eval_date.date(),
            "bucket": r.bucket,
            "Symbol": r.Symbol,
            "Name": r.Name,
            "tf": best[0],
            "angle_deg": best[1],
            "residence_20": best[2],
            "next_ret_pct": r.next_ret_pct,
        })
        if i % 200 == 0:
            print(f"  [{i}/{len(df)}]", file=sys.stderr)

    out = pd.DataFrame(rows)
    n = len(out)
    print(f"angle/residence 측정 가능: {n}")

    pa = out["angle_deg"] >= ANGLE_MIN
    pr = out["residence_20"] >= RES_MIN

    print()
    print("=== 필터별 통과 카운트 (1374 → ? 매핑) ===")
    print(f"  필터 없음 (base)          : {n}")
    print(f"  A 단독 (angle ≥ {ANGLE_MIN}°)       : {pa.sum()}   (컷 {n - pa.sum()})")
    print(f"  B 단독 (residence ≥ {int(RES_MIN*100)}%) : {pr.sum()}   (컷 {n - pr.sum()})")
    print(f"  A AND B                   : {(pa & pr).sum()}   (컷 {n - (pa & pr).sum()})")
    print(f"  A OR B                    : {(pa | pr).sum()}   (컷 {n - (pa | pr).sum()})")

    print()
    print("=== 각 필터의 익일 수익률 영향 ===")
    def stats(s, label):
        if len(s) == 0:
            print(f"  {label} n=0")
            return
        print(f"  {label} n={len(s):4d}  mean={s.mean():+.2f}%  median={s.median():+.2f}%  win={(s>0).mean()*100:.0f}%")

    stats(out["next_ret_pct"], "base (no filter)         ")
    stats(out.loc[pa, "next_ret_pct"],            "A only (angle≥3°)        ")
    stats(out.loc[pr, "next_ret_pct"],            "B only (residence≥70%)   ")
    stats(out.loc[pa & pr, "next_ret_pct"],       "A AND B                  ")

    print()
    print("=== angle / residence 분포 (base 전체) ===")
    print(f"  angle_deg     : p25={out['angle_deg'].quantile(0.25):.2f}°  p50={out['angle_deg'].median():.2f}°  p75={out['angle_deg'].quantile(0.75):.2f}°  p90={out['angle_deg'].quantile(0.9):.2f}°")
    print(f"  residence_20  : p25={out['residence_20'].quantile(0.25)*100:.0f}%  p50={out['residence_20'].median()*100:.0f}%  p75={out['residence_20'].quantile(0.75)*100:.0f}%  p90={out['residence_20'].quantile(0.9)*100:.0f}%")

    # 두 필터 독립성: A 만 통과 vs B 만 통과 vs 둘다
    print()
    print("=== 두 필터 교차 ===")
    print(f"  A pass only  (A·~B): {(pa & ~pr).sum()}")
    print(f"  B pass only  (~A·B): {(~pa & pr).sum()}")
    print(f"  both         (A·B) : {(pa & pr).sum()}")
    print(f"  neither      (~A·~B): {(~pa & ~pr).sum()}")

    out_csv = Path(__file__).parent / "_filter_contribution.csv"
    out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
