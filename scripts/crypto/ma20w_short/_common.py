"""ma20w_short — 공통 헬퍼.

- weekly OHLCV 로드 (W-MON 리샘플)
- MA20w / slope_4w 컬럼 부착
- 진입/청산 이벤트 추출 (룩어헤드 금지: t 종가 시그널 → t+1 시가 체결)
- 트레이드 단위 short return 계산
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from data.resample import load as load_crypto


def load_weekly(symbol: str) -> pd.DataFrame:
    """1d 캐시 → 1w 리샘플. 컬럼: timestamp, open, high, low, close, volume, amount.
    인덱스는 reset, dt 컬럼(naive UTC) 부착.
    """
    df = load_crypto(symbol, "1w")
    if df.empty:
        return df
    df = df.copy()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def add_ma_slope(df: pd.DataFrame, ma_window: int = 20, slope_window: int = 4) -> pd.DataFrame:
    """ma20w + slope_4w 컬럼 부착.

    slope_4w(t) = MA20[t] / MA20[t-slope_window] - 1
    (정규화 차분, 단위: 비율)
    """
    out = df.copy()
    out["ma"] = out["close"].rolling(ma_window, min_periods=ma_window).mean()
    out["ma_prev"] = out["ma"].shift(slope_window)
    out["slope"] = out["ma"] / out["ma_prev"] - 1.0
    return out


def extract_trades(
    df: pd.DataFrame,
    fees_bps_roundtrip: float = 15.0,
    funding_bps_per_week: Optional[float] = None,
) -> pd.DataFrame:
    """slope<0 진입, slope>=0 청산. 룩어헤드 금지(시그널 t → 체결 t+1 open).

    한 심볼에 대해 트레이드 리스트를 반환. 컬럼:
        entry_idx, exit_idx, entry_dt, exit_dt,
        entry_open, exit_open, hold_weeks,
        gross_ret, fees_ret, funding_ret, net_ret
    """
    cols = ["entry_idx", "exit_idx", "entry_dt", "exit_dt",
            "entry_open", "exit_open", "hold_weeks",
            "gross_ret", "fees_ret", "funding_ret", "net_ret"]
    if df.empty or df["slope"].isna().all():
        return pd.DataFrame(columns=cols)

    slope = df["slope"].values
    opens = df["open"].values
    dts = df["dt"].values
    n = len(df)

    in_short = False
    entry_i = -1
    trades = []
    fee = fees_bps_roundtrip / 10_000.0  # 0.0015
    funding = (funding_bps_per_week or 0.0) / 10_000.0

    # t = 0..n-2 까지 시그널 평가, 체결은 t+1
    for t in range(n - 1):
        s_t = slope[t]
        if np.isnan(s_t):
            continue
        if not in_short:
            if s_t < 0:
                entry_i = t + 1
                in_short = True
        else:
            if s_t >= 0:
                exit_i = t + 1
                eo = opens[entry_i]
                xo = opens[exit_i]
                if eo <= 0 or xo <= 0:
                    in_short = False
                    continue
                gross = (eo - xo) / eo  # short: 가격 하락 시 양수
                hold = exit_i - entry_i
                fnd = funding * hold  # 숏 보유 비용
                net = gross - fee - fnd
                trades.append((entry_i, exit_i, dts[entry_i], dts[exit_i],
                               eo, xo, hold, gross, -fee, -fnd, net))
                in_short = False
                entry_i = -1

    # 미청산 트레이드: 마지막 close 로 mark-to-market (오픈 포지션 표시용)
    if in_short and entry_i >= 0 and entry_i < n:
        eo = opens[entry_i]
        last_close = df["close"].iloc[-1]
        gross = (eo - last_close) / eo
        hold = (n - 1) - entry_i
        fnd = funding * hold
        net = gross - fee - fnd
        trades.append((entry_i, n - 1, dts[entry_i], dts[-1],
                       eo, last_close, hold, gross, -fee, -fnd, net))

    return pd.DataFrame(trades, columns=cols)


def load_classification(path: Path) -> pd.DataFrame:
    """심볼 → tier_final 매핑."""
    df = pd.read_parquet(path)
    return df[["symbol", "tier_final"]].copy()


def summarize_trades(trades: pd.DataFrame) -> dict:
    """트레이드 리스트 → PLAN ①~⑤ 메트릭."""
    if trades.empty:
        return {
            "n_trades": 0, "n_symbols": 0,
            "mean": None, "median": None, "std": None,
            "win_rate": None, "payoff": None,
            "var95": None, "var99": None, "max_loss": None, "max_gain": None,
            "var_adj_expectancy": None,
            "avg_hold_weeks": None, "total_pnl": None,
        }
    r = trades["net_ret"]
    wins = r[r > 0]
    losses = r[r < 0]
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0  # negative
    payoff = (avg_win / abs(avg_loss)) if avg_loss < 0 else None
    mean = float(r.mean())
    std = float(r.std()) if len(r) > 1 else None
    return {
        "n_trades": int(len(r)),
        "n_symbols": int(trades.get("symbol", pd.Series(dtype=str)).nunique()) if "symbol" in trades.columns else None,
        "mean": mean,
        "median": float(r.median()),
        "std": std,
        "win_rate": float((r > 0).mean()),
        "payoff": float(payoff) if payoff is not None else None,
        "var95": float(r.quantile(0.05)),
        "var99": float(r.quantile(0.01)),
        "max_loss": float(r.min()),
        "max_gain": float(r.max()),
        "var_adj_expectancy": (mean - 1.65 * std) if std is not None else None,
        "avg_hold_weeks": float(trades["hold_weeks"].mean()),
        "total_pnl": float(r.sum()),
    }
