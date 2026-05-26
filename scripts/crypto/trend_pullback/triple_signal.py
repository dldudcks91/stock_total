"""facts + trend_pullback + reviews 세 시그널 합산 추천."""
from __future__ import annotations
import sys, warnings, time
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[3]))
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from research.visual_review.facts import _normalize
from backtest.strategies import trend_pullback

CACHE_1D = Path("data/cache/crypto/1d")
REVIEW_DATE = "2026-05-21"
STOCK_TOKENS = {
    "AAPLUSDT","AMDUSDT","AMZNUSDT","ARMUSDT","COINUSDT","COPPERUSDT",
    "COSTUSDT","GOOGLUSDT","INTCUSDT","JDUSDT","METAUSDT","MRVLUSDT",
    "MSFTUSDT","NFLXUSDT","NVDAUSDT","QQQUSDT","SPYUSDT","TSLAUSDT","UNHUSDT",
}
STATE_MAP = {
    "A2":1.0,"B5":0.95,"A1":0.85,"B4":0.55,"B3":0.30,
    "A3":0.10,"A4":-0.30,"A5":-0.50,"B1":-0.40,"B2":-0.20,"C1":-0.50,
}


def get_tp_score(sym: str) -> tuple[str, float]:
    f = CACHE_1D / f"{sym}.parquet"
    if not f.exists():
        return sym, float("nan")
    try:
        raw = pd.read_parquet(f)
        nd  = _normalize(raw)
        ld  = nd.rename(columns={c: c.lower() for c in nd.columns})
        s   = trend_pullback.score(ld, {})
        return sym, float(s.iloc[-1])
    except Exception:
        return sym, float("nan")


def main():
    # 1. reviews
    cs = pd.read_parquet("data/cache/crypto/visual_review/coin_state.parquet")
    cs = cs[cs["last_review_date"].astype(str) == REVIEW_DATE].copy()
    cs = cs[~cs["symbol"].isin(STOCK_TOKENS)]
    cs = cs[cs["verdict"] != "reject"]
    rf = cs["risk_flags"].fillna("").astype(str)
    cs = cs[~rf.str.contains("pump_dump_trace")]
    cs = cs[~rf.str.contains("zombie")]
    print(f"리뷰 통과: {len(cs)}개")

    # 2. facts entry_score
    fe = pd.read_parquet("data/cache/crypto/visual_review/_scan_entry_v2.parquet")[["symbol","entry_score"]]

    # 3. trend_pullback score
    print("trend_pullback 점수 계산 중...")
    t0 = time.time()
    tp_rows = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(get_tp_score, sym): sym for sym in cs["symbol"]}
        for fut in as_completed(futs):
            sym, sc = fut.result()
            tp_rows.append({"symbol": sym, "tp_score": sc})
    print(f"완료 ({time.time()-t0:.1f}s)")

    # 4. 병합
    df = cs[["symbol","state_1w","state_1d","micro_action_1d","volume_flag_1d",
             "tf_consistency","verdict_confidence","verdict","risk_flags"]].copy()
    df = df.merge(fe, on="symbol", how="left")
    df = df.merge(pd.DataFrame(tp_rows), on="symbol", how="left")

    # 정규화 후 합산 (rev 35% / entry 40% / tp 25%)
    df["ent_n"] = df["entry_score"].clip(-1, 2).map(lambda x: (x + 1) / 3)
    df["tp_n"]  = df["tp_score"].clip(0, 100) / 100
    rev = (df["state_1w"].map(STATE_MAP).fillna(0) * 0.5
           + df["state_1d"].map(STATE_MAP).fillna(0) * 0.5).clip(-1, 1)
    df["rev_n"]    = (rev + 1) / 2
    df["combined"] = df["rev_n"] * 0.35 + df["ent_n"] * 0.40 + df["tp_n"] * 0.25

    df = df.sort_values("combined", ascending=False)

    # 5. 출력
    print()
    hdr = f"{'심볼':12s} {'합산':>6s} {'entry':>6s} {'tp':>5s} {'1w':>4s} {'1d':>4s} {'micro':>16s} {'tf':>4s}  리스크"
    print(hdr)
    print("-" * len(hdr))
    for _, r in df.head(25).iterrows():
        risks = (str(r["risk_flags"] or "")
                 .replace("low_history", "LH")
                 .replace("drawdown_deep", "DD")
                 .replace("accumulation_suspect", "ACC")
                 .replace("parabolic", "PAR")
                 .strip(",").strip())
        print(
            f"{r['symbol']:12s} {r['combined']:>6.3f} {r['entry_score']:>+6.2f}"
            f" {r['tp_score']:>5.0f} {str(r['state_1w']):>4s} {str(r['state_1d']):>4s}"
            f" {str(r['micro_action_1d']):>16s} {str(r['tf_consistency']):>4s}  {risks}"
        )


if __name__ == "__main__":
    main()
