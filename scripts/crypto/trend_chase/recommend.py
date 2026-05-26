"""crypto trend_chase 추천 — **현재 1h 봉 시점** entry timing 점수 TOP N.

사용자 의도 (2026-05-26): "crypto 는 1h/4h 기준. 추천은 결국 타기 좋은 타점에
지금 있냐가 중요" → 1h primary `score_chase_entry_1h` 사용.

cutoff 미지정 시 1h cache 의 가장 최근 봉을 자동으로 사용.

사용:
    .venv/Scripts/python.exe -m scripts.crypto.trend_chase.recommend                  # 최신 1h 봉
    .venv/Scripts/python.exe -m scripts.crypto.trend_chase.recommend --cutoff "2026-05-26 11:00"
    .venv/Scripts/python.exe -m scripts.crypto.trend_chase.recommend --topn 30 --min-score 50
"""
from __future__ import annotations

import argparse
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

from scripts.crypto.trend_chase.scoring import (
    score_chase_entry_1h, score_chase_entry_4h, to_kr_schema, CH_ENTRY_MAX,
)

CACHE_1D = ROOT / "data" / "cache" / "crypto" / "1d"
CACHE_1H = ROOT / "data" / "cache" / "crypto" / "1h"
OUT_DIR = ROOT / "scripts" / "out"
WORKERS = 8


def _last_score(sym: str, cutoff: Optional[pd.Timestamp], tf: str = "1h") -> dict:
    try:
        p1h = CACHE_1H / f"{sym}.parquet"
        if not p1h.exists():
            return {}
        df_1h_raw = pd.read_parquet(p1h)
        df_1h = to_kr_schema(df_1h_raw)
        if cutoff is not None:
            df_1h = df_1h[df_1h.index <= cutoff]
        min_bars = 168 if tf == "1h" else 168   # 4h: 42*4 = 168h 도 동일 시간
        if len(df_1h) < min_bars:
            return {}

        df_1d = None
        p1d = CACHE_1D / f"{sym}.parquet"
        if p1d.exists():
            df_1d_raw = pd.read_parquet(p1d)
            df_1d = to_kr_schema(df_1d_raw)
            if cutoff is not None:
                df_1d = df_1d[df_1d.index <= cutoff]

        if tf == "1h":
            sc, parts = score_chase_entry_1h(df_1h, df_1d)
            dist_key = "_dist_ma10_1h"
            ret_short_key = "_ret_4h"
            stack_key = "_bull_stack_1h"
            ma10_up_key = "_ma10_strong_up_1h"
            last_ts = df_1h.index[-1]
            last_close = float(df_1h["Close"].iloc[-1])
            ret_bar = float(df_1h["Close"].pct_change(1).iloc[-1] or 0)
            amt_bar = last_close * float(df_1h["Volume"].iloc[-1])
        else:  # 4h
            sc, parts = score_chase_entry_4h(df_1h, df_1d)
            dist_key = "_dist_ma10_4h"
            ret_short_key = "_ret_4h_1bar"
            stack_key = "_bull_stack_4h"
            ma10_up_key = "_ma10_strong_up_4h"
            last_ts = parts.get("_last_ts")
            last_close = float(parts.get("_close", 0))
            # 4h ret_1bar = 4h ret
            ret_bar = float(parts.get(ret_short_key, 0))
            # 마지막 4h 봉의 거래대금 — 1h 합산 4h
            amt_bar = float("nan")  # 단순화

        return {
            "symbol": sym,
            "bar_ts": last_ts,
            "last_close": last_close,
            "ret_bar": ret_bar,
            "amt_bar": amt_bar,
            "ch_score": sc,
            "dist_ma10": parts.get(dist_key, float("nan")),
            "ret_short": parts.get(ret_short_key, float("nan")),
            "ret_24h": parts.get("_ret_24h", float("nan")),
            "ret_72h": parts.get("_ret_72h", float("nan")),
            "vol_burst_24v72": parts.get("_vol_burst", float("nan")),
            "bull_stack": parts.get(stack_key, 0),
            "ma10_strong_up": parts.get(ma10_up_key, 0),
        }
    except Exception:
        return {}


def fmt_amount_usd(a: float) -> str:
    if pd.isna(a):
        return "-"
    if a >= 1e9:
        return f"${a/1e9:.2f}B"
    if a >= 1e6:
        return f"${a/1e6:.1f}M"
    if a >= 1e3:
        return f"${a/1e3:.0f}K"
    return f"${a:.0f}"


