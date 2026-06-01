"""ma20w_short 공통 헬퍼.

PLAN.md 의 진입/청산 룰을 구현하는 작은 모듈.

핵심:
  - 주봉 MA20 + slope_4w 계산 (룩어헤드 방지: 직전 완성 주봉만)
  - 일봉마다 "그 시점의 직전 완성 주봉" 의 MA20w/slope_4w 를 fix 해 attach
  - 게이트 (close_1w < MA20w AND slope_4w < 0) 통과 + 일봉 high >= MA20w 첫 봉 = 진입
  - 4 그룹 universe (trend / follower / whale / junk)

`screen_crypto` (weekly_trend_gate.py) 와 같은 MA20w 정의를 쓰지만, 게이트는 반대 방향.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from data.resample import load as load_crypto


# ============================================================
# 1. Weekly features (MA20 + slope_4w)
# ============================================================

def compute_weekly_features(
    weekly: pd.DataFrame,
    ma_window: int = 20,
    slope_window: int = 4,
) -> pd.DataFrame:
    """주봉 OHLCV → MA20w / slope_4w / gate_pass 컬럼 추가.

    Args:
        weekly: data.resample.load(sym, '1w') 의 반환 (columns: timestamp/open/high/low/close/volume/amount)
        ma_window: MA 윈도우 (기본 20)
        slope_window: slope 비교 윈도우 (기본 4주)

    Returns:
        weekly + ['dt', 'ma20w', 'slope_4w', 'gate_pass']
        - gate_pass: close < ma20w AND slope_4w < 0
        - 룩어헤드 방지를 위해 호출 측이 마지막 미완성 주봉을 drop 해야 함.
    """
    if weekly.empty:
        return weekly.assign(dt=pd.Series(dtype="datetime64[ns]"),
                             ma20w=np.nan, slope_4w=np.nan, gate_pass=False)

    df = weekly.copy()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms")
    df["ma20w"] = df["close"].rolling(ma_window, min_periods=ma_window).mean()
    df["slope_4w"] = df["ma20w"] / df["ma20w"].shift(slope_window) - 1.0
    df["gate_pass"] = (df["close"] < df["ma20w"]) & (df["slope_4w"] < 0)
    return df


# ============================================================
# 2. Attach weekly features to daily (look-ahead safe)
# ============================================================

def attach_weekly_to_daily(
    daily: pd.DataFrame,
    weekly_feat: pd.DataFrame,
) -> pd.DataFrame:
    """일봉 각 행에 "그 시점의 직전 완성 주봉" 의 MA20w/slope_4w/gate_pass 부착.

    완성 시점 = 주봉 라벨 + 7d (W-MON, label=left, closed=left 가정).
    daily.dt >= weekly.completed_at 인 가장 최근 주봉을 backward asof merge.

    Args:
        daily: data.resample.load(sym, '1d') 반환 (columns 동일)
        weekly_feat: compute_weekly_features 결과

    Returns:
        daily + ['dt', 'ma20w', 'slope_4w', 'gate_pass', 'weekly_dt']
        주봉이 충분히 누적되기 전 일봉들은 ma20w=NaN, gate_pass=False
    """
    if daily.empty or weekly_feat.empty:
        return daily.assign(dt=pd.Series(dtype="datetime64[ns]"),
                            ma20w=np.nan, slope_4w=np.nan,
                            gate_pass=False, weekly_dt=pd.NaT)

    d = daily.copy()
    d["dt"] = pd.to_datetime(d["timestamp"], unit="ms")
    d = d.sort_values("dt").reset_index(drop=True)

    w = weekly_feat.copy()
    w["completed_at"] = w["dt"] + pd.Timedelta(days=7)
    w = w.dropna(subset=["ma20w", "slope_4w"]).sort_values("completed_at").reset_index(drop=True)

    if w.empty:
        return d.assign(ma20w=np.nan, slope_4w=np.nan, gate_pass=False, weekly_dt=pd.NaT)

    merged = pd.merge_asof(
        d,
        w[["completed_at", "dt", "ma20w", "slope_4w", "gate_pass"]].rename(
            columns={"dt": "weekly_dt"}
        ),
        left_on="dt",
        right_on="completed_at",
        direction="backward",
    )
    merged["gate_pass"] = merged["gate_pass"].fillna(False).astype(bool)
    return merged.drop(columns=["completed_at"])


# ============================================================
# 3. Find entry events (touch of MA20w in downtrend)
# ============================================================

def find_entries(
    daily_attached: pd.DataFrame,
    cooldown_days: int = 28,
) -> pd.DataFrame:
    """게이트 통과 + 일봉 high >= MA20w(fixed) 인 첫 일봉 = 진입.

    Args:
        daily_attached: attach_weekly_to_daily 결과
        cooldown_days: 청산 후 재진입 쿨다운 (일 단위, 기본 28d = 4w)
                       baseline 에서는 청산 시점 미정이므로 entry 단위로만 cooldown 적용 (직전 entry 후 N일 금지)

    Returns:
        DataFrame: [entry_dt, entry_price, weekly_dt, ma20w_at_entry, slope_4w_at_entry]
        entry_price = ma20w_at_entry (지정가 체결 가정)
    """
    if daily_attached.empty:
        return pd.DataFrame(columns=["entry_dt", "entry_price", "weekly_dt",
                                       "ma20w_at_entry", "slope_4w_at_entry"])

    df = daily_attached.copy()
    df["touch"] = df["gate_pass"] & (df["high"] >= df["ma20w"]) & df["ma20w"].notna()

    # 같은 weekly_dt 안에서는 첫 터치만 (한 주에 여러 일봉 터치해도 1회만)
    df["weekly_dt"] = pd.to_datetime(df["weekly_dt"])
    first_touch = (
        df[df["touch"]]
        .sort_values("dt")
        .drop_duplicates(subset=["weekly_dt"], keep="first")
    )

    if first_touch.empty:
        return pd.DataFrame(columns=["entry_dt", "entry_price", "weekly_dt",
                                       "ma20w_at_entry", "slope_4w_at_entry"])

    # Entry-level cooldown: 직전 entry_dt 후 cooldown_days 이내면 skip
    kept_rows = []
    last_dt = None
    for _, row in first_touch.iterrows():
        if last_dt is None or (row["dt"] - last_dt).days >= cooldown_days:
            kept_rows.append(row)
            last_dt = row["dt"]
    if not kept_rows:
        return pd.DataFrame(columns=["entry_dt", "entry_price", "weekly_dt",
                                       "ma20w_at_entry", "slope_4w_at_entry"])

    out = pd.DataFrame(kept_rows)
    return pd.DataFrame({
        "entry_dt": out["dt"].values,
        "entry_price": out["ma20w"].values,
        "weekly_dt": out["weekly_dt"].values,
        "ma20w_at_entry": out["ma20w"].values,
        "slope_4w_at_entry": out["slope_4w"].values,
    })


# ============================================================
# 4. Baseline exit: rolling close_1d >= MA20w(latest completed weekly)
# ============================================================

def simulate_baseline_trades(
    daily_attached: pd.DataFrame,
    entries: pd.DataFrame,
    fee_bps_per_side: float = 5.0,
    slippage_bps: float = 5.0,
) -> pd.DataFrame:
    """진입 후 close_1d >= ma20w (rolling) 인 첫 일봉 다음 시가에 청산.

    숏 PnL = (entry - exit) / entry - 비용
    비용 = (2 * fee + slippage) bps = 15bps 기본

    Args:
        daily_attached: attach_weekly_to_daily 결과 (전체 일봉)
        entries: find_entries 결과
        fee_bps_per_side, slippage_bps: 비용 (bps = 0.01%)

    Returns:
        DataFrame: [entry_dt, entry_price, exit_dt, exit_price, ret_gross, ret_net, holding_days, exit_reason]
        exit_reason: 'close_ge_ma20w' 또는 'end_of_data'
    """
    if entries.empty:
        return pd.DataFrame(columns=["entry_dt", "entry_price", "exit_dt", "exit_price",
                                       "ret_gross", "ret_net", "holding_days", "exit_reason"])

    d = daily_attached.copy().sort_values("dt").reset_index(drop=True)
    cost = (2 * fee_bps_per_side + slippage_bps) / 10000.0

    rows = []
    for _, e in entries.iterrows():
        entry_dt = pd.to_datetime(e["entry_dt"])
        entry_price = float(e["entry_price"])

        # 진입 일봉 다음 일봉부터 청산 후보 탐색
        sub = d[d["dt"] > entry_dt].reset_index(drop=True)
        if sub.empty:
            continue

        # 청산 조건: close >= ma20w (ma20w 가 NaN 인 경우는 skip)
        cond = (sub["close"] >= sub["ma20w"]) & sub["ma20w"].notna()
        hit = cond.idxmax() if cond.any() else None

        if hit is not None and cond.iloc[hit]:
            # 조건 만족한 일봉의 다음 일봉 시가로 청산 (룩어헤드 방지)
            if hit + 1 < len(sub):
                exit_row = sub.iloc[hit + 1]
                exit_dt = exit_row["dt"]
                exit_price = float(exit_row["open"])
                exit_reason = "close_ge_ma20w"
            else:
                # 마지막 일봉에서 조건 만족 → 데이터 끝까지 보유
                exit_row = sub.iloc[hit]
                exit_dt = exit_row["dt"]
                exit_price = float(exit_row["close"])
                exit_reason = "end_of_data"
        else:
            # 데이터 끝까지 청산 안 됨 → 마지막 일봉 종가로 마감
            exit_row = sub.iloc[-1]
            exit_dt = exit_row["dt"]
            exit_price = float(exit_row["close"])
            exit_reason = "end_of_data"

        ret_gross = (entry_price - exit_price) / entry_price
        ret_net = ret_gross - cost
        holding_days = (pd.to_datetime(exit_dt) - entry_dt).days

        rows.append({
            "entry_dt": entry_dt,
            "entry_price": entry_price,
            "exit_dt": pd.to_datetime(exit_dt),
            "exit_price": exit_price,
            "ret_gross": ret_gross,
            "ret_net": ret_net,
            "holding_days": holding_days,
            "exit_reason": exit_reason,
        })

    return pd.DataFrame(rows)


# ============================================================
# 5. 4-group universe loader
# ============================================================

def load_4groups(min_obs: int = 300) -> Dict[str, List[str]]:
    """4그룹 (trend / follower / whale / junk) 심볼 dict.

    classification.parquet 의 6-way tier 를 4-way 로 합침:
      junk = junk + junk_pump + junk_new
    """
    from data.universe import load_groups

    raw = load_groups(min_obs=min_obs)
    return {
        "trend": raw.get("trend", []),
        "follower": raw.get("follower", []),
        "whale": raw.get("whale", []),
        "junk": (raw.get("junk", []) + raw.get("junk_pump", []) + raw.get("junk_new", [])),
    }


# ============================================================
# 6. End-to-end: per-symbol backtest
# ============================================================

def backtest_symbol(
    symbol: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    cooldown_days: int = 28,
    fee_bps_per_side: float = 5.0,
    slippage_bps: float = 5.0,
    ma_window: int = 20,
    slope_window: int = 4,
) -> pd.DataFrame:
    """한 심볼 baseline 백테스트 → trades DataFrame.

    실패 시 (캐시 미스 / 데이터 부족) 빈 DataFrame 반환.
    """
    try:
        daily = load_crypto(symbol, "1d")
        weekly = load_crypto(symbol, "1w")
    except Exception:
        return pd.DataFrame()

    if daily.empty or weekly.empty:
        return pd.DataFrame()

    # 룩어헤드 방지: 마지막 주봉이 미완성이면 drop
    # (W-MON, label=left, closed=left → 라벨 + 7d > 데이터 max_dt 면 미완성)
    daily["dt"] = pd.to_datetime(daily["timestamp"], unit="ms")
    weekly["dt"] = pd.to_datetime(weekly["timestamp"], unit="ms")
    daily_max_dt = daily["dt"].max()
    weekly = weekly[weekly["dt"] + pd.Timedelta(days=7) <= daily_max_dt + pd.Timedelta(days=1)].copy()

    weekly_feat = compute_weekly_features(weekly, ma_window, slope_window)
    daily_attached = attach_weekly_to_daily(daily, weekly_feat)

    if date_from:
        daily_attached = daily_attached[daily_attached["dt"] >= pd.Timestamp(date_from)].reset_index(drop=True)
    if date_to:
        daily_attached = daily_attached[daily_attached["dt"] <= pd.Timestamp(date_to)].reset_index(drop=True)

    entries = find_entries(daily_attached, cooldown_days=cooldown_days)
    if entries.empty:
        return pd.DataFrame()

    trades = simulate_baseline_trades(daily_attached, entries, fee_bps_per_side, slippage_bps)
    if not trades.empty:
        trades.insert(0, "symbol", symbol)
    return trades
