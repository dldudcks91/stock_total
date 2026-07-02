"""G4 손절선 백테스트.

베이스 룰 (앞에서 확정):
  - D60 (일봉 MA60), slope<0, close<MA60, dev ≤ 하위 5% percentile
  - 사이클당 1회, 극단 봉 거래량 ≥ 20일평균 × 1.5
  - 진입: 극단 후 첫 양봉 종가 (타이밍 C)
  - 청산: close ≥ MA60 재돌파 종가 (strict)

이번에 추가:
  - 진입가 대비 손실 X% 초과 시 그날 종가로 손절 청산
  - 손절선 후보: 없음 / −3% / −5% / −7% / −10% / −15%

측정:
  - 승률·평균수익 (손절 손실 포함)
  - 손절 비율·MA회복 비율·오픈 비율
  - 손절된 트레이드의 평균 손실
  - MA회복으로 살아남은 트레이드의 평균 수익
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
CONFIRM_MAX_WAIT = 20
MIN_BARS = PCT_WIN + MA_WIN
KR_TOP_N = 200
US_TOP_N = 100

STOPS = [None, -0.03, -0.05, -0.07, -0.10, -0.15]


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


def run(df: pd.DataFrame, stop_pct) -> pd.DataFrame:
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
    extreme_i = None
    entry_i = None
    entry_price = None
    max_dd_dev = None
    min_ret = None  # 진입가 대비 최저 수익률 (음수)

    def confirm_entry(ext_i):
        """극단 이후 첫 양봉 close (최대 CONFIRM_MAX_WAIT 봉 대기)."""
        for j in range(ext_i + 1, min(ext_i + 1 + CONFIRM_MAX_WAIT, n)):
            if c[j] > o[j]:
                return j, c[j]
        return None

    for i in range(n):
        if np.isnan(ma_a[i]) or np.isnan(pct_a[i]) or np.isnan(slope_a[i]):
            continue
        below = c[i] < ma_a[i]

        if below and not in_cycle:
            in_cycle = True
        elif (not below) and in_cycle:
            if entry_i is not None:
                trades.append({
                    "entry_date": idx[entry_i],
                    "exit_date": idx[i],
                    "hold_days": i - entry_i,
                    "entry_dev": dev_a[extreme_i],
                    "max_dd_dev": max_dd_dev,
                    "min_ret": min_ret,
                    "return": c[i] / entry_price - 1,
                    "exit_reason": "ma_recover",
                })
                extreme_i = entry_i = None
                entry_price = None
                max_dd_dev = None
                min_ret = None
            in_cycle = False
            continue

        if in_cycle and extreme_i is None:
            if slope_a[i] < 0 and dev_a[i] <= pct_a[i]:
                # 거래량 필터
                if not (v[i] > 0 and vol_ma[i] > 0 and v[i] >= vol_ma[i] * VOL_MULT):
                    continue
                extreme_i = i
                res = confirm_entry(i)
                if res is None:
                    entry_i = None
                    entry_price = None
                    max_dd_dev = None
                    min_ret = None
                else:
                    entry_i, entry_price = res
                    max_dd_dev = dev_a[entry_i]
                    min_ret = 0.0

        # 오픈 관리 + 손절 판정
        if entry_i is not None and i > entry_i:  # 진입 다음 봉부터 손절 판정
            cur_ret = c[i] / entry_price - 1
            if cur_ret < min_ret:
                min_ret = cur_ret
            if dev_a[i] < max_dd_dev:
                max_dd_dev = dev_a[i]
            if stop_pct is not None and cur_ret <= stop_pct:
                trades.append({
                    "entry_date": idx[entry_i],
                    "exit_date": idx[i],
                    "hold_days": i - entry_i,
                    "entry_dev": dev_a[extreme_i],
                    "max_dd_dev": max_dd_dev,
                    "min_ret": min_ret,
                    "return": cur_ret,
                    "exit_reason": "stop",
                })
                extreme_i = entry_i = None
                entry_price = None
                max_dd_dev = None
                min_ret = None
                # 손절 후에도 사이클은 유효 → 다음 극단 나올 때까지 대기 (사이클 안에서 한 번 더 진입은 X, 첫 만남만)
                # 정통 정의 유지 위해 extreme_i 를 유지시켜야 하나?
                # 여기선 심플하게 "손절 후엔 사이클 종료까지 재진입 없음" (첫 만남 원칙)

    if entry_i is not None:
        trades.append({
            "entry_date": idx[entry_i],
            "exit_date": idx[-1],
            "hold_days": (n - 1) - entry_i,
            "entry_dev": dev_a[extreme_i],
            "max_dd_dev": max_dd_dev,
            "min_ret": min_ret,
            "return": c[-1] / entry_price - 1,
            "exit_reason": "open_eod",
        })
    return pd.DataFrame(trades)


def summarize(trades, stop_pct, asset, n_pool):
    if trades.empty:
        return {"자산": asset, "손절": stop_label(stop_pct), "종목": n_pool, "트레이드": 0}
    reasons = trades["exit_reason"]
    win_rate = (trades["return"] > 0).mean()
    stop_share = (reasons == "stop").mean()
    ma_share = (reasons == "ma_recover").mean()
    open_share = (reasons == "open_eod").mean()

    row = {
        "자산": asset,
        "손절": stop_label(stop_pct),
        "종목": n_pool,
        "트레이드": len(trades),
        "승률": f"{win_rate*100:.0f}%",
        "평균수익": f"{trades['return'].mean()*100:+.2f}%",
        "중앙수익": f"{trades['return'].median()*100:+.2f}%",
        "평균보유일": f"{trades['hold_days'].mean():.0f}",
        "손절%": f"{stop_share*100:.0f}%",
        "MA회복%": f"{ma_share*100:.0f}%",
        "오픈%": f"{open_share*100:.0f}%",
    }
    # 손절된 것만 평균, MA회복된 것만 평균
    stopped = trades[reasons == "stop"]
    recov = trades[reasons == "ma_recover"]
    row["손절평균손실"] = f"{stopped['return'].mean()*100:+.2f}%" if not stopped.empty else "-"
    row["MA회복평균수익"] = f"{recov['return'].mean()*100:+.2f}%" if not recov.empty else "-"
    return row


def stop_label(stop_pct):
    if stop_pct is None:
        return "없음"
    return f"{int(stop_pct*100)}%"


def dd_distribution(trades, asset):
    """진입 후 최저 수익률 분포 (손절 없음 baseline)."""
    if trades.empty:
        return
    r = trades["min_ret"].dropna()
    if r.empty:
        return
    print(f"\n  === {asset} 진입 후 최저 수익률 분포 (손절 없음 baseline) ===")
    for p in [5, 10, 25, 50, 75, 90]:
        v = r.quantile(p/100) * 100
        print(f"    {p:>2}%ile: {v:+.1f}%")
    # 손절선별 걸리는 비율 (사전 시뮬)
    print(f"    (참고) 진입 후 낙폭이 손절선 아래로 내려간 비율")
    for s in [-0.03, -0.05, -0.07, -0.10, -0.15]:
        share = (r <= s).mean() * 100
        print(f"    dev min ≤ {int(s*100)}%: {share:.0f}%")


def main():
    kr_codes, us_codes = pick_universe()
    print(f"유니버스: KR {len(kr_codes)}, US {len(us_codes)}")

    rows = []
    for asset, codes in [("KR", kr_codes), ("US", us_codes)]:
        baseline_trades = None
        for stop_pct in STOPS:
            pool_count = 0
            all_trades = []
            for sym in codes:
                df = load_ohlcv(asset, sym)
                if df.empty:
                    continue
                t = run(df, stop_pct)
                if t.empty:
                    continue
                pool_count += 1
                all_trades.append(t)
            merged = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
            rows.append(summarize(merged, stop_pct, asset, pool_count))
            print(f"  [{asset} 손절={stop_label(stop_pct)}] 종목={pool_count}, 트레이드={len(merged)}")
            if stop_pct is None:
                baseline_trades = merged
        if baseline_trades is not None:
            dd_distribution(baseline_trades, asset)

    tbl = pd.DataFrame(rows)
    print("\n=== 손절선별 성능 비교 ===")
    with pd.option_context("display.max_columns", None, "display.width", 250):
        print(tbl.to_string(index=False))


if __name__ == "__main__":
    main()
