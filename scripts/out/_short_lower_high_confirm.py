"""MA 기준선 3종 + 고점신호(Lower High) 확인 효과 검증.

기본 신호 (3개 MA 공통):
- 직전 10일 안에 가격이 MA 대비 -30% 이상 깊이 빠진 적 있음
- 오늘 일봉 high ≥ MA (= 닿거나 돌파)
- MA slope < 0 (장기 추세 약세)

진입 방식 2가지:
A. 즉시 진입 — 그 일봉 안에서 limit short @ MA (진입가 = MA 정확히)
B. Lower High 확인 진입 —
   - 신호일 high 가 기준 high
   - 그 후 K일 안에 high < 기준 high 인 일봉 출현 → 거부 확인
   - 진입가 = 그 lower high 봉의 close
   - K일 안에 신호일 high 가 깨지면 (= 새 고점) 신호 폐기

비교: A vs B (K=3, 5, 7), 3개 MA 각각.
hold 7일 (1주일) 고정. 강제청산 -100% 캡. 신호 20일 dedup.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"

DEPTH = 0.30
LOOKBACK_DAYS = 10
HOLD_DAYS = 7
DEDUP_DAYS = 20

CONFIRM_WINDOWS = [3, 5, 7]


def attach_mas(df: pd.DataFrame) -> pd.DataFrame:
    """3개 MA 동시 부착 — MA20w(주봉, 1주 lag forward-fill), MA100d, MA200d."""
    d = df.copy()
    d["dt"] = pd.to_datetime(d["timestamp"], unit="ms")

    # MA20w (주봉 close 기준 20주 MA, 1주 lag 후 일봉에 ffill)
    weekly = (
        d.set_index("dt")
        .resample("W-MON", label="left", closed="left")
        .agg({"close": "last"}).dropna()
    )
    weekly["ma20w"] = weekly["close"].rolling(20, min_periods=20).mean()
    weekly["ma20w_slope"] = weekly["ma20w"] / weekly["ma20w"].shift(4) - 1
    weekly_ma = weekly[["ma20w", "ma20w_slope"]].shift(1).reindex(
        d["dt"].dt.normalize().values, method="ffill"
    )
    d["ma20w"] = weekly_ma["ma20w"].values
    d["ma20w_slope"] = weekly_ma["ma20w_slope"].values

    # MA100d, MA200d (일봉)
    d["ma100d"] = d["close"].rolling(100, min_periods=100).mean()
    d["ma200d"] = d["close"].rolling(200, min_periods=200).mean()
    d["ma100d_slope"] = d["ma100d"] / d["ma100d"].shift(50) - 1
    d["ma200d_slope"] = d["ma200d"] / d["ma200d"].shift(100) - 1
    return d


def dedup_signals(sig_arr, dedup_days):
    idx = np.where(sig_arr)[0]
    if len(idx) == 0:
        return np.zeros_like(sig_arr, dtype=bool)
    keep = [idx[0]]
    for i in idx[1:]:
        if i - keep[-1] >= dedup_days:
            keep.append(i)
    out = np.zeros_like(sig_arr, dtype=bool)
    out[keep] = True
    return out


def collect_trades(files, ma_col, slope_col):
    """각 신호에 대해:
    - immediate entry (= MA 가격) → 결과
    - lower high confirmation (K=3,5,7) → 진입 여부 + 결과
    """
    # 결과 누적
    immediate = []  # list of (entry, exit, ret)
    confirmed = {k: [] for k in CONFIRM_WINDOWS}
    confirm_attempts = {k: 0 for k in CONFIRM_WINDOWS}  # K 안에 신호 발생한 시도 수
    total_signals = 0

    for f in files:
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if len(df) < 300:  # MA200d 안정화
            continue
        df = df.sort_values("timestamp").reset_index(drop=True)
        df = df.iloc[200:].reset_index(drop=True)
        if len(df) < 100:
            continue
        d = attach_mas(df)
        n = len(d)

        ma = d[ma_col]
        slope = d[slope_col]

        low_min = d["low"].shift(1).rolling(LOOKBACK_DAYS, min_periods=LOOKBACK_DAYS).min()
        cond = (
            (low_min <= ma * (1 - DEPTH)) &
            (d["high"] >= ma) &
            (slope < 0)
        )
        sig_arr = cond.fillna(False).values
        sig_arr = dedup_signals(sig_arr, DEDUP_DAYS)

        for t in np.where(sig_arr)[0]:
            if t + max(CONFIRM_WINDOWS) + HOLD_DAYS >= n:
                continue
            total_signals += 1

            entry_immediate = ma.iloc[t]
            if pd.isna(entry_immediate):
                continue
            # immediate: 진입 후 HOLD_DAYS 일 후 close
            exit_imm = d["close"].iloc[t + HOLD_DAYS]
            if not pd.isna(exit_imm):
                ret = -(exit_imm / entry_immediate - 1)
                immediate.append({"entry": entry_immediate, "exit": exit_imm, "ret": max(ret, -1.0)})

            # Lower High 확인: 신호일 t 의 high 가 기준
            base_high = d["high"].iloc[t]
            for K in CONFIRM_WINDOWS:
                confirm_attempts[K] += 1
                # t+1 ~ t+K 일 안에 lower high (high < base_high) 출현?
                # 그리고 그 사이에 새 고점 (high >= base_high) 안 나옴
                entered = False
                for k in range(1, K + 1):
                    if t + k >= n:
                        break
                    h_k = d["high"].iloc[t + k]
                    # 새 고점 갱신 → 폐기
                    if h_k > base_high:
                        break
                    # lower high → 진입
                    if h_k < base_high:
                        entry_lh = d["close"].iloc[t + k]
                        # 청산: t+k + HOLD_DAYS 후 close
                        exit_idx = t + k + HOLD_DAYS
                        if exit_idx >= n:
                            break
                        exit_lh = d["close"].iloc[exit_idx]
                        if pd.isna(entry_lh) or pd.isna(exit_lh):
                            break
                        ret_lh = -(exit_lh / entry_lh - 1)
                        confirmed[K].append({
                            "entry": entry_lh,
                            "exit": exit_lh,
                            "ret": max(ret_lh, -1.0),
                            "entry_vs_ma": entry_lh / entry_immediate - 1,
                            "confirm_day": k,
                        })
                        entered = True
                        break
                # 안 들어가면 그냥 폐기

    return immediate, confirmed, confirm_attempts, total_signals


def summarize(trades_list, label, total_signals=None, attempts=None):
    rets = pd.Series([t["ret"] for t in trades_list])
    if len(rets) == 0:
        return {
            "구분": label,
            "표본수": 0, "진입율": 0,
            "윈율": np.nan, "평균_숏수익": np.nan, "중위_숏수익": np.nan,
            "최대손실": np.nan, "표준편차": np.nan, "Sharpe": np.nan,
            "squeeze_플20_pct_이상_손실_비율": np.nan,
        }
    out = {
        "구분": label,
        "표본수": int(len(rets)),
        "진입율": float(len(rets) / (attempts or total_signals or len(rets))),
        "윈율": float((rets > 0).mean()),
        "평균_숏수익": float(rets.mean()),
        "중위_숏수익": float(rets.median()),
        "최대손실": float(rets.min()),
        "표준편차": float(rets.std()),
        "Sharpe": float(rets.mean() / rets.std()) if rets.std() > 0 else np.nan,
        "squeeze_플20_pct_이상_손실_비율": float((rets <= -0.20).mean()),
    }
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CACHE_DIR.glob("*.parquet"))
    print(f"심볼 {len(files)}개")
    print(f"공통 신호: 직전 {LOOKBACK_DAYS}일 안에 가격이 MA 대비 -{DEPTH*100:.0f}% 이상 깊이 + 오늘 high≥MA + MA slope<0")
    print(f"보유: {HOLD_DAYS}일\n")

    all_rows = []
    ma_configs = [
        ("주봉 MA20w", "ma20w", "ma20w_slope"),
        ("일봉 MA100d", "ma100d", "ma100d_slope"),
        ("일봉 MA200d", "ma200d", "ma200d_slope"),
    ]

    for ma_label, ma_col, slope_col in ma_configs:
        print(f"\n{'='*100}\n>>>>> {ma_label}\n{'='*100}")
        immediate, confirmed, confirm_attempts, total_signals = collect_trades(files, ma_col, slope_col)
        print(f"전체 신호: {total_signals}건")

        rows = []
        rows.append(summarize(immediate, "즉시 진입 (Limit @ MA)", attempts=total_signals))
        for K in CONFIRM_WINDOWS:
            rows.append(summarize(confirmed[K], f"고점확인 K={K}일 (Lower High close)", attempts=confirm_attempts[K]))
        df_out = pd.DataFrame(rows)
        # 보기 좋게 포맷
        for col in ["진입율", "윈율", "평균_숏수익", "중위_숏수익", "표준편차", "최대손실", "Sharpe", "squeeze_플20_pct_이상_손실_비율"]:
            if col in df_out.columns:
                pass
        print(df_out.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))
        # all_rows 누적
        for r in rows:
            r2 = dict(r)
            r2["MA"] = ma_label
            all_rows.append(r2)

    final = pd.DataFrame(all_rows)
    out_path = ROOT / "scripts" / "out" / "short_lower_high_confirm.csv"
    final.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_path}")


if __name__ == "__main__":
    main()
