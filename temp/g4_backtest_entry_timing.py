"""G4 진입 타이밍 + 거래량 필터 비교 (D60 baseline).

논점:
  1. 거래량 필터 — 극단 봉 거래량 > 20일 평균 × 1.5 (매도 클라이맥스)
  2. 진입 타이밍 4안:
     A. 극단 봉 종가
     B. 극단 다음 봉 open
     C. 극단 후 첫 양봉 (close > open) 종가
     D. 극단 후 장대양봉 (close/open ≥ 1.03) 종가

공통:
  - MA60 slope<0, close<MA60, dev ≤ 하위 5% percentile
  - 사이클당 1회 (첫 만남)
  - 청산: close ≥ MA60 재돌파 종가 (strict)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
KR_DIR = ROOT / "data" / "cache" / "kr"
US_DIR = ROOT / "data" / "cache" / "us"

MA_WIN = 60
SLOPE_WIN = 20
PCT_WIN = 756
PCT = 0.05
VOL_WIN = 20
VOL_MULT = 1.5
LONG_BODY_MULT = 1.03   # 장대양봉: close ≥ open × 1.03
CONFIRM_MAX_WAIT = 20   # 반등 확인 최대 대기 봉수 (넘어가면 취소)
MIN_BARS = PCT_WIN + MA_WIN
KR_TOP_N = 200
US_TOP_N = 100


def pick_universe():
    kr = pd.read_parquet(ROOT / "data/cache/kr/_live_snapshot.parquet")
    kr["mv"] = pd.to_numeric(kr["marketValue"], errors="coerce")
    kr = kr.dropna(subset=["mv"]).sort_values("mv", ascending=False)
    kr_codes = kr["itemCode"].astype(str).str.zfill(6).head(KR_TOP_N).tolist()

    us = pd.read_parquet(ROOT / "data/cache/us/_live_snapshot.parquet")
    us["mv"] = pd.to_numeric(us["marketValueRaw"], errors="coerce")
    us = us.dropna(subset=["mv"]).sort_values("mv", ascending=False)
    def is_common(sym):
        s = str(sym).upper()
        if len(s) >= 5 and s[-1] in ("R", "U", "W") and s[-2] not in "AEIOU":
            return False
        return True
    us = us[us["symbolCode"].apply(is_common)]
    us_codes = us["symbolCode"].astype(str).head(US_TOP_N).tolist()
    return kr_codes, us_codes


def load_ohlcv(asset, sym):
    p = (KR_DIR if asset == "KR" else US_DIR) / f"{sym}.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df.columns = [c.lower() for c in df.columns]
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[cols].sort_index()
    df.index = pd.to_datetime(df.index)
    return df


def run(df: pd.DataFrame, timing: str, use_volume_filter: bool) -> pd.DataFrame:
    """timing ∈ {A, B, C, D}"""
    if len(df) < MIN_BARS:
        return pd.DataFrame()
    o = df["open"].astype(float).to_numpy()
    c = df["close"].astype(float).to_numpy()
    v = df["volume"].astype(float).to_numpy() if "volume" in df.columns else np.zeros(len(df))

    close_s = df["close"].astype(float)
    ma = close_s.rolling(MA_WIN).mean()
    slope = ma.diff(SLOPE_WIN)
    dev = (close_s - ma) / ma
    pct_thresh = dev.rolling(PCT_WIN, min_periods=252).quantile(PCT)
    vol_ma = pd.Series(v, index=df.index).rolling(VOL_WIN).mean().to_numpy()

    ma_a = ma.to_numpy()
    slope_a = slope.to_numpy()
    dev_a = dev.to_numpy()
    pct_a = pct_thresh.to_numpy()
    idx = df.index
    n = len(df)

    trades = []
    in_cycle = False
    extreme_i = None    # 극단 봉 index
    entry_i = None      # 실제 진입 봉 index
    entry_price = None
    max_dd_dev = None

    def try_enter(i):
        """timing 룰에 따라 실제 진입 봉·가격 결정. 진입 못 하면 None 반환."""
        if timing == "A":
            # 극단 봉 종가
            return i, c[i]
        if timing == "B":
            # 다음 봉 open
            if i + 1 >= n:
                return None
            return i + 1, o[i + 1]
        if timing == "C":
            # 극단 다음부터 첫 양봉 close
            for j in range(i + 1, min(i + 1 + CONFIRM_MAX_WAIT, n)):
                if c[j] > o[j]:
                    return j, c[j]
            return None
        if timing == "D":
            # 극단 다음부터 장대양봉 close
            for j in range(i + 1, min(i + 1 + CONFIRM_MAX_WAIT, n)):
                if o[j] > 0 and c[j] / o[j] >= LONG_BODY_MULT:
                    return j, c[j]
            return None
        return None

    for i in range(n):
        if np.isnan(ma_a[i]) or np.isnan(pct_a[i]) or np.isnan(slope_a[i]):
            continue
        below = c[i] < ma_a[i]

        if below and not in_cycle:
            in_cycle = True
        elif (not below) and in_cycle:
            # 사이클 종료 → 열린 포지션 청산
            if entry_i is not None:
                trades.append({
                    "entry_date": idx[entry_i],
                    "exit_date": idx[i],
                    "hold_days": i - entry_i,
                    "entry_dev": dev_a[extreme_i],  # 극단 이격 (진입 봉 아니라 극단 봉 기준)
                    "max_dd_dev": max_dd_dev,
                    "return": c[i] / entry_price - 1,
                    "exit_reason": "ma_recover",
                })
                extreme_i = entry_i = None
                entry_price = None
                max_dd_dev = None
            in_cycle = False
            continue

        # 사이클 안, 아직 극단 안 찾음
        if in_cycle and extreme_i is None:
            if slope_a[i] < 0 and dev_a[i] <= pct_a[i]:
                # 거래량 필터
                if use_volume_filter:
                    if not (v[i] > 0 and vol_ma[i] > 0 and v[i] >= vol_ma[i] * VOL_MULT):
                        continue
                extreme_i = i
                # 진입 시도
                res = try_enter(i)
                if res is None:
                    # 진입 못 함 → 사이클 안이지만 진입 실패로 남김
                    entry_i = None
                    entry_price = None
                    max_dd_dev = None
                else:
                    entry_i, entry_price = res
                    max_dd_dev = dev_a[entry_i]

        # 오픈 관리
        if entry_i is not None and i >= entry_i:
            if dev_a[i] < max_dd_dev:
                max_dd_dev = dev_a[i]

    if entry_i is not None:
        trades.append({
            "entry_date": idx[entry_i],
            "exit_date": idx[-1],
            "hold_days": (n - 1) - entry_i,
            "entry_dev": dev_a[extreme_i],
            "max_dd_dev": max_dd_dev,
            "return": c[-1] / entry_price - 1,
            "exit_reason": "open_eod",
        })
    return pd.DataFrame(trades)


def summarize(trades, timing, use_vol, asset, n_pool):
    if trades.empty:
        return {"자산": asset, "타이밍": timing, "거래량": "ON" if use_vol else "OFF",
                "종목": n_pool, "트레이드": 0}
    open_mask = trades["exit_reason"] == "open_eod"
    return {
        "자산": asset,
        "타이밍": timing,
        "거래량": "ON" if use_vol else "OFF",
        "종목": n_pool,
        "트레이드": len(trades),
        "종목당": f"{len(trades)/max(n_pool,1):.1f}",
        "오픈%": f"{open_mask.mean()*100:.1f}%",
        "승률": f"{(trades['return'] > 0).mean()*100:.0f}%",
        "평균수익": f"{trades['return'].mean()*100:+.2f}%",
        "중앙수익": f"{trades['return'].median()*100:+.2f}%",
        "평균보유일": f"{trades['hold_days'].mean():.0f}",
        "MDD이격": f"{trades['max_dd_dev'].mean()*100:.1f}%",
    }


def main():
    kr_codes, us_codes = pick_universe()
    print(f"유니버스: KR {len(kr_codes)}, US {len(us_codes)}")
    TIMINGS = [
        ("A_극단봉종가", "A"),
        ("B_다음봉open", "B"),
        ("C_첫양봉close", "C"),
        ("D_장대양봉close", "D"),
    ]
    rows = []
    for asset, codes in [("KR", kr_codes), ("US", us_codes)]:
        for use_vol in [False, True]:
            for label, timing in TIMINGS:
                pool_count = 0
                all_trades = []
                for sym in codes:
                    df = load_ohlcv(asset, sym)
                    if df.empty:
                        continue
                    t = run(df, timing, use_vol)
                    if t.empty:
                        continue
                    pool_count += 1
                    all_trades.append(t)
                merged = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
                rows.append(summarize(merged, label, use_vol, asset, pool_count))
                print(f"  [{asset} vol={'ON' if use_vol else 'OFF'} {label}] "
                      f"종목={pool_count}, 트레이드={len(merged)}")

    tbl = pd.DataFrame(rows)
    print("\n=== 진입 타이밍 × 거래량 필터 비교 ===")
    with pd.option_context("display.max_columns", None, "display.width", 250):
        print(tbl.to_string(index=False))


if __name__ == "__main__":
    main()
