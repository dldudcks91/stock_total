"""숏 진입 후 MAE (Max Adverse Excursion) 분포 + 손절선 시뮬레이션.

질문 (사용자):
- MA20w 근처에서 숏 쳤을 때, 가격이 그 위로 넘어가면 어디까지 가는가?
- 손절선을 어디에 놓아야 하는가?

룰:
- 진입: "최근 7일 +20%↑ 급등 + MA20w ±8% 이내 + slope < 0"
- 진입가 = 다음날 시가
- 분석:
  1. MAE — 진입 후 보유 기간 동안 가격이 최대 얼마나 위로 갔나 (= 숏 최대 손실)
  2. MAE 발생 시점 — 며칠째 최고점 찍나
  3. MA20w 대비 MAE 위치 — MA20w 위 X% 까지 돌파했나
  4. 손절선 시나리오: 진입가 대비 +3%, +5%, +8%, +10%, +15%, +20% / 무손절
     - 손절 hit 시 즉시 청산 (손실 = -손절선)
     - 손절 hit 안 한 케이스는 보유기간 만료 후 close 청산
     - 보유기간 H = 7일, 14일, 30일 각각
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"

RALLY_LOOKBACK = 7
NEAR_PCT = 0.08
DEDUP_DAYS = 15

RULES = {
    "실용판_rally_플20pct": 0.20,
    "강버전_rally_플50pct": 0.50,
}

STOP_LOSSES = [0.03, 0.05, 0.08, 0.10, 0.15, 0.20, None]  # None = 무손절
HOLD_PERIODS = [7, 14, 30]


def attach_weekly_ma20(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["dt"] = pd.to_datetime(d["timestamp"], unit="ms")
    weekly = (
        d.set_index("dt")
        .resample("W-MON", label="left", closed="left")
        .agg({"close": "last"})
        .dropna()
    )
    weekly["ma20w"] = weekly["close"].rolling(20, min_periods=20).mean()
    weekly["ma20w_slope_4w"] = weekly["ma20w"] / weekly["ma20w"].shift(4) - 1
    weekly_ma = weekly[["ma20w", "ma20w_slope_4w"]].reindex(
        d["dt"].dt.normalize().values, method="ffill"
    )
    d["ma20w"] = weekly_ma["ma20w"].values
    d["ma20w_slope_4w"] = weekly_ma["ma20w_slope_4w"].values
    return d


def dedup_signals(sig: pd.Series, dedup_days: int) -> pd.Series:
    idx = np.where(sig.fillna(False).values)[0]
    if len(idx) == 0:
        return sig
    keep = [idx[0]]
    for i in idx[1:]:
        if i - keep[-1] >= dedup_days:
            keep.append(i)
    out = pd.Series(False, index=sig.index)
    out.iloc[keep] = True
    return out


def collect_trades(files, rally_pct_threshold, max_hold=30):
    """각 신호에 대해 진입가 + 이후 max_hold 일의 high/low/close + 진입시점 MA20w 기록."""
    trades = []
    for f in files:
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if len(df) < 250:
            continue
        df = df.sort_values("timestamp").reset_index(drop=True)
        df = df.iloc[150:].reset_index(drop=True)
        if len(df) < 100:
            continue
        d = attach_weekly_ma20(df)
        d["dist_to_ma20w"] = d["close"] / d["ma20w"] - 1
        rally = d["close"] / d["close"].shift(RALLY_LOOKBACK) - 1
        sig_raw = (
            (rally >= rally_pct_threshold)
            & (d["dist_to_ma20w"].abs() <= NEAR_PCT)
            & (d["ma20w_slope_4w"] < 0)
        )
        sig = dedup_signals(sig_raw, DEDUP_DAYS)
        n = len(d)
        for i in np.where(sig.fillna(False).values)[0]:
            if i + 1 + max_hold >= n:
                continue
            entry = d["open"].iloc[i + 1]
            ma20w_at_entry = d["ma20w"].iloc[i + 1]
            if pd.isna(entry) or pd.isna(ma20w_at_entry):
                continue
            highs = d["high"].iloc[i + 1 : i + 1 + max_hold].values
            lows = d["low"].iloc[i + 1 : i + 1 + max_hold].values
            closes = d["close"].iloc[i + 1 : i + 1 + max_hold].values
            trades.append({
                "entry": float(entry),
                "ma20w_at_entry": float(ma20w_at_entry),
                "highs": highs.astype(float),
                "lows": lows.astype(float),
                "closes": closes.astype(float),
            })
    return trades


def mae_distribution(trades, horizons=(1, 3, 7, 14, 30)):
    """각 신호별 MAE (진입가 대비 최대 손실 = (max_high - entry) / entry) 분포.

    여러 horizon 별 누적 최대 손실 분포 측정.
    """
    rows = []
    for h in horizons:
        mae_pct = []
        mae_vs_ma20w = []
        for t in trades:
            if h > len(t["highs"]):
                continue
            max_high = t["highs"][:h].max()
            mae = max_high / t["entry"] - 1  # 진입가 대비 최대 손실 (양수면 가격 올라간 정도)
            mae_pct.append(mae)
            # MA20w 대비
            mae_vs = max_high / t["ma20w_at_entry"] - 1
            mae_vs_ma20w.append(mae_vs)
        if not mae_pct:
            continue
        s = pd.Series(mae_pct)
        s_ma = pd.Series(mae_vs_ma20w)
        rows.append({
            "보유기간_일_까지": h,
            "표본수": int(len(s)),
            # MAE = 진입가 대비 최대 가격 상승 (= 숏 최대 손실)
            "MAE_평균_pct": float(s.mean()),
            "MAE_p10": float(s.quantile(0.10)),
            "MAE_p25": float(s.quantile(0.25)),
            "MAE_중위": float(s.quantile(0.50)),
            "MAE_p75": float(s.quantile(0.75)),
            "MAE_p90": float(s.quantile(0.90)),
            "MAE_p95": float(s.quantile(0.95)),
            "MAE_최악": float(s.max()),
            # MA20w 대비 — 진입 후 가격 최고점이 MA20w 보다 얼마나 위
            "최고가_vs_MA20w_p50": float(s_ma.quantile(0.50)),
            "최고가_vs_MA20w_p75": float(s_ma.quantile(0.75)),
            "최고가_vs_MA20w_p90": float(s_ma.quantile(0.90)),
            "최고가_vs_MA20w_p95": float(s_ma.quantile(0.95)),
        })
    return pd.DataFrame(rows)


def stoploss_simulation(trades, stop_losses, hold_periods):
    """손절선 시나리오별 결과 시뮬레이션.

    각 trade 에 대해:
    - 보유 기간 H 동안 high 가 entry * (1 + SL) 을 처음 넘는 시점에 손절 (-SL 손실)
    - 손절 hit 안 하면 H일째 close 로 청산
    - 강제청산: 단일 손실 -100% 캡 (이 시뮬레이션은 손절선 이내 청산이라 무관)
    """
    rows = []
    for SL in stop_losses:
        for H in hold_periods:
            rets = []
            sl_hit_count = 0
            for t in trades:
                if H > len(t["highs"]):
                    continue
                entry = t["entry"]
                highs_h = t["highs"][:H]
                close_h = t["closes"][H - 1]

                if SL is None:
                    # 무손절 — H일째 close 로 청산
                    ret = -(close_h / entry - 1)
                else:
                    # 손절 가격 = entry * (1 + SL)  (숏이므로 가격이 SL% 오르면 손절)
                    sl_price = entry * (1 + SL)
                    # high 가 sl_price 를 넘는 첫 날을 찾음
                    hit_mask = highs_h >= sl_price
                    if hit_mask.any():
                        ret = -SL  # 손절 손실
                        sl_hit_count += 1
                    else:
                        ret = -(close_h / entry - 1)
                ret = max(ret, -1.0)  # 강제청산 캡
                rets.append(ret)

            if not rets:
                continue
            s = pd.Series(rets)
            rows.append({
                "손절선_pct": "무손절" if SL is None else f"+{SL:.0%}",
                "보유기간_일": H,
                "표본수": int(len(s)),
                "손절_히트율": float(sl_hit_count / len(s)) if SL is not None else 0.0,
                "윈율": float((s > 0).mean()),
                "평균_숏수익": float(s.mean()),
                "p10": float(s.quantile(0.10)),
                "p25": float(s.quantile(0.25)),
                "중위_p50": float(s.quantile(0.50)),
                "p75": float(s.quantile(0.75)),
                "p90": float(s.quantile(0.90)),
                "최대손실": float(s.min()),
                "표준편차": float(s.std()),
                "Sharpe_like": float(s.mean() / s.std()) if s.std() > 0 else np.nan,
            })
    return pd.DataFrame(rows)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CACHE_DIR.glob("*.parquet"))
    print(f"심볼 {len(files)}개")

    for name, threshold in RULES.items():
        print(f"\n>>>>>>>>>>  {name}  (rally ≥ +{threshold:.0%})  <<<<<<<<<<")
        trades = collect_trades(files, threshold, max_hold=30)
        print(f"신호 (dedup 후): {len(trades)} 건")

        # 1. MAE 분포
        mae_df = mae_distribution(trades)
        print()
        print("=" * 130)
        print(f"[{name}] MAE 분포 — 진입 후 N일까지 가격이 진입가 대비 얼마나 위로 갔나 (양수 = 숏 손실)")
        print("=" * 130)
        print(mae_df.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

        # 2. 손절선 시뮬레이션
        sl_df = stoploss_simulation(trades, STOP_LOSSES, HOLD_PERIODS)
        print()
        print("=" * 130)
        print(f"[{name}] 손절선 시나리오 (진입가 대비 +X% 위로 가면 손절)")
        print("=" * 130)
        print(sl_df.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

        # 저장
        mae_path = ROOT / "scripts" / "out" / f"short_mae_{name}.csv"
        sl_path = ROOT / "scripts" / "out" / f"short_stoploss_{name}.csv"
        mae_df.to_csv(mae_path, index=False, encoding="utf-8-sig")
        sl_df.to_csv(sl_path, index=False, encoding="utf-8-sig")
        print(f"\nCSV: {mae_path}")
        print(f"CSV: {sl_path}")


if __name__ == "__main__":
    main()
