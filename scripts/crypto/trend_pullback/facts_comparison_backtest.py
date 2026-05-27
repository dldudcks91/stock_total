"""Facts entry_score vs Strategy (trend_pullback) 롤링 백테스트.

기준날짜 T = (오늘-30일) ~ (오늘-14일) 구간 매일:
  - entry_score (1d facts 기반) 시그널 생성
  - trend_pullback 전략 시그널 생성
  → D+7, D+14 forward return 비교.

※ facts는 1d TF만 사용 (4h/1h: 1h 캐시 미로드로 제외, 기여도 ~17%)
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

from scripts._common.visual_review.facts import compute_facts_tf, _normalize
from backtest.strategies import trend_pullback

CACHE_1D    = Path("data/cache/crypto/1d")
OUT_DIR     = Path("data/cache/crypto/visual_review")
WORKERS     = 8
FACTS_TH    = 1.0   # entry_score 활성 임계값 (1d only 기준 ~0.85)
STRAT_TH    = 80    # 전략 score 임계값


# ── entry_score (1d only) ────────────────────────────────────────────────────

def entry_score_1d(f1d: dict) -> float:
    if not f1d:
        return float("nan")
    s = 0.0
    if f1d.get("ma_stack") == "정배열":   s += 0.30
    elif f1d.get("ma_stack") == "역배열": s -= 0.30
    slopes = f1d.get("ma_slopes") or {}
    if slopes.get("ma20") == "up":   s += 0.20
    elif slopes.get("ma20") == "down": s -= 0.20

    nma     = f1d.get("nearest_ma") or {}
    dma     = f1d.get("dist_from_ma_atr") or {}
    nma_key = nma.get("ma", "ma10")
    atr_dist = abs(dma.get(f"{nma_key}_atr") or 99)
    if nma.get("ma") in ("ma10", "ma20") and atr_dist < 1.0:
        s += 0.40 * (1.0 - atr_dist)
    elif nma.get("ma") == "ma50" and atr_dist < 0.5:
        s += 0.20 * (0.5 - atr_dist)

    rsb = f1d.get("recent_strong_bull") or {}
    if rsb.get("holding"):
        bars = rsb.get("bars_ago") or 99
        if bars <= 5:  s += 0.40
        elif bars <= 10: s += 0.20

    lc = f1d.get("last_candle") or {}
    s += (lc.get("accumulation_candle_score") or 0.0) * 0.30
    s -= (lc.get("distribution_candle_score") or 0.0) * 0.30

    adx = f1d.get("adx") or 0
    if 25 <= adx <= 50: s += 0.15
    elif adx > 75:      s -= 0.15
    return s


# ── 심볼-날짜 단위 연산 ──────────────────────────────────────────────────────

def process(sym: str, t_date: pd.Timestamp,
            df_norm: pd.DataFrame, df_lower: pd.DataFrame) -> dict | None:
    # 슬라이싱
    df_hist  = df_norm[df_norm.index <= t_date]
    df_lower_hist = df_lower[df_lower.index <= t_date]
    df_fwd   = df_norm[df_norm.index > t_date]

    if len(df_hist) < 60 or len(df_fwd) < 7:
        return None

    close_T   = float(df_hist["Close"].iloc[-1])
    close_T7  = float(df_fwd["Close"].iloc[6])  if len(df_fwd) >= 7  else None
    close_T14 = float(df_fwd["Close"].iloc[13]) if len(df_fwd) >= 14 else None

    ret7  = (close_T7  / close_T - 1) if close_T7  is not None else float("nan")
    ret14 = (close_T14 / close_T - 1) if close_T14 is not None else float("nan")

    # Facts (1d)
    try:
        f1d     = compute_facts_tf(df_hist, bars=200, tf_label="1d")
        e_score = entry_score_1d(f1d)
    except Exception:
        e_score = float("nan")

    # 전략 (trend_pullback) — lowercase df 사용
    try:
        sig_series   = trend_pullback.signal(df_lower_hist, {})
        score_series = trend_pullback.score(df_lower_hist, {})
        strat_sig    = int(sig_series.iloc[-1])
        strat_score  = float(score_series.iloc[-1])
    except Exception:
        strat_sig   = 0
        strat_score = float("nan")

    return {
        "symbol":      sym,
        "date":        t_date.date(),
        "entry_score": e_score,
        "strat_score": strat_score,
        "facts_sig":   1 if (not np.isnan(e_score) and e_score >= FACTS_TH) else 0,
        "strat_sig":   strat_sig,
        "ret7":        ret7,
        "ret14":       ret14,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parquet_files = sorted(CACHE_1D.glob("*.parquet"))
    symbols = [f.stem for f in parquet_files]
    print(f"심볼 수: {len(symbols)}")

    # 1. 전체 1d 선로드
    print("1d 파케이 선로드 중 ...")
    t0 = time.time()
    norm_store  = {}   # symbol → capitalized df (facts용)
    lower_store = {}   # symbol → lowercase df   (strategy용)

    for f in parquet_files:
        sym = f.stem
        try:
            raw = pd.read_parquet(f)
            nd  = _normalize(raw)                           # capitalized, DatetimeIndex
            ld  = nd.rename(columns={c: c.lower() for c in nd.columns})
            norm_store[sym]  = nd
            lower_store[sym] = ld
        except Exception:
            pass
    print(f"  {len(norm_store)} 심볼 완료 ({time.time()-t0:.1f}s)")

    # 2. 날짜 범위 — BTC 인덱스 기준
    btc_idx = norm_store["BTCUSDT"].index
    latest  = btc_idx[-1]
    date_range = btc_idx[
        (btc_idx >= latest - pd.Timedelta(days=30)) &
        (btc_idx <= latest - pd.Timedelta(days=14))
    ]
    print(f"백테스트 날짜: {date_range[0].date()} ~ {date_range[-1].date()} ({len(date_range)}일)\n")

    # 3. 롤링 백테스트
    results = []
    t1 = time.time()
    tasks_total = len(date_range) * len(symbols)
    done = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {
            ex.submit(process, sym, t_date,
                      norm_store[sym], lower_store[sym]): (sym, t_date)
            for t_date in date_range
            for sym in symbols
            if sym in norm_store
        }
        for fut in as_completed(futures):
            done += 1
            r = fut.result()
            if r is not None:
                results.append(r)
            if done % 2000 == 0 or done == tasks_total:
                print(f"  [{done}/{tasks_total}] {time.time()-t1:.0f}s elapsed")

    df = pd.DataFrame(results)
    print(f"\n총 {len(df):,} 레코드 수집 ({time.time()-t1:.1f}s)\n")

    # 4. 그룹 분류
    df["S"] = df.strat_sig == 1
    df["F"] = df.facts_sig == 1
    df["grp"] = "none"
    df.loc[ df.S &  df.F, "grp"] = "S+F"
    df.loc[ df.S & ~df.F, "grp"] = "S_only"
    df.loc[~df.S &  df.F, "grp"] = "F_only"

    # 5. 결과 출력
    print("=" * 72)
    print(f"  롤링 백테스트: Facts vs Strategy  ({date_range[0].date()} ~ {date_range[-1].date()})")
    print(f"  facts 임계값: entry_score >= {FACTS_TH} (1d only)")
    print(f"  전략 임계값: trend_pullback score >= {STRAT_TH}")
    print("=" * 72)
    print()
    print(f"{'그룹':8s} {'n':>6s} {'/date':>6s} | "
          f"{'D+7 avg':>8s} {'D+7 med':>8s} {'D+7 승':>7s} | "
          f"{'D+14 avg':>9s} {'D+14 med':>9s} {'D+14 승':>8s}")
    print("-" * 72)

    order = ["S+F", "F_only", "S_only", "none"]
    for grp in order:
        sub = df[df.grp == grp].dropna(subset=["ret7", "ret14"])
        if len(sub) == 0:
            continue
        n_dates      = sub.date.nunique()
        avg_per_date = len(sub) / n_dates
        r7_mean = sub.ret7.mean();  r7_med = sub.ret7.median();  r7_win = (sub.ret7 > 0).mean()
        r14_mean = sub.ret14.mean(); r14_med = sub.ret14.median(); r14_win = (sub.ret14 > 0).mean()
        print(f"{grp:8s} {len(sub):>6d} {avg_per_date:>6.1f} | "
              f"{r7_mean:>+8.2%} {r7_med:>+8.2%} {r7_win:>6.0%} | "
              f"{r14_mean:>+9.2%} {r14_med:>+9.2%} {r14_win:>7.0%}")

    print("-" * 72)
    # 전체 기준선
    all_sub = df.dropna(subset=["ret7", "ret14"])
    r7m = all_sub.ret7.mean(); r14m = all_sub.ret14.mean()
    print(f"{'전체(기준)':8s} {len(all_sub):>6d} {'':>6s} | "
          f"{r7m:>+8.2%} {'':>8s} {'':>7s} | {r14m:>+9.2%}")

    # 날짜별 요약
    print("\n=== 날짜별 그룹 forward return (D+14) ===")
    print(f"{'날짜':12s} {'S+F(n)':>10s} {'S_only(n)':>12s} {'F_only(n)':>12s} {'none':>8s}")
    for t_date in date_range:
        sub_d = df[df.date == t_date.date()]
        parts = [str(t_date.date())]
        for grp in ["S+F", "S_only", "F_only", "none"]:
            sub_g = sub_d[sub_d.grp == grp].dropna(subset=["ret14"])
            if len(sub_g) == 0:
                parts.append("   n/a")
            else:
                parts.append(f"{sub_g.ret14.mean():+.1%}({len(sub_g)})")
        print("  " + "  ".join(f"{p:>12s}" for p in parts))

    # 저장
    df.to_parquet(OUT_DIR / "_backtest_result.parquet", index=False)
    print(f"\nsaved _backtest_result.parquet  ({len(df):,} rows)")


if __name__ == "__main__":
    main()
