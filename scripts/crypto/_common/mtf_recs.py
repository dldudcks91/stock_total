"""Multi-TF (1h+4h+1d) trend_chase / trend_pullback 추천 점수 — 최근 N시간 시점별 TOP N.

사용자 의도 (2026-05-27):
  - 매시간 cutoff 에서, 각 코인을 1h, 4h, 1d 의 MA10/MA20 기반 점수로 평가.
  - 세 TF 점수를 합쳐 종합 점수 산출. 두 전략 각각 TOP N 코인 행=시간 표로 표시.

점수 소스 (2026-05-27 backtest/strategies 에서 scripts/ 로 전환):
  - scripts.crypto.trend_chase.scoring.score_chase_crypto_tf(df)       # Series
  - scripts.crypto.trend_pullback.scoring.score_pullback_crypto_tf(df) # Series

  각 TF (1h, 4h, 1d) 에서 위 함수 호출 → 종합 = sum(1h, 4h, 1d) → 이론상 0~300.
  scripts/ 버전은 음수 floor + 하드 게이트 없음 (soft components) — backtest 버전의
  "게이트 flip 으로 0→100 점프" 문제 해소.

핵심 트레이드오프:
  - score_pullback_crypto_tf 와 score_chase_crypto_tf 는 KR 일봉 컨벤션 (10/30/252 bar
    rolling) 을 TF 무관 적용. 1h 에선 250봉 ≈ 10일, 1d 에선 250봉 ≈ 1년 — 의미가
    TF별로 다르지만 패턴 채점 자체는 일관됨 (의도적).

산출:
  recent_top_recs(hours=24, top_n=10) → DataFrame (rows=hour ts KST,
    cols=[chase_top10, pullback_top10], cell = "BTCUSDT(85), ETHUSDT(82), ...")

CLI:
  .venv/Scripts/python.exe -m scripts.crypto._common.mtf_recs            # 최근 24h, top10
  .venv/Scripts/python.exe -m scripts.crypto._common.mtf_recs --hours 48 --top 15
"""
from __future__ import annotations

import argparse
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

from scripts.crypto.trend_chase.scoring import score_chase_mtf
from scripts.crypto.trend_pullback.scoring import score_pullback_crypto_tf

CACHE_1H = ROOT / "data" / "cache" / "crypto" / "1h"
CACHE_1D = ROOT / "data" / "cache" / "crypto" / "1d"
OUT_DIR = ROOT / "scripts" / "out"
WORKERS = 6


# ─────────────────────────────────────────────────────────────
# 추천 대상 제외 블랙리스트 (2026-05-27)
# 사유: 점수 산식이 degenerate 하게 만점을 주는 종목들
#   - stablecoin: USDCUSDT 가격 ≈ $1, 잔파동만 → 모든 MA 근접/정배열 자동 통과
#   - RWA(토큰화 주식·ETF·원자재): 실시계열이라 crypto 와 패턴 다름 (24시간 거래 X,
#     갭 존재). Bitget contracts API 의 `isRwa==YES` 로 자동 식별 (108개, 2026-05-27).
#
# RWA 리스트 갱신: `.venv/Scripts/python.exe -m data.sources.bitget_rwa`
# (crypto-fetch 시 자동 갱신되도록 hook 예정. 캐시 없으면 hardcoded fallback 사용.)
# ─────────────────────────────────────────────────────────────
from data.sources.bitget_rwa import load_rwa_cache

STABLECOINS = {"USDCUSDT"}  # Bitget USDT-M 페그 유지 stablecoin (FRAX 는 페그 깨짐, 제외 X)

# Fallback — RWA 캐시 미생성 시 사용 (구 hardcoded STOCK_TOKENS, 19개만)
_FALLBACK_STOCK_TOKENS = {
    "AAPLUSDT", "AMDUSDT", "AMZNUSDT", "ARMUSDT", "COINUSDT", "COPPERUSDT",
    "COSTUSDT", "GOOGLUSDT", "INTCUSDT", "JDUSDT", "METAUSDT", "MRVLUSDT",
    "MSFTUSDT", "NFLXUSDT", "NVDAUSDT", "QQQUSDT", "SPYUSDT", "TSLAUSDT", "UNHUSDT",
}


def _build_blacklist() -> set:
    """RWA 캐시 + STABLECOINS 합집합. 캐시 없으면 fallback."""
    rwa = load_rwa_cache()
    if not rwa:
        print("  [warn] RWA 캐시 없음 — fallback STOCK_TOKENS(19) 사용. "
              "갱신: python -m data.sources.bitget_rwa")
        return STABLECOINS | _FALLBACK_STOCK_TOKENS
    return STABLECOINS | rwa


