"""A/B 그룹 백테스트 — 지난 한 달.

각 거래일 D 에 대해:
  prev = 직전 거래일,  next = 다음 거래일
  passers(prev), passers(D) 계산
  A = passers(D) ∩ passers(prev),  today_ret(D) ≤ 0
  B = passers(D) − passers(prev),  today_ret(D) ≤ 0
  next_day_ret = (close[next] − close[D]) / close[D] × 100

집계: 그룹별 평균/중앙값/승률, 날짜별 분포, 종목별 raw.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.mtf_loader import load_normalized_daily, resample_multi_tf
from scripts._common.mtf_indicators import compute_mtf_indicators
from scripts._common.signals import evaluate_tf
from scripts._common.tf_selector import determine_eval_kind, select_eval_tfs
from scripts._common.recommend_runner import EVAL_TFS, MIN_DAILY_BARS, discover_universe

ASSET = "kr"
LOOKBACK_DAYS = 35   # 한 달 + 여유


# symbol → df_daily 캐시 (전체)
_DF_CACHE: dict = {}


def get_daily(sym: str):
    if sym not in _DF_CACHE:
        try:
            _DF_CACHE[sym] = load_normalized_daily(ASSET, sym)
        except Exception:
            _DF_CACHE[sym] = None
    return _DF_CACHE[sym]


def passes_at(sym: str, cutoff: pd.Timestamp) -> bool:
    df_full = get_daily(sym)
    if df_full is None:
        return False
    df_d = df_full[df_full.index <= cutoff]
    if len(df_d) < MIN_DAILY_BARS or cutoff not in df_d.index:
        return False
    mtf = resample_multi_tf(df_d)
    allowed = set(select_eval_tfs(mtf))
    today_low = float(df_d["low"].iloc[-1])
    for tf in EVAL_TFS:
        df_tf = mtf[tf]
        kind = determine_eval_kind(df_tf)
        if (tf not in allowed) or kind == "skip":
            continue
        df_ind = compute_mtf_indicators(df_tf, kind)
        pf, pp, _ = evaluate_tf(df_ind, df_d, kind, today_low=today_low)
        if pf or pp:
            return True
    return False


def passers_at(symbols, cutoff: pd.Timestamp) -> set[str]:
    return {s for s in symbols if passes_at(s, cutoff)}


def main():
    symbols = discover_universe(ASSET)
    print(f"universe={len(symbols)}", file=sys.stderr)

    # 거래일 = 가장 캐시 큰 종목의 인덱스 (KR은 거래일 동일)
    samsung = get_daily("005930")
    if samsung is None:
        # fallback
        samsung = get_daily(symbols[0])
    all_dates = samsung.index
    today = pd.Timestamp.today().normalize()
    recent = all_dates[(all_dates >= today - pd.Timedelta(days=LOOKBACK_DAYS)) & (all_dates <= today)]
    # next_day 가 존재해야 평가 가능 — 마지막 날 제외 (다음 거래일 없음)
    eval_dates = list(recent[:-1])
    print(f"평가 거래일: {len(eval_dates)} 개 ({eval_dates[0].date()} ~ {eval_dates[-1].date()})", file=sys.stderr)

    # 모든 cutoff (eval + prev) 의 passers 한 번씩만 계산
    needed_dates = set(eval_dates)
    # prev 도 필요
    for i, d in enumerate(eval_dates):
        idx = recent.get_loc(d)
        if idx > 0:
            needed_dates.add(recent[idx - 1])
    needed_dates = sorted(needed_dates)
    print(f"필요 cutoff: {len(needed_dates)} 개", file=sys.stderr)

    passers_cache: dict = {}
    t0 = time.time()
    for i, dt in enumerate(needed_dates, 1):
        passers_cache[dt] = passers_at(symbols, dt)
        elapsed = time.time() - t0
        print(f"  [{i}/{len(needed_dates)}] {dt.date()}: {len(passers_cache[dt])} passers  (elapsed={elapsed:.0f}s)",
              file=sys.stderr)

    listing = pd.read_csv(_ROOT / "data" / "cache" / "kr" / "_listing.csv", dtype={"Symbol": str})
    name_map = dict(zip(listing["Symbol"], listing["Name"]))

    # 본 백테스트
    records = []
    for d in eval_dates:
        idx = recent.get_loc(d)
        if idx == 0:
            continue   # prev 없으면 분류 못함
        prev = recent[idx - 1]
        try:
            next_d = recent[idx + 1]
        except IndexError:
            continue
        prev_set = passers_cache.get(prev, set())
        today_set = passers_cache.get(d, set())

        for sym in today_set:
            df_full = get_daily(sym)
            if df_full is None or d not in df_full.index or prev not in df_full.index or next_d not in df_full.index:
                continue
            ec = float(df_full.loc[d, "close"])
            pc = float(df_full.loc[prev, "close"])
            nc = float(df_full.loc[next_d, "close"])
            today_ret = (ec - pc) / pc * 100
            if today_ret > 0:
                continue   # 폭등 진입 제외
            next_ret = (nc - ec) / ec * 100
            bucket = "A" if sym in prev_set else "B"
            records.append({
                "eval_date": d.date(),
                "next_date": next_d.date(),
                "bucket": bucket,
                "Symbol": sym,
                "Name": name_map.get(sym, ""),
                "today_ret_pct": today_ret,
                "next_ret_pct": next_ret,
            })

    df = pd.DataFrame(records)
    if df.empty:
        print("no records", file=sys.stderr)
        return

    print(f"\n총 관측치: {len(df)}")
    print(f"  A (유지 + 약세) : {(df.bucket == 'A').sum()}")
    print(f"  B (신규 + 약세) : {(df.bucket == 'B').sum()}")

    def stats(s, label):
        if len(s) == 0:
            print(f"  {label} (n=0)")
            return
        print(f"  {label} (n={len(s)})  mean={s.mean():+.2f}%  median={s.median():+.2f}%  "
              f"win={(s>0).mean()*100:.0f}%  min={s.min():+.2f}%  max={s.max():+.2f}%  std={s.std():.2f}%")

    print("\n=== 그룹별 익일 수익률 ===")
    stats(df[df.bucket == "A"]["next_ret_pct"], "A 유지+약세")
    stats(df[df.bucket == "B"]["next_ret_pct"], "B 신규+약세")
    stats(df["next_ret_pct"], "전체")

    # 날짜별 분포
    print("\n=== 날짜별 (A+B 합산) ===")
    day_grp = df.groupby("eval_date").agg(
        n=("Symbol", "count"),
        next_mean=("next_ret_pct", "mean"),
        win=("next_ret_pct", lambda s: (s > 0).mean() * 100),
    )
    print(day_grp.to_string(float_format=lambda v: f"{v:.2f}"))

    out_csv = Path(__file__).parent / "_backtest_ab_last_month.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
