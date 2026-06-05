"""Quick short-pattern backtest (대충 버전).

5개 숏 패턴 (S1~S5) 의 단순화된 검출기 + forward return 측정.
- 진입: 신호일 t (룩어헤드 회피 위해 t의 close 종가 시그널, 가격은 t+1 open)
- 청산: t+1 시점 +5d / +10d / +20d 후 close
- 숏 수익률: -(exit/entry - 1)  (가격 하락 = 숏 이익)
- 표본: 1d 캐시 전체 (Bitget USDT-M)
- 기간: 2020-01-01 ~ 현재 (각 심볼 별)
- 수수료/슬리피지/펀딩비는 미반영 (대충 단계)

집계:
- 패턴별: count(전체 신호 수), win_rate (P(short_ret > 0)), mean_short_ret, p25/p50/p75

룩어헤드: 모든 시그널 t의 정보만 사용. 진입가 = t+1 open. 출구 = t+1+N의 close.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from data.loader import load_ohlcv  # noqa: E402

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"
HOLD_DAYS = [5, 10, 20]


# ---------- 지표 ----------

def compute_ind(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["ma20"] = d["close"].rolling(20, min_periods=20).mean()
    d["ma50"] = d["close"].rolling(50, min_periods=50).mean()
    d["ma20_slope_20d"] = d["ma20"] / d["ma20"].shift(20) - 1  # 20일 변화율
    d["std20"] = d["close"].pct_change().rolling(20).std()
    d["std60"] = d["close"].pct_change().rolling(60).std()
    d["high60"] = d["high"].rolling(60).max()
    d["low60"] = d["low"].rolling(60).min()
    d["range60"] = d["high60"] / d["low60"] - 1
    return d


# ---------- 5개 패턴 시그널 (boolean Series) ----------

def sig_S1_bear_flag(d: pd.DataFrame) -> pd.Series:
    """강한 음봉 후 짧은 반등 → 다시 음봉.
    - 5~10일 전에 -8% 이상 하락 음봉
    - 그 후 close < MA20 유지
    - 오늘 음봉 (close < open)
    - 오늘 거래량 ≥ 20일 평균
    """
    big_drop_5_to_10 = (d["close"].shift(5) / d["close"].shift(10) - 1) < -0.08
    below_ma20 = d["close"] < d["ma20"]
    today_red = d["close"] < d["open"]
    vol_avg20 = d["volume"].rolling(20).mean()
    high_vol = d["volume"] >= vol_avg20
    return big_drop_5_to_10 & below_ma20 & today_red & high_vol


def sig_S2_steady_decline(d: pd.DataFrame) -> pd.Series:
    """꾸준한 하락:
    - close < MA20 < MA50
    - MA20 20일 slope < -2%
    - 20일 변동성 ≤ 60일 변동성 (잔잔하게 흘러내림)
    - 큰 음봉 없음: 직전 20일 최대 일간 낙폭 < -5%
    """
    align = (d["close"] < d["ma20"]) & (d["ma20"] < d["ma50"])
    slope_down = d["ma20_slope_20d"] < -0.02
    quiet = d["std20"] <= d["std60"]
    daily_ret = d["close"].pct_change()
    no_big_drop = daily_ret.rolling(20).min() > -0.05
    return align & slope_down & quiet & no_big_drop


def sig_S3_ma_rejection(d: pd.DataFrame) -> pd.Series:
    """MA20 에 N회 이상 닿고 거부:
    - 직전 40일 내 high 가 MA20 ±2% 범위에 진입한 일수 ≥ 3
    - close < MA20 (= 거부 후 하락)
    - MA20 slope < 0 (채널 하락)
    """
    near_ma20 = (d["high"] >= d["ma20"] * 0.98) & (d["close"] < d["ma20"])
    touch_count_40 = near_ma20.rolling(40).sum()
    enough_touches = touch_count_40 >= 3
    slope_down = d["ma20_slope_20d"] < 0
    today_below = d["close"] < d["ma20"]
    return enough_touches & slope_down & today_below


def sig_S4_stage3_to_4(d: pd.DataFrame) -> pd.Series:
    """분배 박스 후 neckline 이탈:
    - 직전 60~120일 range (high/low - 1) ≤ 30% (박스)
    - 그 박스 안에서 횡보 (close 가 60일 high 의 75% 이상에서 머묾)
    - 오늘 close 가 60일 low * 0.98 아래로 break
    - 거래량 ≥ 20일 평균 * 1.5
    """
    box = d["range60"] <= 0.30
    # 박스 내 횡보: 60일 평균 close 가 60일 high 의 75% 이상
    mean_close_60 = d["close"].rolling(60).mean()
    distribution = mean_close_60 >= d["high60"] * 0.75
    breakdown = d["close"] < d["low60"].shift(1) * 0.99  # 어제 60일 low를 1% 이탈
    vol_avg20 = d["volume"].rolling(20).mean()
    high_vol = d["volume"] >= vol_avg20 * 1.5
    return box & distribution & breakdown & high_vol


def sig_S5_upthrust(d: pd.DataFrame) -> pd.Series:
    """Upthrust / Bull Trap:
    - 어제 (t-1) 60일 high 돌파 (high[t-1] > high60[t-2])
    - 오늘 (t) close < 어제 high60 (가짜 돌파 확정)
    - 직전 60일 box (range60 ≤ 35%) 였음
    """
    prev_high60 = d["high60"].shift(2)
    breakout = d["high"].shift(1) > prev_high60
    failed = d["close"] < prev_high60
    was_box = d["range60"].shift(1) <= 0.35
    return breakout & failed & was_box


PATTERNS = {
    "S1_bear_flag": sig_S1_bear_flag,
    "S2_steady_decline": sig_S2_steady_decline,
    "S3_ma_rejection": sig_S3_ma_rejection,
    "S4_stage3to4": sig_S4_stage3_to_4,
    "S5_upthrust": sig_S5_upthrust,
}


# ---------- forward return ----------

def short_returns(d: pd.DataFrame, signal: pd.Series, hold_days: list[int]) -> pd.DataFrame:
    """signal=True 인 t 에서, entry = open[t+1], exit = close[t+1+N].
    숏 수익 = -(exit/entry - 1).
    """
    entry = d["open"].shift(-1)
    rows = []
    for n in hold_days:
        exit_ = d["close"].shift(-(1 + n))
        ret = -(exit_ / entry - 1)
        rows.append(ret.rename(f"short_ret_{n}d"))
    return pd.concat(rows, axis=1).loc[signal.fillna(False)]


# ---------- 메인 ----------

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CACHE_DIR.glob("*.parquet"))
    print(f"심볼 {len(files)}개 처리 시작")

    # pattern → forward return rows 누적
    all_rows = {name: [] for name in PATTERNS}

    for i, f in enumerate(files):
        symbol = f.stem
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if len(df) < 150:
            continue
        # timestamp ms → datetime index (정렬용)
        df = df.sort_values("timestamp").reset_index(drop=True)
        d = compute_ind(df)

        for name, fn in PATTERNS.items():
            sig = fn(d)
            ret_df = short_returns(d, sig, HOLD_DAYS)
            if len(ret_df) == 0:
                continue
            ret_df = ret_df.copy()
            ret_df["symbol"] = symbol
            all_rows[name].append(ret_df)

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(files)} 처리")

    # 집계
    summary_rows = []
    for name, dfs in all_rows.items():
        if not dfs:
            for n in HOLD_DAYS:
                summary_rows.append({"pattern": name, "hold_days": n, "count": 0})
            continue
        merged = pd.concat(dfs, ignore_index=True)
        for n in HOLD_DAYS:
            col = f"short_ret_{n}d"
            s = merged[col].dropna()
            if len(s) == 0:
                continue
            summary_rows.append({
                "pattern": name,
                "hold_days": n,
                "count": int(len(s)),
                "n_symbols": int(merged.loc[~merged[col].isna(), "symbol"].nunique()),
                "win_rate": float((s > 0).mean()),
                "mean_short_ret": float(s.mean()),
                "median_short_ret": float(s.median()),
                "p25": float(s.quantile(0.25)),
                "p75": float(s.quantile(0.75)),
                "std": float(s.std()),
                "max_loss": float(s.min()),  # 가장 큰 손실 (squeeze)
                "max_gain": float(s.max()),
                "expectancy_per_trade": float(s.mean()),
                "sharpe_like": float(s.mean() / s.std()) if s.std() > 0 else np.nan,
            })

    summary = pd.DataFrame(summary_rows)
    print("\n=== 집계 결과 ===")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    out_path = ROOT / "scripts" / "out" / "quick_short_backtest_summary.csv"
    summary.to_csv(out_path, index=False)
    print(f"\nCSV 저장: {out_path}")


if __name__ == "__main__":
    main()