BLACKLIST = _build_blacklist()


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _to_dt_index(df: pd.DataFrame) -> pd.DataFrame:
    """timestamp(ms) 컬럼 → naive UTC DatetimeIndex. 이미 DatetimeIndex 면 그대로."""
    if isinstance(df.index, pd.DatetimeIndex):
        return df.sort_index()
    if "timestamp" in df.columns:
        out = df.copy()
        out["dt"] = pd.to_datetime(out["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
        out = out.set_index("dt").sort_index()
        return out
    return df


def _resample_to_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """1h OHLCV → 4h OHLCV. lowercase 그대로."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "amount" in df_1h.columns:
        agg["amount"] = "sum"
    return df_1h.resample("4h", label="left", closed="left").agg(agg).dropna(subset=["close"])


def _score_one_tf(df_tf: pd.DataFrame, scorer) -> pd.Series:
    """단일 TF 에서 전략 점수 Series 산출. scorer = callable(df) -> Series. NaN → 0."""
    try:
        s = scorer(df_tf)
        return s.fillna(0.0)
    except Exception:
        return pd.Series(0.0, index=df_tf.index)


# ─────────────────────────────────────────────────────────────
# Per-symbol: 1h-frequency combined score series for both strategies
# ─────────────────────────────────────────────────────────────
def _symbol_scores(sym: str, end_ts: pd.Timestamp,
                   start_ts: pd.Timestamp) -> Optional[dict]:
    """한 종목의 1h/4h/1d 점수를 1h 인덱스로 align 한 chase/pullback combined Series.

    Args:
      sym       : 심볼 (e.g. "BTCUSDT")
      end_ts    : 종료 cutoff (naive UTC). 이 시각 이전 데이터만 사용.
      start_ts  : 결과 인덱스의 시작 (보통 end_ts - hours)

    Returns:
      {"chase": Series(1h idx, sum 0~300), "pullback": Series(1h idx, sum 0~300)} or None
    """
    p1h = CACHE_1H / f"{sym}.parquet"
    if not p1h.exists():
        return None
    df_1h = _to_dt_index(pd.read_parquet(p1h))
    df_1h = df_1h[df_1h.index <= end_ts]
    # 1h core 지표가 안정적으로 잡히려면 최소 ~250 봉 + lookback
    if len(df_1h) < 300:
        return None

    p1d = CACHE_1D / f"{sym}.parquet"
    if p1d.exists():
        df_1d = _to_dt_index(pd.read_parquet(p1d))
        df_1d = df_1d[df_1d.index <= end_ts]
    else:
        # 1d cache 없으면 1h 에서 즉석 리샘플 (label='left', closed='left' → UTC 자정 시작)
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        if "amount" in df_1h.columns:
            agg["amount"] = "sum"
        df_1d = df_1h.resample("1D", label="left", closed="left").agg(agg).dropna(subset=["close"])

    df_4h = _resample_to_4h(df_1h)

    # 1w 리샘플 (1d 캐시 → W-MON, label='left', closed='left' — CLAUDE.md 시간 표준)
    agg_w = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "amount" in df_1d.columns:
        agg_w["amount"] = "sum"
    df_1w = df_1d.resample("W-MON", label="left", closed="left").agg(agg_w).dropna(subset=["close"])

    out = {}

    # chase — MTF v3 (1h+4h+1d+1w 게이트 통과 시 점수 살아남음)
    try:
        s_chase = score_chase_mtf(df_1h, df_4h, df_1d, df_1w).fillna(0.0)
    except Exception:
        s_chase = pd.Series(0.0, index=df_1h.index)
    out["chase"] = s_chase.loc[(s_chase.index >= start_ts) & (s_chase.index <= end_ts)]

    # pullback — TF-by-TF 합 (기존 유지)
    s_1h_pb = _score_one_tf(df_1h, score_pullback_crypto_tf)
    s_4h_pb = _score_one_tf(df_4h, score_pullback_crypto_tf).reindex(df_1h.index, method="ffill").fillna(0.0)
    s_1d_pb = _score_one_tf(df_1d, score_pullback_crypto_tf).reindex(df_1h.index, method="ffill").fillna(0.0)
    combined_pb = (s_1h_pb + s_4h_pb + s_1d_pb)
    out["pullback"] = combined_pb.loc[(combined_pb.index >= start_ts) & (combined_pb.index <= end_ts)]

    return {"sym": sym, **out}


def _symbol_scores_safe(args):
    sym, end_ts, start_ts = args
    try:
        return _symbol_scores(sym, end_ts, start_ts)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# 전체 종목 × 시각 매트릭스
# ─────────────────────────────────────────────────────────────
def compute_score_matrix(end_ts: pd.Timestamp, hours: int = 24,
                         symbols: Optional[list] = None,
                         workers: int = WORKERS) -> dict:
    """모든 심볼 × 최근 hours 시각 → 두 전략 점수 매트릭스.

    Returns:
      {"chase": DataFrame(idx=hour ts, cols=symbols), "pullback": ...}
    """
    if symbols is None:
        symbols = sorted(p.stem for p in CACHE_1H.glob("*.parquet"))
    # 블랙리스트 제외 (stablecoin + 주식 토큰화 종목 — degenerate 점수)
    n_total = len(symbols)
    symbols = [s for s in symbols if s not in BLACKLIST]
    n_excluded = n_total - len(symbols)
    start_ts = end_ts - pd.Timedelta(hours=hours - 1)

    chase_cols, pullback_cols = {}, {}
    args = [(s, end_ts, start_ts) for s in symbols]
    print(f"  scoring {len(symbols)} symbols across {hours}h "
          f"(workers={workers}, blacklist 제외={n_excluded}) ...")
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_symbol_scores_safe, a) for a in args]
        for fut in as_completed(futs):
            r = fut.result()
            done += 1
            if done % 100 == 0:
                print(f"    {done}/{len(symbols)}")
            if not r:
                continue
            sym = r["sym"]
            chase_cols[sym] = r["chase"]
            pullback_cols[sym] = r["pullback"]

    chase_df = pd.DataFrame(chase_cols)
    pullback_df = pd.DataFrame(pullback_cols)
    return {"chase": chase_df, "pullback": pullback_df}


# ─────────────────────────────────────────────────────────────
# TOP N 표 포맷 (rows=hour ts KST)
# ─────────────────────────────────────────────────────────────
def _top_n_per_row(score_df: pd.DataFrame, n: int, min_score: float = 1.0) -> pd.Series:
    """행마다 점수 내림차순 TOP n 심볼을 'SYM(score), ...' 문자열로."""
    def _row(r):
        s = r.dropna()
        s = s[s >= min_score]
        if s.empty:
            return ""
        top = s.sort_values(ascending=False).head(n)
        return ", ".join(f"{sym}({int(round(sc))})" for sym, sc in top.items())
    return score_df.apply(_row, axis=1)


def recent_top_recs(hours: int = 24, top_n: int = 10,
                    end_ts: Optional[pd.Timestamp] = None,
                    min_score: float = 1.0,
                    symbols: Optional[list] = None,
                    workers: int = WORKERS) -> pd.DataFrame:
    """최근 hours 시간 매시간 × 두 전략 TOP n 코인 추천 표.

    rows = hour timestamp (KST 표시), cols = [chase_top{n}, pullback_top{n}].
    """
    if end_ts is None:
        # 1h cache 의 가장 최근 봉 (BTCUSDT 기준)
        p = CACHE_1H / "BTCUSDT.parquet"
        if not p.exists():
            p = next(CACHE_1H.glob("*.parquet"))
        df = pd.read_parquet(p)
        end_ts = pd.to_datetime(df["timestamp"].iloc[-1], unit="ms", utc=True).tz_localize(None)
        # 가장 최근 완성된 1h 봉으로 floor
        end_ts = end_ts.floor("1h")

    mats = compute_score_matrix(end_ts, hours=hours, symbols=symbols, workers=workers)
    chase_top = _top_n_per_row(mats["chase"], top_n, min_score)
    pull_top = _top_n_per_row(mats["pullback"], top_n, min_score)

    idx_kst = chase_top.index + pd.Timedelta(hours=9)
    out = pd.DataFrame({
        f"chase_top{top_n}": chase_top.values,
        f"pullback_top{top_n}": pull_top.values,
    }, index=idx_kst.strftime("%Y-%m-%d %H:%M KST"))
    out.index.name = "ts"
    # 시간 내림차순 (최신이 위)
    return out.iloc[::-1]


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--cutoff", default=None,
                    help="종료 cutoff (UTC, e.g. '2026-05-27 02:00'). 미지정 시 1h cache 최신.")
    ap.add_argument("--min-score", type=float, default=1.0,
                    help="이 점수 미만 심볼은 표에서 제외 (default 1.0).")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--out-csv", default=None, help="결과 CSV 저장 경로 (옵션).")
    args = ap.parse_args()

    end_ts = pd.Timestamp(args.cutoff) if args.cutoff else None
    print(f"=== MTF Crypto Recs (last {args.hours}h, TOP {args.top}) ===")
    df = recent_top_recs(hours=args.hours, top_n=args.top, end_ts=end_ts,
                         min_score=args.min_score, workers=args.workers)
    print()
    # 한 줄에 길이 제한 — 표시용으로만 truncate
    with pd.option_context("display.max_colwidth", 200, "display.width", 220):
        print(df.to_string())

    if args.out_csv is None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        end_str = (end_ts or pd.Timestamp.utcnow().tz_localize(None)).strftime("%Y%m%d_%H%M")
        args.out_csv = str(OUT_DIR / f"crypto_mtf_recs_{end_str}.csv")
    df.to_csv(args.out_csv, encoding="utf-8-sig")
    print(f"\n저장: {args.out_csv}")


if __name__ == "__main__":
    main()
