"""Wyckoff Spring (liquidity sweep) 패턴 스캐너.

4H 봉 기준으로 SMA20을 잠깐 침범했다가 즉시 회복 + 거래량 스파이크 +
하단 꼬리 우세 봉을 찾고, 그 이후 forward return 분포를 집계한다.

Spring 검출 룰 (strict, 4H bar):
  0. close > Weekly SMA10            (상승 추세 컨텍스트)
  1. low  < SMA20 - α·ATR            (꼬리가 지지선 깊게 침범, α=1.0)
  2. close > SMA20                   (종가는 회복)
  3. lower_wick / range > 0.6        (하단 꼬리 우세, 핀바)
  4. body / range > 0.2              (도지 제외)
  5. close > (high + low) / 2        (종가가 봉 상단 절반)
  6. volume > rolling_mean(20)·2.5   (진짜 패닉 매도)
  7. **next bar follow-through**     (다음 봉이 강한 양봉)
       next_close > spring.close × (1 + 0.5·ATR/close)
       OR next_high > spring.high
  8. (사후) 다음 N봉 안에 close > spring.high  (= 'confirmed' spring)

forward return은 **follow-through 봉(i+1) close 대비** +6 / +12 / +24 / +48
4H봉 후 close (= 24h / 48h / 96h / 192h 후) 의 % 수익률.
→ 진입은 follow-through 봉 종가에서 가능 (look-ahead 없음).

사용:
    python scripts/spring_scan.py
    python scripts/spring_scan.py --tier trend --min-events 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.resample import load  # noqa: E402

CACHE_DIR = ROOT / "data" / "cache"
CLASSIFICATION_PATH = CACHE_DIR / "classification.parquet"

FORWARD_HORIZONS = [6, 12, 24, 48]  # 4H 봉 단위 → 24h / 48h / 96h / 192h


def _weekly_sma10_on_4h(symbol: str, df_4h: pd.DataFrame, window: int = 10) -> np.ndarray:
    """주봉 SMA10을 4H 봉 타임라인에 ffill로 정렬해서 반환.

    주봉 SMA10[t]는 t주 종가를 포함하므로, 다음 주가 시작될 때까지만 사용해야
    look-ahead가 없다. asof-merge로 '직전 주의 종가까지로 계산된 SMA10'을 매핑.
    """
    df_w = load(symbol, "1w")
    if len(df_w) < window:
        return np.full(len(df_4h), np.nan)
    sma_w = df_w["close"].rolling(window).mean()
    weekly = pd.DataFrame({
        "ts_close": df_w["timestamp"].astype("int64") + (7 * 24 * 3600 * 1000) - 1,
        "sma10w": sma_w,
    }).dropna()
    if weekly.empty:
        return np.full(len(df_4h), np.nan)

    bars_4h = pd.DataFrame({"ts": df_4h["timestamp"].astype("int64")})
    bars_4h["_idx"] = np.arange(len(bars_4h))
    merged = pd.merge_asof(
        bars_4h.sort_values("ts"),
        weekly.sort_values("ts_close"),
        left_on="ts",
        right_on="ts_close",
        direction="backward",
    ).sort_values("_idx")
    return merged["sma10w"].to_numpy()


def detect_springs(
    df: pd.DataFrame,
    sma_window: int = 20,
    atr_window: int = 14,
    alpha: float = 1.0,
    wick_ratio_min: float = 0.6,
    body_ratio_min: float = 0.2,
    close_upper_half: bool = True,
    vol_mult: float = 2.5,
    vol_window: int = 20,
    confirm_window: int = 6,
    followthrough_atr: float = 0.5,
    weekly_sma10: np.ndarray | None = None,
) -> pd.DataFrame:
    """주어진 OHLCV(4H 가정)에서 strict spring 봉을 검출.

    Spring 봉(i) 직후 봉(i+1)의 follow-through까지 확인한 뒤 등록.
    forward return은 i+1 봉 close 기준으로 측정 (실거래 가능 시점).
    """
    n_min = max(sma_window, atr_window, vol_window) + confirm_window + 2
    if len(df) < n_min:
        return pd.DataFrame()

    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    v = df["volume"].to_numpy()

    sma = pd.Series(c).rolling(sma_window).mean().to_numpy()

    tr = np.maximum.reduce([
        h - l,
        np.abs(h - np.roll(c, 1)),
        np.abs(l - np.roll(c, 1)),
    ])
    tr[0] = h[0] - l[0]
    atr = pd.Series(tr).rolling(atr_window).mean().to_numpy()

    vol_ma = pd.Series(v).rolling(vol_window).mean().to_numpy()

    rng = np.maximum(h - l, 1e-12)
    lower_wick = np.minimum(o, c) - l
    body = np.abs(c - o)
    wick_ratio = lower_wick / rng
    body_ratio = body / rng
    midpoint = (h + l) / 2.0

    cond_pierce = l < (sma - alpha * atr)
    cond_close_above = c > sma
    cond_wick = wick_ratio > wick_ratio_min
    cond_body = body_ratio > body_ratio_min
    cond_close_upper = c > midpoint if close_upper_half else np.ones_like(c, dtype=bool)
    cond_vol = v > vol_ma * vol_mult

    raw = (
        cond_pierce
        & cond_close_above
        & cond_wick
        & cond_body
        & cond_close_upper
        & cond_vol
    )
    if weekly_sma10 is not None:
        cond_uptrend = (~np.isnan(weekly_sma10)) & (c > weekly_sma10)
        raw = raw & cond_uptrend
    raw[: max(sma_window, atr_window, vol_window)] = False
    raw[-1] = False  # 다음 봉 follow-through 확인 필요

    # follow-through: 다음 봉 i+1 검증
    next_close = np.roll(c, -1)
    next_high = np.roll(h, -1)
    ft_threshold = c * (1 + followthrough_atr * np.divide(atr, c, out=np.zeros_like(c), where=c > 0))
    cond_ft = (next_close > ft_threshold) | (next_high > h)
    raw = raw & cond_ft

    if not raw.any():
        return pd.DataFrame()

    idx = np.where(raw)[0]
    rows = []
    for i in idx:
        # 진입 시점 = i+1 봉 close, 사후 confirm = i+1 이후
        entry_close = c[i + 1]
        end_confirm = min(i + 2 + confirm_window, len(df))
        future_close_max = c[i + 2 : end_confirm].max() if end_confirm > i + 2 else np.nan
        confirmed = future_close_max > h[i] if not np.isnan(future_close_max) else False
        rows.append({
            "bar_idx": i,
            "timestamp": df["timestamp"].iat[i],
            "spring_close": c[i],
            "spring_high": h[i],
            "spring_low": l[i],
            "entry_close": entry_close,
            "sma20": sma[i],
            "atr14": atr[i],
            "wick_ratio": wick_ratio[i],
            "body_ratio": body_ratio[i],
            "vol_x_ma": v[i] / vol_ma[i] if vol_ma[i] > 0 else np.nan,
            "pierce_atr": (sma[i] - l[i]) / atr[i] if atr[i] > 0 else np.nan,
            "ft_gain_%": (entry_close / c[i] - 1.0) * 100.0,
            "confirmed": bool(confirmed),
        })

    out = pd.DataFrame(rows)

    # forward returns from entry_close (i+1 close)
    for k in FORWARD_HORIZONS:
        fwd = np.full(len(out), np.nan)
        for j, i in enumerate(out["bar_idx"].to_numpy()):
            if i + 1 + k < len(df):
                fwd[j] = (c[i + 1 + k] / c[i + 1] - 1.0) * 100.0
        out[f"ret_{k*4}h"] = fwd
    return out


def list_symbols() -> list[str]:
    files = sorted(CACHE_DIR.glob("bitget_*_1h.parquet"))
    return [f.stem.replace("bitget_", "").replace("_1h", "") for f in files]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default=None, help="trend/follower/whale/junk 필터 (기본: 전체)")
    ap.add_argument("--min-events", type=int, default=3, help="심볼별 최소 spring 수")
    ap.add_argument("--alpha", type=float, default=1.0, help="ATR 침범 배수")
    ap.add_argument("--vol-mult", type=float, default=2.5, help="거래량 스파이크 배수")
    ap.add_argument("--wick-ratio", type=float, default=0.6, help="하단꼬리/range 최소")
    ap.add_argument("--body-ratio", type=float, default=0.2, help="body/range 최소 (도지 제외)")
    ap.add_argument("--ft-atr", type=float, default=0.5, help="follow-through 강도 (×ATR)")
    ap.add_argument("--confirmed-only", action="store_true", help="confirmed spring만 집계")
    ap.add_argument("--no-weekly-filter", action="store_true", help="주봉 SMA10 위 필터 비활성화")
    ap.add_argument("--out", default=str(ROOT / "data" / "spring_events.parquet"))
    ap.add_argument("--summary-out", default=str(ROOT / "data" / "spring_summary_per_symbol.csv"))
    args = ap.parse_args()

    cls = None
    if CLASSIFICATION_PATH.exists():
        cls = pd.read_parquet(CLASSIFICATION_PATH)[["symbol", "tier_final"]]

    symbols = list_symbols()
    if args.tier and cls is not None:
        keep = set(cls.loc[cls["tier_final"] == args.tier, "symbol"])
        symbols = [s for s in symbols if s in keep]

    print(f"[scan] symbols={len(symbols)} tier={args.tier or 'ALL'} "
          f"alpha={args.alpha} wick>{args.wick_ratio} body>{args.body_ratio} "
          f"vol×{args.vol_mult} ft={args.ft_atr}·ATR "
          f"weekly_filter={'OFF' if args.no_weekly_filter else 'ON'}")

    all_events = []
    failed = 0
    for i, sym in enumerate(symbols, 1):
        try:
            df_4h = load(sym, "4h")
            wsma = None if args.no_weekly_filter else _weekly_sma10_on_4h(sym, df_4h)
            ev = detect_springs(
                df_4h,
                alpha=args.alpha,
                vol_mult=args.vol_mult,
                wick_ratio_min=args.wick_ratio,
                body_ratio_min=args.body_ratio,
                followthrough_atr=args.ft_atr,
                weekly_sma10=wsma,
            )
            if not ev.empty:
                ev.insert(0, "symbol", sym)
                all_events.append(ev)
        except Exception as e:
            failed += 1
            if failed <= 3:
                print(f"  ! {sym}: {e}")
        if i % 50 == 0:
            print(f"  ... {i}/{len(symbols)}")

    if not all_events:
        print("no events found.")
        return

    events = pd.concat(all_events, ignore_index=True)
    if cls is not None:
        events = events.merge(cls, on="symbol", how="left")

    if args.confirmed_only:
        events = events[events["confirmed"]].copy()

    events.to_parquet(args.out, index=False)
    print(f"\n[saved] events → {args.out}  (rows={len(events)})")

    ret_cols = [f"ret_{h*4}h" for h in FORWARD_HORIZONS]

    print("\n=== OVERALL (all symbols, all events) ===")
    print(f"total events: {len(events)}  symbols with events: {events['symbol'].nunique()}")
    print(f"confirmed rate: {events['confirmed'].mean()*100:.1f}%")
    overall = []
    for col in ret_cols:
        s = events[col].dropna()
        if s.empty:
            continue
        overall.append({
            "horizon": col,
            "n": len(s),
            "win_rate_%": (s > 0).mean() * 100,
            "mean_%": s.mean(),
            "median_%": s.median(),
            "p25_%": s.quantile(0.25),
            "p75_%": s.quantile(0.75),
            "max_%": s.max(),
            "min_%": s.min(),
        })
    print(pd.DataFrame(overall).to_string(index=False, float_format=lambda x: f"{x:8.2f}"))

    if "tier_final" in events.columns:
        print("\n=== BY TIER ===")
        for tier, grp in events.groupby("tier_final"):
            print(f"\n-- tier={tier}  events={len(grp)}  symbols={grp['symbol'].nunique()}  "
                  f"confirmed={grp['confirmed'].mean()*100:.1f}%")
            rows = []
            for col in ret_cols:
                s = grp[col].dropna()
                if s.empty:
                    continue
                rows.append({
                    "horizon": col,
                    "n": len(s),
                    "win_%": (s > 0).mean() * 100,
                    "mean_%": s.mean(),
                    "median_%": s.median(),
                })
            print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:7.2f}"))

    print("\n=== TOP 20 SYMBOLS by ret_96h median (min events filter) ===")
    per_sym = (
        events.groupby("symbol")
        .agg(
            n_events=("symbol", "size"),
            confirmed_rate=("confirmed", "mean"),
            win_24h=("ret_24h", lambda s: (s > 0).mean() * 100),
            mean_24h=("ret_24h", "mean"),
            med_24h=("ret_24h", "median"),
            win_96h=("ret_96h", lambda s: (s > 0).mean() * 100),
            mean_96h=("ret_96h", "mean"),
            med_96h=("ret_96h", "median"),
        )
        .reset_index()
    )
    per_sym = per_sym[per_sym["n_events"] >= args.min_events].copy()
    per_sym["confirmed_rate"] = per_sym["confirmed_rate"] * 100
    per_sym = per_sym.sort_values("med_96h", ascending=False)
    per_sym.to_csv(args.summary_out, index=False)
    print(f"[saved] per-symbol summary → {args.summary_out}")
    print(per_sym.head(20).to_string(index=False, float_format=lambda x: f"{x:7.2f}"))


if __name__ == "__main__":
    main()
