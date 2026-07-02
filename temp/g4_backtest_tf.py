"""G4 백테스트 — TF/MA 조합 비교 (일봉 MA60/120, 주봉 MA20/60, 월봉 MA10).

진입/청산 룰 동일. MA 계산 기준선만 다름.
- MA 는 각 TF resample 후 rolling mean → 일봉 index 에 forward-fill 매핑
- Slope 도 각 TF 봉 단위 diff 후 forward-fill
- 진입/청산 판정은 항상 일봉 봉 단위 (실전 대시보드 감각과 일치)
- 임계: rolling 3년 (일봉 756봉) 하위 5% percentile
- 청산: strict (일봉 close ≥ MA 재돌파)
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

PCT_WIN = 756
PCT = 0.05

KR_TOP_N = 200
US_TOP_N = 100

# TF 정의: (label, resample rule, MA window, slope window)
TF_CONFIGS = [
    ("D60",  None, 60, 20),      # 일봉 그대로
    ("D120", None, 120, 20),
    ("W20",  "W",  20, 4),       # 주봉 4봉 ≈ 20일
    ("W60",  "W",  60, 8),
    ("M10",  "M",  10, 3),
]


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


def load_daily(asset, sym):
    p = (KR_DIR if asset == "KR" else US_DIR) / f"{sym}.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df.columns = [c.lower() for c in df.columns]
    df = df[["close"]].sort_index()
    # DatetimeIndex 보장
    df.index = pd.to_datetime(df.index)
    return df


def build_ma_series(daily: pd.DataFrame, rule, ma_win, slope_win):
    """일봉 index 에 매핑된 (MA, slope) Series 반환."""
    close = daily["close"].astype(float)
    if rule is None:
        ma = close.rolling(ma_win).mean()
        slope = ma.diff(slope_win)
        return ma, slope
    # resample
    r_close = close.resample(rule).last()
    r_ma = r_close.rolling(ma_win).mean()
    r_slope = r_ma.diff(slope_win)
    # forward fill to daily index
    ma = r_ma.reindex(daily.index, method="ffill")
    slope = r_slope.reindex(daily.index, method="ffill")
    return ma, slope


def backtest(daily: pd.DataFrame, rule, ma_win, slope_win) -> pd.DataFrame:
    if len(daily) < PCT_WIN + 60:
        return pd.DataFrame()
    close = daily["close"].astype(float)
    ma, slope = build_ma_series(daily, rule, ma_win, slope_win)
    dev = (close - ma) / ma
    pct_thresh = dev.rolling(PCT_WIN, min_periods=252).quantile(PCT)

    close_arr = close.to_numpy()
    ma_arr = ma.to_numpy()
    slope_arr = slope.to_numpy()
    dev_arr = dev.to_numpy()
    pct_arr = pct_thresh.to_numpy()
    idx = daily.index
    n = len(daily)

    trades = []
    in_cycle = False
    entry_i = None
    max_dd_dev = None

    for i in range(n):
        if np.isnan(ma_arr[i]) or np.isnan(pct_arr[i]) or np.isnan(slope_arr[i]):
            continue
        below = close_arr[i] < ma_arr[i]

        if below and not in_cycle:
            in_cycle = True
        elif (not below) and in_cycle:
            if entry_i is not None:
                trades.append({
                    "entry_date": idx[entry_i],
                    "exit_date": idx[i],
                    "hold_days": i - entry_i,
                    "entry_dev": dev_arr[entry_i],
                    "max_dd_dev": max_dd_dev,
                    "return": close_arr[i] / close_arr[entry_i] - 1,
                    "exit_reason": "ma_recover",
                })
                entry_i = None
                max_dd_dev = None
            in_cycle = False
            continue

        if in_cycle and entry_i is None:
            if slope_arr[i] < 0 and dev_arr[i] <= pct_arr[i]:
                entry_i = i
                max_dd_dev = dev_arr[i]

        if entry_i is not None:
            if dev_arr[i] < max_dd_dev:
                max_dd_dev = dev_arr[i]

    if entry_i is not None:
        trades.append({
            "entry_date": idx[entry_i],
            "exit_date": idx[-1],
            "hold_days": (n - 1) - entry_i,
            "entry_dev": dev_arr[entry_i],
            "max_dd_dev": max_dd_dev,
            "return": close_arr[-1] / close_arr[entry_i] - 1,
            "exit_reason": "open_eod",
        })
    return pd.DataFrame(trades)


def summarize(trades: pd.DataFrame, tf_label: str, asset: str, n_pool: int) -> dict:
    if trades.empty:
        return {"자산": asset, "TF": tf_label, "종목": n_pool, "트레이드": 0}
    open_mask = trades["exit_reason"] == "open_eod"
    return {
        "자산": asset,
        "TF": tf_label,
        "종목": n_pool,
        "트레이드": len(trades),
        "종목당": f"{len(trades)/max(n_pool,1):.1f}",
        "오픈%": f"{open_mask.mean()*100:.1f}%",
        "승률": f"{(trades['return'] > 0).mean()*100:.0f}%",
        "평균수익": f"{trades['return'].mean()*100:+.2f}%",
        "중앙수익": f"{trades['return'].median()*100:+.2f}%",
        "평균보유일": f"{trades['hold_days'].mean():.0f}",
        "중앙보유일": f"{trades['hold_days'].median():.0f}",
        "진입이격": f"{trades['entry_dev'].mean()*100:.1f}%",
        "MDD이격": f"{trades['max_dd_dev'].mean()*100:.1f}%",
    }


def main():
    kr_codes, us_codes = pick_universe()
    print(f"유니버스: KR {len(kr_codes)}, US {len(us_codes)}")

    rows = []
    for asset, codes in [("KR", kr_codes), ("US", us_codes)]:
        for tf_label, rule, ma_win, slope_win in TF_CONFIGS:
            pool_count = 0
            all_trades = []
            for sym in codes:
                df = load_daily(asset, sym)
                if df.empty:
                    continue
                t = backtest(df, rule, ma_win, slope_win)
                if t.empty:
                    continue
                pool_count += 1
                all_trades.append(t)
            merged = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
            rows.append(summarize(merged, tf_label, asset, pool_count))
            print(f"  [{asset} {tf_label}] 종목={pool_count}, 트레이드={len(merged)}")

    tbl = pd.DataFrame(rows)
    print("\n=== TF/MA 비교 요약 ===")
    with pd.option_context("display.max_columns", None, "display.width", 250):
        print(tbl.to_string(index=False))


if __name__ == "__main__":
    main()
