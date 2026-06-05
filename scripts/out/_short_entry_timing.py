"""숏 진입 타점 비교 — 같은 신호에 5가지 다른 진입가 적용.

확정 신호 (주봉 wick test):
- 주봉 candle 의 high >= MA20w
- 주봉 candle 의 low <= MA20w * (1 - 0.30)
- 주봉 close < MA20w
- MA20w slope_4w < 0

진입가 5종:
  A. 다음주 시가 (현재 룰 — baseline)
     entry = open_w[t+1]

  B. 신호 주봉의 close (그 주 마감 시점 즉시)
     entry = close_w[t]
     → 분배 캔들 마감 즉시 숏. 갭 위험 없지만 늦은 진입

  C. 신호 주봉의 high (idealized — 그 주 최고가에서 정확히 reject)
     entry = high_w[t]
     → 실전 불가, R:R 측정용

  D. MA20w 정확히 (idealized — MA20w 저항선 정확히 터치)
     entry = ma20w[t]
     → 실전엔 limit order. 신호 주봉 안에 high >= MA20w 이므로 도달함

  E. 다음 주 retest (다음주 high >= MA20w 도달 시 진입, 안 도달 시 미진입)
     entry = ma20w[t+1] 도달가 (시뮬 — high_w[t+1] >= ma20w[t+1] 인 경우만 진입)
     → 실전 limit short. 안 닿으면 신호 폐기

룰: hold 4주, 강제청산 -100% 캡, 4주 dedup.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "crypto" / "1d"

LOW_GAP_X = 0.30
HOLD_WEEKS = 4
DEDUP_WEEKS = 4


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["dt"] = pd.to_datetime(d["timestamp"], unit="ms")
    weekly = (
        d.set_index("dt")
        .resample("W-MON", label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    weekly["ma20w"] = weekly["close"].rolling(20, min_periods=20).mean()
    weekly["ma20w_slope_4w"] = weekly["ma20w"] / weekly["ma20w"].shift(4) - 1
    return weekly.reset_index(drop=True)


def dedup_signals(sig_arr, dedup_weeks):
    idx = np.where(sig_arr)[0]
    if len(idx) == 0:
        return np.zeros_like(sig_arr, dtype=bool)
    keep = [idx[0]]
    for i in idx[1:]:
        if i - keep[-1] >= dedup_weeks:
            keep.append(i)
    out = np.zeros_like(sig_arr, dtype=bool)
    out[keep] = True
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CACHE_DIR.glob("*.parquet"))
    print(f"심볼 {len(files)}개")

    # 진입가 5종 → list of (entry, exit) for short_ret 계산
    results = {
        "A_다음주_시가": [],
        "B_신호주_close": [],
        "C_신호주_high_idealized": [],
        "D_MA20w_정확히_idealized": [],
        "E_다음주_MA20w_retest": [],
    }
    # 진입가별 진입 카운트 (E 는 미진입 케이스 있음)
    entry_counts = {k: 0 for k in results}
    total_signals = 0

    for i, f in enumerate(files):
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if len(df) < 250:
            continue
        df = df.sort_values("timestamp").reset_index(drop=True)
        w = to_weekly(df)
        w = w.iloc[30:].reset_index(drop=True)
        if len(w) < 30:
            continue

        cond = (
            (w["high"] >= w["ma20w"]) &
            (w["low"] <= w["ma20w"] * (1 - LOW_GAP_X)) &
            (w["close"] < w["ma20w"]) &
            (w["ma20w_slope_4w"] < 0)
        )
        sig_arr = cond.fillna(False).values
        sig_arr = dedup_signals(sig_arr, DEDUP_WEEKS)

        # 청산 가격: hold 주 뒤 close
        exit_price = w["close"].shift(-(HOLD_WEEKS + 0)).values  # 신호 주봉 +H 주의 close

        for t in np.where(sig_arr)[0]:
            if t + 1 + HOLD_WEEKS >= len(w):
                continue
            total_signals += 1

            ma_t = w["ma20w"].iloc[t]
            high_t = w["high"].iloc[t]
            close_t = w["close"].iloc[t]
            open_next = w["open"].iloc[t + 1]
            high_next = w["high"].iloc[t + 1]
            ma_next = w["ma20w"].iloc[t + 1]

            # 청산 close = 진입 주 + HOLD_WEEKS 의 close
            # A 진입: t+1 시가 → 청산: t+1+HOLD_WEEKS 의 close
            exit_A = w["close"].iloc[t + 1 + HOLD_WEEKS - 1] if t + 1 + HOLD_WEEKS - 1 < len(w) else np.nan
            # B/C/D 진입: t 시점 → 청산: t+HOLD_WEEKS 의 close
            exit_BCD = w["close"].iloc[t + HOLD_WEEKS] if t + HOLD_WEEKS < len(w) else np.nan
            # E: 다음 주 high 가 MA20w 도달하면 진입가=MA20w, 아니면 미진입
            # 진입 시점 = t+1 주, 청산 = t+1+HOLD_WEEKS-1 주의 close
            exit_E = w["close"].iloc[t + HOLD_WEEKS] if t + HOLD_WEEKS < len(w) else np.nan

            if pd.notna(open_next) and pd.notna(exit_A):
                ret_A = -(exit_A / open_next - 1)
                results["A_다음주_시가"].append({"entry": open_next, "exit": exit_A, "ret": max(ret_A, -1.0), "ma": ma_t})
                entry_counts["A_다음주_시가"] += 1

            if pd.notna(close_t) and pd.notna(exit_BCD):
                ret_B = -(exit_BCD / close_t - 1)
                results["B_신호주_close"].append({"entry": close_t, "exit": exit_BCD, "ret": max(ret_B, -1.0), "ma": ma_t})
                entry_counts["B_신호주_close"] += 1

            if pd.notna(high_t) and pd.notna(exit_BCD):
                ret_C = -(exit_BCD / high_t - 1)
                results["C_신호주_high_idealized"].append({"entry": high_t, "exit": exit_BCD, "ret": max(ret_C, -1.0), "ma": ma_t})
                entry_counts["C_신호주_high_idealized"] += 1

            if pd.notna(ma_t) and pd.notna(exit_BCD):
                ret_D = -(exit_BCD / ma_t - 1)
                results["D_MA20w_정확히_idealized"].append({"entry": ma_t, "exit": exit_BCD, "ret": max(ret_D, -1.0), "ma": ma_t})
                entry_counts["D_MA20w_정확히_idealized"] += 1

            # E: 다음 주 안에 MA20w 다시 도달 시 진입
            if pd.notna(high_next) and pd.notna(ma_next) and pd.notna(exit_E):
                if high_next >= ma_next:
                    entry_E = ma_next  # 가정: MA20w 정확히 닿을 때 limit 체결
                    ret_E = -(exit_E / entry_E - 1)
                    results["E_다음주_MA20w_retest"].append({
                        "entry": entry_E, "exit": exit_E, "ret": max(ret_E, -1.0), "ma": ma_t,
                    })
                    entry_counts["E_다음주_MA20w_retest"] += 1
                # 안 닿으면 미진입 (카운트 안 함)

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(files)}")

    print(f"\n총 신호 발생: {total_signals}건")
    print()

    rows = []
    for name, trades in results.items():
        if not trades:
            continue
        rets = pd.Series([t["ret"] for t in trades])
        entries = pd.Series([t["entry"] for t in trades])
        mas = pd.Series([t["ma"] for t in trades])
        # 진입가의 MA20w 대비 위치
        entry_vs_ma = entries / mas - 1
        rows.append({
            "진입_타점": name,
            "진입_표본수": entry_counts[name],
            "진입율_vs_총신호": entry_counts[name] / total_signals if total_signals else 0,
            "윈율": float((rets > 0).mean()),
            "평균_숏수익": float(rets.mean()),
            "중위_숏수익": float(rets.median()),
            "p10": float(rets.quantile(0.10)),
            "p25": float(rets.quantile(0.25)),
            "p75": float(rets.quantile(0.75)),
            "p90": float(rets.quantile(0.90)),
            "표준편차": float(rets.std()),
            "최대손실": float(rets.min()),
            "Sharpe_like": float(rets.mean() / rets.std()) if rets.std() > 0 else np.nan,
            "진입가_vs_MA20w_중위": float(entry_vs_ma.median()),
            "진입가_vs_MA20w_평균": float(entry_vs_ma.mean()),
        })

    out = pd.DataFrame(rows)
    print("=" * 130)
    print("진입 타점 5종 비교 (hold 4주, 강제청산 -100% 캡):")
    print("=" * 130)
    print(out.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    print()
    print("=" * 130)
    print("진입가가 MA20w 대비 어디였나 (중위·평균):")
    print("=" * 130)
    print(out[["진입_타점", "진입가_vs_MA20w_중위", "진입가_vs_MA20w_평균"]].to_string(index=False, float_format=lambda x: f"{x:+.4f}"))

    out_path = ROOT / "scripts" / "out" / "short_entry_timing.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_path}")


if __name__ == "__main__":
    main()
