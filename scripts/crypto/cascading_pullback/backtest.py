"""Cascading pullback 1h 그리드 백테스트 (최근 3일 = 72시간 × 전 종목).

매 1h candle close 시점에 score≥120 인 종목을 추출하고,
next 1h / 4h / 24h return 함께 표시.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.stdout.reconfigure(encoding="utf-8")

import warnings
warnings.filterwarnings("ignore")

import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from research.visual_review.facts import _normalize
from backtest.strategies import cascading_pullback as cp

CACHE_1H = Path("data/cache/crypto/1h")
CACHE_1D = Path("data/cache/crypto/1d")
WORKERS = 8
HOURS = 72        # 최근 3일
SCORE_TH = 120.0  # 아주 강한 풀백만


def process(sym: str, ts: pd.Timestamp,
            df_1h: pd.DataFrame, df_1d: pd.DataFrame) -> dict | None:
    df_1h_hist = df_1h[df_1h.index < ts]
    if len(df_1h_hist) < 200:
        return None
    df_1d_hist = df_1d[df_1d.index < ts] if df_1d is not None else None
    if df_1d_hist is None or len(df_1d_hist) < 60:
        return None

    res = cp.compute_cascade(df_1h_hist, df_1d_hist)
    score = float(res.get("score", 0.0))
    if score < SCORE_TH:
        return None

    close_now = float(df_1h_hist["Close"].iloc[-1])
    # next 1h / 4h / 24h
    fut = df_1h[df_1h.index >= ts]
    def _ret(n):
        if len(fut) >= n:
            return float(fut["Close"].iloc[n-1] / close_now - 1)
        return float("nan")
    ret_1h = _ret(1)
    ret_4h = _ret(4)
    ret_24h = _ret(24)

    return {
        "ts": ts,
        "symbol": sym,
        "score": score,
        "tier": int(res.get("tier", 0)),
        "imp_tf": res.get("impulse_tf") or "-",
        "pull_ma": res.get("pullback_ma") or "-",
        "closest_atr": res.get("pullback_closest_atr"),
        "react_bull": bool(res.get("react_bull")),
        "close": close_now,
        "ret_1h": ret_1h,
        "ret_4h": ret_4h,
        "ret_24h": ret_24h,
    }


def main():
    files = sorted(CACHE_1H.glob("*.parquet"))
    symbols = [f.stem for f in files]
    print(f"심볼 수: {len(symbols)}")

    print("1h/1d 캐시 선로드 ...")
    t0 = time.time()
    h_store: dict[str, pd.DataFrame] = {}
    d_store: dict[str, pd.DataFrame] = {}
    for f in files:
        sym = f.stem
        try:
            h_store[sym] = _normalize(pd.read_parquet(f))
        except Exception:
            continue
        f1d = CACHE_1D / f.name
        if f1d.exists():
            try:
                d_store[sym] = _normalize(pd.read_parquet(f1d))
            except Exception:
                pass
    print(f"  1h {len(h_store)} / 1d {len(d_store)} ({time.time()-t0:.1f}s)")

    # 시간 grid: BTC 인덱스 기준 최근 HOURS 시간
    btc = h_store["BTCUSDT"]
    ts_list = list(btc.index[-HOURS:])
    print(f"\n평가 시간: {ts_list[0]} ~ {ts_list[-1]} ({len(ts_list)}h)\n")

    rows = []
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {
            ex.submit(process, sym, ts, h_store[sym], d_store.get(sym)): (sym, ts)
            for ts in ts_list
            for sym in symbols
            if sym in h_store
        }
        done = 0
        total = len(futs)
        for fut in as_completed(futs):
            done += 1
            r = fut.result()
            if r is not None:
                rows.append(r)
            if done % 10000 == 0:
                print(f"  [{done}/{total}] {time.time()-t1:.0f}s elapsed")
    df = pd.DataFrame(rows)
    print(f"\n총 {len(df):,} 시그널 ({time.time()-t1:.1f}s)\n")

    if len(df) == 0:
        print("시그널 없음")
        return

    # 시간당 표
    print("=" * 145)
    print(f"  1H 그리드 시그널 (score >= {SCORE_TH:.0f}, 최근 {HOURS}h)")
    print(f"  표시: 시간 / 종목수 / 상위 시그널 — 'symbol(score, tier, ma, atr, react)' + next-ret")
    print("=" * 145)

    df["utc"] = df["ts"] - pd.Timedelta(hours=9)
    for ts in ts_list:
        sub = df[df.ts == ts].sort_values("score", ascending=False)
        if len(sub) == 0:
            continue
        utc_str = (ts - pd.Timedelta(hours=9)).strftime("%m-%d %H:%M")
        kst_str = ts.strftime("%m-%d %H:%M")
        n = len(sub)
        avg_1h = sub.ret_1h.mean()
        avg_4h = sub.ret_4h.mean()
        avg_24h = sub.ret_24h.mean()
        print(f"\nUTC {utc_str} (KST {kst_str})  n={n}  avg ret 1h={avg_1h:+.2%} / 4h={avg_4h:+.2%} / 24h={avg_24h:+.2%}")
        # 상위 10개
        for _, r in sub.head(10).iterrows():
            atr = r.closest_atr if r.closest_atr is not None else 0
            rb = "Y" if r.react_bull else "-"
            def _fmt(x):
                return f"{x:+6.2%}" if not pd.isna(x) else "  n/a"
            print(f"   {r.symbol:18s} s={r.score:6.1f} t{r.tier}/{r.imp_tf}/{r.pull_ma}/atr{atr:.2f}/{rb}  "
                  f"ret 1h={_fmt(r.ret_1h)}  4h={_fmt(r.ret_4h)}  24h={_fmt(r.ret_24h)}")

    # 종합
    print("\n" + "=" * 145)
    print("  전체 요약")
    print("=" * 145)
    valid = df.dropna(subset=["ret_24h"])
    if len(valid) > 0:
        print(f"전체 시그널 수: {len(df):,}  (24h 측정가능: {len(valid):,})")
        print(f"평균 next ret  1h: {df.ret_1h.mean():+.3%}  /  4h: {df.ret_4h.mean():+.3%}  /  24h: {valid.ret_24h.mean():+.3%}")
        print(f"중앙값         1h: {df.ret_1h.median():+.3%}  /  4h: {df.ret_4h.median():+.3%}  /  24h: {valid.ret_24h.median():+.3%}")
        print(f"24h 승률 (>0): {(valid.ret_24h > 0).mean():.1%}")
        print(f"24h 최대   : {valid.ret_24h.max():+.2%}  /  최소: {valid.ret_24h.min():+.2%}")

    out_path = Path("scripts/out/cp_1h_3d.parquet")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    print(f"\nsaved {out_path}  ({len(df):,} rows)")


if __name__ == "__main__":
    main()
