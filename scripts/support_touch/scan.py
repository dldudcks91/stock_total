"""특정 이평선에 2~3번 닿고 튀어오르는 (= 지지 테스트 성공) 패턴 스캐너.

사용자 직관:
  - 가격이 MA 위에 있고
  - 주기적으로 MA로 pullback (위에서 내려와 닿음)
  - 매번 닿은 뒤 다시 위로 반등
  - 이 패턴이 2~3회 반복된 종목

QUIET_BOTTOM 의 "박치기 거름"과 반대 — 여기서는 "지지 테스트 성공"을 찾는다.

크립토 전 종목에 대해 3가지 설정으로 스캔:
  1) 1d × MA20  (정석 스윙)
  2) 4h × MA20  (단기 스윙)
  3) 1h × MA10  (단기/노이즈)

출력: 각 설정별 top 후보 + 다중 해상도에 동시 등장한 consensus 후보.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from data.resample import load  # noqa: E402

CACHE_1H = PROJECT_ROOT / "data" / "cache" / "crypto" / "1h"

CONFIGS = [
    {"label": "1d_MA20", "interval": "1d", "ma": 20, "lookback": 60,  "min_sep": 3, "tol": 0.010},
    {"label": "4h_MA20", "interval": "4h", "ma": 20, "lookback": 80,  "min_sep": 3, "tol": 0.010},
    {"label": "1h_MA10", "interval": "1h", "ma": 10, "lookback": 100, "min_sep": 2, "tol": 0.008},
]

MIN_BARS = 200          # 최소 봉 수 (충분한 히스토리)
MIN_AMOUNT_USDT = 1e6   # 최근 30봉 평균 거래대금 (유동성 필터)


def detect_support_touch(df: pd.DataFrame, ma_period: int, lookback: int,
                         min_separation: int, tol: float) -> Optional[dict]:
    """MA에 위에서 닿고 다시 튀어오르는 패턴 검출.

    터치 정의:
      - low <= MA × (1+tol)  (가격이 아래로 MA를 건드림)
      - close > MA × (1-tol)  (그래도 종가는 MA 근처/위에서 마감)

    터치 이벤트는 min_separation 이상 떨어진 첫 터치만 카운트 (연속 봉 통합).
    """
    if len(df) < max(ma_period * 3, MIN_BARS):
        return None

    close = df["close"].astype("float64").reset_index(drop=True)
    low = df["low"].astype("float64").reset_index(drop=True)
    high = df["high"].astype("float64").reset_index(drop=True)
    amount = df["amount"].astype("float64").reset_index(drop=True) if "amount" in df.columns else None

    ma = close.rolling(ma_period, min_periods=ma_period).mean()
    if ma.isna().iloc[-1]:
        return None

    # 현재 위에 있고 MA 상승 중이어야 함
    above_now = close.iloc[-1] > ma.iloc[-1]
    ma_rising = ma.iloc[-1] > ma.iloc[-max(5, ma_period // 4)]
    if not (above_now and ma_rising):
        return None

    # 유동성 필터
    if amount is not None:
        recent_amount = amount.iloc[-30:].mean()
        if pd.isna(recent_amount) or recent_amount < MIN_AMOUNT_USDT:
            return None

    n = len(close)
    cutoff = n - lookback

    touched = (low <= ma * (1 + tol)) & (close > ma * (1 - tol))
    above = low > ma * (1 + tol)

    # 터치 이벤트 통합 (min_separation 이상 띄어진 것만 새 이벤트)
    events = []
    last = -min_separation - 1
    for i in range(ma_period, n):
        if pd.isna(ma.iloc[i]):
            continue
        if touched.iloc[i] and (i - last) >= min_separation:
            events.append(i)
            last = i

    recent_events = [t for t in events if t >= cutoff]
    n_touches = len(recent_events)

    if n_touches < 2:
        return None

    # 각 터치 후 반등 확인: 터치 후 5봉(또는 다음 터치 전) 안에 close가 MA 위로 회복
    bounces = 0
    for k, t in enumerate(recent_events):
        end = recent_events[k + 1] if k + 1 < len(recent_events) else min(t + 10, n - 1)
        window_close = close.iloc[t : end + 1]
        window_ma = ma.iloc[t : end + 1]
        if (window_close > window_ma).any() and window_close.max() > close.iloc[t]:
            bounces += 1

    if bounces < 2:
        return None

    # 가장 마지막 터치 이후 현재까지 너무 멀지 않게 (스토리 진행 중인 종목 선호)
    last_touch_age = n - 1 - recent_events[-1]
    if last_touch_age > lookback // 2:
        return None

    # MA 상승 강도 (최근 ma_period 봉 동안 변화율)
    ma_slope_pct = (ma.iloc[-1] / ma.iloc[-ma_period] - 1) * 100 if ma.iloc[-ma_period] > 0 else 0

    # 현재 MA로부터 거리 (%)
    dist_from_ma = (close.iloc[-1] / ma.iloc[-1] - 1) * 100

    # 스코어: 터치 횟수가 2~3에 가까울수록 + 반등 % + MA 상승률
    sweet_spot = 1.0 - min(abs(n_touches - 2.5), 3.0) / 3.0
    score = sweet_spot * 50 + bounces * 10 + ma_slope_pct + min(dist_from_ma, 20)

    return {
        "n_touches": n_touches,
        "bounces": bounces,
        "touch_indices": recent_events,
        "last_touch_age_bars": last_touch_age,
        "ma_now": float(ma.iloc[-1]),
        "close_now": float(close.iloc[-1]),
        "dist_from_ma_pct": dist_from_ma,
        "ma_slope_pct": ma_slope_pct,
        "score": score,
    }


def list_symbols() -> "list[str]":
    return sorted(p.stem for p in CACHE_1H.glob("*.parquet"))


def scan_config(symbols: "list[str]", cfg: dict) -> pd.DataFrame:
    rows = []
    for sym in symbols:
        try:
            df = load(sym, cfg["interval"])
        except Exception:
            continue
        res = detect_support_touch(df, cfg["ma"], cfg["lookback"], cfg["min_sep"], cfg["tol"])
        if res is None:
            continue
        rows.append({"symbol": sym, **res})
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    return out


def main() -> int:
    global MIN_BARS, MIN_AMOUNT_USDT
    from scripts._common.run_helper import parse_args, update_config, resolve_config_path

    def add_args(ap):
        ap.add_argument("--min-bars", type=int, default=None,
                        help="minimum bars of history required")
        ap.add_argument("--min-amount-usdt", type=float, default=None,
                        help="liquidity floor (avg of last 30 bars amount)")
        ap.add_argument("--top", type=int, default=20,
                        help="print top-N per config")

    defaults = {"min_bars": MIN_BARS, "min_amount_usdt": MIN_AMOUNT_USDT, "top": 20}
    out_dir, params, args = parse_args(add_args, defaults, "support_touch.scan")

    MIN_BARS = int(params["min_bars"])
    MIN_AMOUNT_USDT = float(params["min_amount_usdt"])
    top_n = int(params["top"])

    symbols = list_symbols()
    print(f"scanning {len(symbols)} symbols × {len(CONFIGS)} configs")

    results = {}
    for cfg in CONFIGS:
        print(f"\n=== {cfg['label']}  (interval={cfg['interval']}, MA={cfg['ma']}, lookback={cfg['lookback']}봉) ===")
        df = scan_config(symbols, cfg)
        results[cfg["label"]] = df
        if df.empty:
            print("  (no candidates)")
            continue
        top = df.head(top_n).copy()
        top["touch_idx"] = top["touch_indices"].apply(lambda xs: ",".join(map(str, xs[-4:])))
        print(top[["symbol", "n_touches", "bounces", "last_touch_age_bars",
                   "dist_from_ma_pct", "ma_slope_pct", "score"]].to_string(index=False,
                       float_format=lambda x: f"{x:.2f}"))

    # consensus: 2개 이상 config에 동시 등장
    sets = {label: set(df["symbol"].head(50)) for label, df in results.items() if not df.empty}
    consensus_rows = []
    if len(sets) >= 2:
        all_syms = set().union(*sets.values())
        for s in all_syms:
            hits = [lbl for lbl, sset in sets.items() if s in sset]
            if len(hits) >= 2:
                consensus_rows.append({"symbol": s, "hits": ",".join(hits), "n_hits": len(hits)})
        if consensus_rows:
            print("\n=== CONSENSUS (2+ configs 동시 등장, top50 기준) ===")
            cdf = pd.DataFrame(consensus_rows).sort_values("n_hits", ascending=False)
            print(cdf.to_string(index=False))
        else:
            print("\n=== CONSENSUS: none ===")

    saved = []
    for label, df in results.items():
        if df.empty:
            continue
        path = out_dir / f"support_touch_{label}.csv"
        df.drop(columns=["touch_indices"]).to_csv(path, index=False)
        saved.append((label, len(df)))
    if consensus_rows:
        cpath = out_dir / "support_touch_consensus.csv"
        pd.DataFrame(consensus_rows).sort_values("n_hits", ascending=False).to_csv(cpath, index=False)
    print(f"\nsaved per-config CSVs to {out_dir}")

    cfg_path = resolve_config_path(args)
    if cfg_path is not None:
        update_config(cfg_path,
                       params={"min_bars": MIN_BARS,
                               "min_amount_usdt": MIN_AMOUNT_USDT,
                               "top": top_n,
                               "configs": CONFIGS},
                       data={"asset": "crypto",
                             "cache_dir": "data/cache/crypto (1h/4h/1d)",
                             "symbol_count": len(symbols)},
                       results_summary={
                           "candidates_per_config": {lbl: n for lbl, n in saved},
                           "n_consensus": len(consensus_rows),
                       })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