def _auto_cutoff_from_cache() -> pd.Timestamp:
    """1h cache 의 가장 최근 timestamp (BTCUSDT 기준). UTC naive 반환."""
    p = CACHE_1H / "BTCUSDT.parquet"
    if not p.exists():
        p = next(CACHE_1H.glob("*.parquet"))
    df = pd.read_parquet(p)
    if "timestamp" in df.columns:
        return pd.to_datetime(df["timestamp"].iloc[-1], unit="ms", utc=True).tz_localize(None)
    return df.index[-1]


def _fmt_cutoff_kst(cutoff: pd.Timestamp) -> str:
    """UTC naive → 'YYYY-MM-DD HH:MM UTC (HH:MM KST)' 표시."""
    kst = (cutoff + pd.Timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")
    utc = cutoff.strftime("%Y-%m-%d %H:%M")
    return f"{utc} UTC / {kst} KST"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", default=None,
                    help="cutoff 시각 (예: '2026-05-26 11:00'). 미지정 시 1h cache 의 가장 최근 봉 자동.")
    ap.add_argument("--tf", default="1h", choices=("1h", "4h"),
                    help="entry 점수 평가 봉 단위 (기본 1h). 4h 면 1h cache 를 4h 리샘플 후 4h 봉 last 시점 평가.")
    ap.add_argument("--topn", type=int, default=20)
    ap.add_argument("--min-score", type=float, default=40.0,
                    help="이 점수 미만 제외. 기본 40 (임시, entry score 백테스트 전).")
    args = ap.parse_args()

    cutoff = pd.Timestamp(args.cutoff) if args.cutoff else _auto_cutoff_from_cache()
    print(f"=== Crypto CHASE entry 추천 ({args.tf} 봉 primary, cutoff = {_fmt_cutoff_kst(cutoff)}) ===")
    print(f"    threshold ≥ {args.min_score} (entry score, 백테스트 미검증 임시값)\n")

    syms = sorted(p.stem for p in CACHE_1H.glob("*.parquet"))
    rows = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(_last_score, sym, cutoff, args.tf) for sym in syms]
        for fut in as_completed(futs):
            r = fut.result()
            if r:
                rows.append(r)

    df = pd.DataFrame(rows)
    if df.empty:
        print("점수 산출 결과 없음")
        return

    df["ch_pct"] = (df["ch_score"] / CH_ENTRY_MAX * 100).round(1)
    if args.tf == "1h":
        df["거래대금"] = df["amt_bar"].apply(fmt_amount_usd)
    else:
        df["거래대금"] = "-"  # 4h 합산은 단순화 (생략)
    df["ret_bar_str"] = (df["ret_bar"] * 100).round(2).astype(str) + "%"

    qualified = df[df["ch_score"] >= args.min_score].copy()
    n_qual = len(qualified)
    print(f"전체 {len(df)} 종목 중 threshold 통과: {n_qual}")
    if n_qual == 0:
        print(f"(임계점수 ≥ {args.min_score} 통과 종목 없음 — --min-score 0 으로 강제 출력 가능)")
        return

    top = qualified.sort_values("ch_score", ascending=False).head(args.topn).copy()
    top["ch_score_fmt"] = top["ch_score"].round(0).astype(int).astype(str) + f"/{CH_ENTRY_MAX}"
    for c in ("ret_short", "ret_24h", "ret_72h", "dist_ma10", "vol_burst_24v72"):
        if c in top.columns:
            top[c] = top[c].round(3)
    ret_bar_label = "ret_1h" if args.tf == "1h" else "ret_4h(=1bar)"
    ret_short_label = "ret_4h" if args.tf == "1h" else "ret_4h_1bar"  # 4h: same as ret_bar
    cols = ["symbol", "거래대금", "ret_bar_str", "ch_score_fmt", "ch_pct",
            "dist_ma10", "ret_short", "ret_24h", "ret_72h", "vol_burst_24v72",
            "bull_stack", "ma10_strong_up"]
    top_show = top[cols].rename(columns={
        "ret_bar_str": ret_bar_label, "ch_score_fmt": "ch_score",
        "ret_short": ret_short_label, "ma10_strong_up": "MA10↑",
    })
    print(top_show.to_string(index=False))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cutoff_str = cutoff.strftime("%Y%m%d_%H%M")
    out_csv = OUT_DIR / f"crypto_chase_entry_{args.tf}_{cutoff_str}.csv"
    df.sort_values("ch_score", ascending=False).to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n전체 저장: {out_csv}")


if __name__ == "__main__":
    main()
