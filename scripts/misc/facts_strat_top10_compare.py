"""Facts entry_score(1d+4h+1h) top-10 + Strategy(trend_pullback) score top-10
vs 실제 next-day return top-10 비교 (최근 10일, UTC 00->00).

day-D 정의/룩어헤드 회피 규약 (facts_top10_hit_rate.py 와 동일):
  - day-D return = Close[D] / Close[D-1] - 1
  - facts/strategy 는 index < D 09:00 KST 데이터로 계산

Facts 점수: scripts.misc.rec_now.entry_score (production multi-TF).
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

import warnings
warnings.filterwarnings("ignore")

import time
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from research.visual_review.facts import compute_facts_tf, _normalize, _resample, RESAMPLE_RULE
from scripts.misc.rec_now import entry_score as entry_score_multi_tf
from backtest.strategies import trend_pullback
from backtest.strategies import cascading_pullback as cascading

CACHE_1D = Path("data/cache/crypto/1d")
CACHE_1H = Path("data/cache/crypto/1h")
WORKERS = 8
TOP_N = 10
N_DAYS = 10


def process(sym: str, d_ts: pd.Timestamp,
            df_1d_norm: pd.DataFrame, df_1h_norm: pd.DataFrame,
            df_lower: pd.DataFrame) -> dict | None:
    df_1d_hist = df_1d_norm[df_1d_norm.index < d_ts]
    df_lower_hist = df_lower[df_lower.index < d_ts]
    if len(df_1d_hist) < 60:
        return None

    close_start = float(df_1d_hist["Close"].iloc[-1])
    df_d = df_1d_norm[df_1d_norm.index == d_ts]
    if len(df_d) == 0:
        return None
    close_end = float(df_d["Close"].iloc[0])
    ret = (close_end / close_start - 1) if close_start > 0 else float("nan")

    # Facts (1d + 4h + 1h)
    facts: dict = {"symbol": sym, "asset": "crypto", "tfs": ["1d", "4h", "1h"]}
    try:
        facts["tf_1d"] = compute_facts_tf(df_1d_hist, bars=200, tf_label="1d")
    except Exception:
        facts["tf_1d"] = None
    if df_1h_norm is not None:
        df_1h_hist = df_1h_norm[df_1h_norm.index < d_ts]
        if len(df_1h_hist) >= 50:
            try:
                df_4h_hist = _resample(df_1h_hist, RESAMPLE_RULE["4h"])
                if len(df_4h_hist) >= 30:
                    facts["tf_4h"] = compute_facts_tf(df_4h_hist, bars=200, tf_label="4h")
                facts["tf_1h"] = compute_facts_tf(df_1h_hist, bars=200, tf_label="1h")
            except Exception:
                pass
    try:
        e_score, _info = entry_score_multi_tf(facts)
    except Exception:
        e_score = float("nan")

    # Strategy score (trend_pullback)
    try:
        score_series = trend_pullback.score(df_lower_hist, {})
        strat_score = float(score_series.iloc[-1])
    except Exception:
        strat_score = float("nan")

    # Cascading pullback (multi-TF: 1h + 4h + 1d)
    cascade_score = float("nan")
    cascade_tier = 0
    cascade_imp_tf = None
    cascade_pull_ma = None
    try:
        df_1h_hist_for_cascade = (df_1h_norm[df_1h_norm.index < d_ts]
                                  if df_1h_norm is not None else None)
        if df_1h_hist_for_cascade is not None and len(df_1h_hist_for_cascade) >= 200:
            res = cascading.compute_cascade(df_1h_hist_for_cascade, df_1d_hist, params=None)
            cascade_score = float(res.get("score", 0.0))
            cascade_tier = int(res.get("tier", 0))
            cascade_imp_tf = res.get("impulse_tf")
            cascade_pull_ma = res.get("pullback_ma")
    except Exception:
        pass

    return {
        "symbol": sym,
        "date": d_ts.date(),
        "entry_score": e_score,
        "strat_score": strat_score,
        "cascade_score": cascade_score,
        "cascade_tier": cascade_tier,
        "cascade_imp_tf": cascade_imp_tf,
        "cascade_pull_ma": cascade_pull_ma,
        "ret": ret,
    }


def main():
    parquet_files = sorted(CACHE_1D.glob("*.parquet"))
    symbols = [f.stem for f in parquet_files]
    print(f"심볼 수: {len(symbols)}")

    print("1d/1h 파케이 선로드 중 ...")
    t0 = time.time()
    norm_store: dict[str, pd.DataFrame] = {}
    lower_store: dict[str, pd.DataFrame] = {}
    norm_1h_store: dict[str, pd.DataFrame] = {}
    for f in parquet_files:
        sym = f.stem
        try:
            raw = pd.read_parquet(f)
            nd = _normalize(raw)
            ld = nd.rename(columns={c: c.lower() for c in nd.columns})
            norm_store[sym] = nd
            lower_store[sym] = ld
        except Exception:
            pass
        f1h = CACHE_1H / f.name
        if f1h.exists():
            try:
                raw1h = pd.read_parquet(f1h)
                norm_1h_store[sym] = _normalize(raw1h)
            except Exception:
                pass
    print(f"  1d {len(norm_store)} / 1h {len(norm_1h_store)} 심볼 완료 ({time.time()-t0:.1f}s)")

    btc_idx = norm_store["BTCUSDT"].index
    date_range = list(btc_idx[-N_DAYS:])
    print(f"분석 날짜 (UTC day = KST candle ts - 9h): {date_range[0].date()} ~ {date_range[-1].date()} ({len(date_range)}일)\n")

    results = []
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {
            ex.submit(process, sym, d_ts,
                      norm_store[sym], norm_1h_store.get(sym), lower_store[sym]): (sym, d_ts)
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

    print("=" * 130)
    print(f"  top-{TOP_N} 비교 — Actual / Facts(1d+4h+1h) / Strategy(trend_pullback) / Cascading(multi-TF)")
    print(f"  hit = top-{TOP_N} (by score) ∩ top-{TOP_N} (by actual return)")
    print("=" * 130)
    header = (f"{'UTC date':12s} {'actual':>9s} | {'facts':>9s} {'Fh':>4s} | "
              f"{'strat':>9s} {'Sh':>4s} | {'cascade':>9s} {'Ch':>4s} | "
              f"{'F∩S':>4s} {'F∩C':>4s} {'S∩C':>4s} | {'baseline':>9s}")
    print(header)
    print("-" * 130)

    summary = []
    for d_ts in date_range:
        sub = df[df.date == d_ts.date()].dropna(subset=["ret"])
        sub_f = sub.dropna(subset=["entry_score"])
        sub_s = sub.dropna(subset=["strat_score"])
        sub_c = sub.dropna(subset=["cascade_score"])
        if len(sub_f) < TOP_N * 2 or len(sub_s) < TOP_N * 2 or len(sub_c) < TOP_N * 2:
            continue
        utc_date = (d_ts - pd.Timedelta(hours=9)).date()

        actual_top = set(sub.nlargest(TOP_N, "ret").symbol)
        facts_top = set(sub_f.nlargest(TOP_N, "entry_score").symbol)
        strat_top = set(sub_s.nlargest(TOP_N, "strat_score").symbol)
        cascade_top = set(sub_c.nlargest(TOP_N, "cascade_score").symbol)

        f_hit = len(facts_top & actual_top)
        s_hit = len(strat_top & actual_top)
        c_hit = len(cascade_top & actual_top)
        f_s = len(facts_top & strat_top)
        f_c = len(facts_top & cascade_top)
        s_c = len(strat_top & cascade_top)

        actual_avg = sub[sub.symbol.isin(actual_top)].ret.mean()
        facts_avg = sub[sub.symbol.isin(facts_top)].ret.mean()
        strat_avg = sub[sub.symbol.isin(strat_top)].ret.mean()
        cascade_avg = sub[sub.symbol.isin(cascade_top)].ret.mean()
        baseline = sub.ret.mean()

        summary.append({
            "utc_date": utc_date,
            "actual_avg": actual_avg, "facts_avg": facts_avg,
            "strat_avg": strat_avg, "cascade_avg": cascade_avg,
            "f_hit": f_hit, "s_hit": s_hit, "c_hit": c_hit,
            "f_s": f_s, "f_c": f_c, "s_c": s_c,
            "baseline": baseline, "n": len(sub),
        })

        print(f"{str(utc_date):12s} {actual_avg:>+9.2%} | "
              f"{facts_avg:>+9.2%} {f_hit:>2d}/10 | "
              f"{strat_avg:>+9.2%} {s_hit:>2d}/10 | "
              f"{cascade_avg:>+9.2%} {c_hit:>2d}/10 | "
              f"{f_s:>4d} {f_c:>4d} {s_c:>4d} | {baseline:>+9.2%}")

    print("-" * 130)
    if summary:
        s = pd.DataFrame(summary)
        print(f"{'전체 평균':12s} {s.actual_avg.mean():>+9.2%} | "
              f"{s.facts_avg.mean():>+9.2%} {s.f_hit.mean():>4.1f}/10 | "
              f"{s.strat_avg.mean():>+9.2%} {s.s_hit.mean():>4.1f}/10 | "
              f"{s.cascade_avg.mean():>+9.2%} {s.c_hit.mean():>4.1f}/10 | "
              f"{s.f_s.mean():>4.1f} {s.f_c.mean():>4.1f} {s.s_c.mean():>4.1f} | {s.baseline.mean():>+9.2%}")
        n = len(s) * TOP_N
        print(f"\nFacts    hit 누적: {s.f_hit.sum()}/{n} = {s.f_hit.sum()/n:.1%}")
        print(f"Strat    hit 누적: {s.s_hit.sum()}/{n} = {s.s_hit.sum()/n:.1%}")
        print(f"Cascade  hit 누적: {s.c_hit.sum()}/{n} = {s.c_hit.sum()/n:.1%}")

    # 상세 — cascading top-10
    print("\n" + "=" * 130)
    print("  매일 cascading top-10 상세 (cascade_score 순 — tier/impulse_tf/pullback_ma 표기)")
    print("=" * 130)
    for d_ts in date_range:
        sub = df[df.date == d_ts.date()].dropna(subset=["ret", "cascade_score"])
        if len(sub) < TOP_N * 2:
            continue
        utc_date = (d_ts - pd.Timedelta(hours=9)).date()
        sub_sorted = sub.sort_values("ret", ascending=False).reset_index(drop=True)
        rank_map = {sym: i+1 for i, sym in enumerate(sub_sorted.symbol)}

        cascade_top = sub.nlargest(TOP_N, "cascade_score")
        print(f"\n[{utc_date}]")
        for _, row in cascade_top.iterrows():
            rk = rank_map.get(row.symbol, "?")
            hit_mark = "★" if isinstance(rk, int) and rk <= TOP_N else " "
            t = int(row.cascade_tier) if pd.notna(row.cascade_tier) else 0
            itf = row.cascade_imp_tf or "-"
            pma = row.cascade_pull_ma or "-"
            print(f"  {hit_mark} {row.symbol:18s} cs={row.cascade_score:6.1f}  tier{t}/{itf:>3s}/{pma:>4s}  "
                  f"ret={row.ret:+.2%}  (actual rank {rk}/{len(sub)})")


if __name__ == "__main__":
    main()
