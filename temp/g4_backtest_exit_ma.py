"""G4 손익 백테스트 — 진입: 첫 만남(사이클당 1회) 극단 이격 자리 / 청산: MA60 근처.

앞선 forward N일 고정 대신 실제 트레이딩 시나리오 (MA60 회복 청산) 로 손익 측정.

진입:
  - 하락 사이클 = close < MA60 상태
  - 사이클 안에서 처음으로 (slope<0 AND dev ≤ 하위 5% percentile) 만족 → 그 봉 종가 매수
  - 사이클당 1회 (첫 만남만)

청산 (두 룰 병렬):
  - strict: close ≥ MA60 재돌파한 첫 봉 종가
  - soft: close ≥ MA60 × 0.98 (MA60 −2% 이내 근접) 첫 봉 종가
  청산 조건 만족 안 한 채 데이터 끝 → 오픈 포지션 (마지막 종가로 mark-to-market)

측정:
  - 평균/중앙 수익률, 승률
  - 평균 보유일수 (진입~청산)
  - 오픈 포지션 비율
  - MDD (진입 후 dev 최저치 = 얼마나 더 벌어졌는지)
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
SOFT_MULT = 0.98            # MA60 × 0.98 = "MA60 −2% 이내" (soft exit)
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


def load_daily(asset, sym):
    p = (KR_DIR if asset == "KR" else US_DIR) / f"{sym}.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df.columns = [c.lower() for c in df.columns]
    return df[["close"]].sort_index()


def backtest_trades(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) < MIN_BARS:
        return pd.DataFrame()
    close = df["close"].astype(float)
    ma = close.rolling(MA_WIN).mean()
    slope = ma.diff(SLOPE_WIN)
    dev = (close - ma) / ma
    pct_thresh = dev.rolling(PCT_WIN, min_periods=252).quantile(PCT)

    close_arr = close.to_numpy()
    ma_arr = ma.to_numpy()
    slope_arr = slope.to_numpy()
    dev_arr = dev.to_numpy()
    pct_arr = pct_thresh.to_numpy()
    idx = df.index

    n = len(df)
    trades = []
    in_cycle = False
    entry_i = None
    max_dd_dev = None  # 진입 후 dev 최저치 (더 벌어진 정도)

    def finalize_trade(exit_i, exit_reason):
        exit_close = close_arr[exit_i]
        ret = exit_close / close_arr[entry_i] - 1
        trades.append({
            "entry_date": idx[entry_i],
            "exit_date": idx[exit_i],
            "hold_days": exit_i - entry_i,
            "entry_dev": dev_arr[entry_i],
            "max_dd_dev": max_dd_dev,
            "return": ret,
            "exit_reason": exit_reason,
        })

    for i in range(n):
        if np.isnan(ma_arr[i]) or np.isnan(pct_arr[i]):
            continue
        below = close_arr[i] < ma_arr[i]

        # 사이클 상태 전이
        if below and not in_cycle:
            in_cycle = True
        elif (not below) and in_cycle:
            # 사이클 종료 시 오픈 포지션 있으면 자동 청산
            if entry_i is not None:
                finalize_trade(i, "cycle_end_ma_recover")
                entry_i = None
                max_dd_dev = None
            in_cycle = False

        # 사이클 안에서 첫 극단 → 진입
        if in_cycle and entry_i is None:
            if slope_arr[i] < 0 and dev_arr[i] <= pct_arr[i]:
                entry_i = i
                max_dd_dev = dev_arr[i]

        # 오픈 포지션 관리
        if entry_i is not None:
            if dev_arr[i] < max_dd_dev:
                max_dd_dev = dev_arr[i]

    # 데이터 끝. 오픈 포지션은 마지막 종가로 mark-to-market
    if entry_i is not None:
        exit_close = close_arr[-1]
        ret = exit_close / close_arr[entry_i] - 1
        trades.append({
            "entry_date": idx[entry_i],
            "exit_date": idx[-1],
            "hold_days": (n - 1) - entry_i,
            "entry_dev": dev_arr[entry_i],
            "max_dd_dev": max_dd_dev,
            "return": ret,
            "exit_reason": "open_eod",
        })

    return pd.DataFrame(trades)


def backtest_trades_with_soft_exit(df: pd.DataFrame) -> pd.DataFrame:
    """soft exit 룰: close ≥ MA60 × 0.98 첫 봉 청산."""
    if len(df) < MIN_BARS:
        return pd.DataFrame()
    close = df["close"].astype(float)
    ma = close.rolling(MA_WIN).mean()
    slope = ma.diff(SLOPE_WIN)
    dev = (close - ma) / ma
    pct_thresh = dev.rolling(PCT_WIN, min_periods=252).quantile(PCT)

    close_arr = close.to_numpy()
    ma_arr = ma.to_numpy()
    slope_arr = slope.to_numpy()
    dev_arr = dev.to_numpy()
    pct_arr = pct_thresh.to_numpy()
    idx = df.index
    n = len(df)

    # 사이클 시작 시점, 진입 시점, soft-exit 시점 계산
    trades = []
    in_cycle = False
    entry_i = None
    max_dd_dev = None

    def close_trade(exit_i, reason):
        ret = close_arr[exit_i] / close_arr[entry_i] - 1
        trades.append({
            "entry_date": idx[entry_i],
            "exit_date": idx[exit_i],
            "hold_days": exit_i - entry_i,
            "entry_dev": dev_arr[entry_i],
            "max_dd_dev": max_dd_dev,
            "return": ret,
            "exit_reason": reason,
        })

    for i in range(n):
        if np.isnan(ma_arr[i]) or np.isnan(pct_arr[i]):
            continue
        below = close_arr[i] < ma_arr[i]

        if below and not in_cycle:
            in_cycle = True
        elif (not below) and in_cycle:
            if entry_i is not None:
                close_trade(i, "ma_full_recover")
                entry_i = None
                max_dd_dev = None
            in_cycle = False
            continue

        if in_cycle and entry_i is None:
            if slope_arr[i] < 0 and dev_arr[i] <= pct_arr[i]:
                entry_i = i
                max_dd_dev = dev_arr[i]
                continue  # 진입 봉 자체에선 청산 판정 X

        if entry_i is not None:
            if dev_arr[i] < max_dd_dev:
                max_dd_dev = dev_arr[i]
            # soft exit: close ≥ MA × 0.98
            if close_arr[i] >= ma_arr[i] * SOFT_MULT:
                close_trade(i, "ma_soft_recover")
                entry_i = None
                max_dd_dev = None

    if entry_i is not None:
        ret = close_arr[-1] / close_arr[entry_i] - 1
        trades.append({
            "entry_date": idx[entry_i],
            "exit_date": idx[-1],
            "hold_days": (n - 1) - entry_i,
            "entry_dev": dev_arr[entry_i],
            "max_dd_dev": max_dd_dev,
            "return": ret,
            "exit_reason": "open_eod",
        })
    return pd.DataFrame(trades)


def summarize(trades: pd.DataFrame, label: str, asset: str) -> dict:
    if trades.empty:
        return {"자산": asset, "청산룰": label, "트레이드수": 0}
    open_mask = trades["exit_reason"] == "open_eod"
    closed = trades[~open_mask]
    row = {
        "자산": asset,
        "청산룰": label,
        "트레이드수": len(trades),
        "오픈수": int(open_mask.sum()),
        "종료수": len(closed),
        "평균수익": f"{trades['return'].mean()*100:+.2f}%",
        "중앙수익": f"{trades['return'].median()*100:+.2f}%",
        "승률": f"{(trades['return'] > 0).mean()*100:.0f}%",
        "평균보유일": f"{trades['hold_days'].mean():.0f}",
        "중앙보유일": f"{trades['hold_days'].median():.0f}",
        "평균진입이격": f"{trades['entry_dev'].mean()*100:.1f}%",
        "평균MDD이격": f"{trades['max_dd_dev'].mean()*100:.1f}%",
    }
    return row


def top_bottom(pool, top_n=5):
    per = []
    for sym, trades in pool:
        r = trades["return"]
        if len(r) < 2:
            continue
        per.append((sym, len(trades), r.mean()*100, (r > 0).mean()*100, trades["hold_days"].mean()))
    if not per:
        return None, None
    df = pd.DataFrame(per, columns=["symbol", "트레이드수", "평균수익%", "승률%", "평균보유일"])
    df = df.sort_values("평균수익%", ascending=False)
    return df.head(top_n), df.tail(top_n).iloc[::-1]


def main():
    kr_codes, us_codes = pick_universe()
    print(f"유니버스: KR {len(kr_codes)}, US {len(us_codes)}")

    summary = []
    for asset, codes in [("KR", kr_codes), ("US", us_codes)]:
        for label, fn in [("strict(MA완전회복)", backtest_trades),
                          ("soft(MA-2%이내근접)", backtest_trades_with_soft_exit)]:
            pool = []
            all_trades = []
            for sym in codes:
                df = load_daily(asset, sym)
                if df.empty:
                    continue
                trades = fn(df)
                if trades.empty:
                    continue
                pool.append((sym, trades))
                all_trades.append(trades)
            merged = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
            print(f"  [{asset} {label}] 종목={len(pool)}, 트레이드={len(merged)}")
            summary.append(summarize(merged, label, asset))

            if label.startswith("soft"):
                top, bot = top_bottom(pool)
                if top is not None:
                    print(f"\n  === {asset} soft 청산 종목별 TOP5 ===")
                    print(top.to_string(index=False))
                    print(f"  === {asset} soft 청산 종목별 BOTTOM5 ===")
                    print(bot.to_string(index=False))

    print("\n=== 자산 × 청산룰 요약 ===")
    tbl = pd.DataFrame(summary)
    with pd.option_context("display.max_columns", None, "display.width", 250):
        print(tbl.to_string(index=False))


if __name__ == "__main__":
    main()
