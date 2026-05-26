"""Facts entry_score top-10 vs 실제 next-day 상승률 top-10 비교.

질문:
  최근 10일 동안 UTC 00->00 기준 최대 상승 코인 top10 중
  entry_score top10이 몇 개나 맞췄는지 (hit rate)
  + entry_score top10의 평균 next-day return

day D 정의:
  - candle indexed at D 09:00 KST (= UTC D 00:00 시작, D+1 00:00 종료)
  - day-D return = Close[D] / Close[D-1] - 1  (UTC 00:00 -> 다음날 00:00)

Facts at start of day D:
  - 사용 가능 데이터 = index < D 09:00 KST (strict less than) — 룩어헤드 회피
  - entry_score_1d 동일 (backtest_facts_vs_strat.py 와 일치)
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.stdout.reconfigure(encoding="utf-8")

import warnings
warnings.filterwarnings("ignore")

import time
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from research.visual_review.facts import compute_facts_tf, _normalize
from scripts.crypto.trend_pullback.facts_comparison_backtest import entry_score_1d

CACHE_1D = Path("data/cache/crypto/1d")
WORKERS = 8
TOP_N = 10
N_DAYS = 10


def process(sym: str, d_ts: pd.Timestamp, df_norm: pd.DataFrame) -> dict | None:
    """day d_ts (KST 09:00 시작 candle) 분석."""
    # 룩어헤드 회피: facts 는 d_ts 이전 데이터만 사용
    df_hist = df_norm[df_norm.index < d_ts]
    if len(df_hist) < 60:
        return None

    # day-D 의 시작 가격 = D-1 candle 의 Close (= D 00:00 UTC 가격)
    # day-D 의 종료 가격 = D   candle 의 Close (= D+1 00:00 UTC 가격)
    close_start = float(df_hist["Close"].iloc[-1])

    # D candle 자체 (이미 종료된 경우)
    df_d = df_norm[df_norm.index == d_ts]
    if len(df_d) == 0:
        return None
    close_end = float(df_d["Close"].iloc[0])

    ret = (close_end / close_start - 1) if close_start > 0 else float("nan")

    try:
        f1d = compute_facts_tf(df_hist, bars=200, tf_label="1d")
        e_score = entry_score_1d(f1d)
    except Exception:
        e_score = float("nan")

    return {
        "symbol": sym,
        "date": d_ts.date(),
        "entry_score": e_score,
        "ret": ret,
    }


def main():
    parquet_files = sorted(CACHE_1D.glob("*.parquet"))
    symbols = [f.stem for f in parquet_files]
    print(f"심볼 수: {len(symbols)}")

    print("1d 파케이 선로드 중 ...")
    t0 = time.time()
    norm_store: dict[str, pd.DataFrame] = {}
    for f in parquet_files:
        sym = f.stem
        try:
            raw = pd.read_parquet(f)
            norm_store[sym] = _normalize(raw)
        except Exception:
            pass
    print(f"  {len(norm_store)} 심볼 완료 ({time.time()-t0:.1f}s)")

    # BTC 인덱스 기준 마지막 10일 (가장 최근부터 역순으로 N_DAYS)
    btc_idx = norm_store["BTCUSDT"].index
    date_range = list(btc_idx[-N_DAYS:])
    print(f"분석 날짜 (KST candle ts, UTC day = ts-9h): {date_range[0].date()} ~ {date_range[-1].date()} ({len(date_range)}일)\n")

    # 롤링
    results = []
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {
            ex.submit(process, sym, d_ts, norm_store[sym]): (sym, d_ts)
            for d_ts in date_range
            for sym in symbols
            if sym in norm_store
        }
        for fut in as_completed(futures):
            r = fut.result()
            if r is not None:
                results.append(r)
    df = pd.DataFrame(results)
    print(f"총 {len(df):,} 레코드 ({time.time()-t1:.1f}s)\n")

    # 날짜별 분석
    print("=" * 96)
    print(f"  Facts entry_score top-{TOP_N} vs 실제 next-day return top-{TOP_N}")
    print(f"  날짜 = UTC 00:00 시작일 (D 00:00 -> D+1 00:00 return)")
    print("=" * 96)
    print(f"{'UTC date':12s} {'actual top10 평균':>18s} | {'facts top10 평균':>18s} | "
          f"{'hit':>4s}/{TOP_N} | {'facts > actual baseline':>22s}")
    print("-" * 96)

    summary = []
    for d_ts in date_range:
        sub = df[df.date == d_ts.date()].dropna(subset=["ret", "entry_score"])
        if len(sub) < TOP_N * 2:
            continue
        # UTC 날짜 표시 (KST candle ts - 9h)
        utc_date = (d_ts - pd.Timedelta(hours=9)).date()

        actual_top = sub.nlargest(TOP_N, "ret")
        facts_top = sub.nlargest(TOP_N, "entry_score")

        hit = len(set(actual_top.symbol) & set(facts_top.symbol))
        actual_avg = actual_top.ret.mean()
        facts_avg = facts_top.ret.mean()
        baseline = sub.ret.mean()

        summary.append({
            "utc_date": utc_date,
            "actual_top10_avg": actual_avg,
            "facts_top10_avg": facts_avg,
            "hit": hit,
            "baseline_avg": baseline,
            "n_total": len(sub),
        })

        print(f"{str(utc_date):12s} {actual_avg:>+18.2%} | {facts_avg:>+18.2%} | "
              f"{hit:>4d}/{TOP_N} | baseline {baseline:>+8.2%}")

    print("-" * 96)
    if summary:
        s = pd.DataFrame(summary)
        print(f"{'전체 평균':12s} {s.actual_top10_avg.mean():>+18.2%} | "
              f"{s.facts_top10_avg.mean():>+18.2%} | "
              f"{s.hit.mean():>4.1f}/{TOP_N} | baseline {s.baseline_avg.mean():>+8.2%}")
        print(f"\nHit 누적: {s.hit.sum()} / {len(s) * TOP_N} = {s.hit.sum() / (len(s) * TOP_N):.1%}")

    # 상세: 매일 facts top10 종목 + 실제 ranking 보여주기
    print("\n" + "=" * 96)
    print("  매일 facts top-10 상세 (entry_score 순)")
    print("=" * 96)
    for d_ts in date_range:
        sub = df[df.date == d_ts.date()].dropna(subset=["ret", "entry_score"])
        if len(sub) < TOP_N * 2:
            continue
        utc_date = (d_ts - pd.Timedelta(hours=9)).date()
        sub_sorted = sub.sort_values("ret", ascending=False).reset_index(drop=True)
        sub_sorted["rank_by_ret"] = sub_sorted.index + 1
        rank_map = dict(zip(sub_sorted.symbol, sub_sorted.rank_by_ret))

        facts_top = sub.nlargest(TOP_N, "entry_score")
        print(f"\n[{utc_date}]")
        for _, row in facts_top.iterrows():
            rk = rank_map.get(row.symbol, "?")
            hit_mark = "★" if isinstance(rk, int) and rk <= TOP_N else " "
            print(f"  {hit_mark} {row.symbol:18s} es={row.entry_score:+.3f}  ret={row.ret:+.2%}  (actual rank {rk}/{len(sub)})")


if __name__ == "__main__":
    main()
