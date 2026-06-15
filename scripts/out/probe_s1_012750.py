"""에스원(012750) — Thu/Fri/Mon 각 TF 별 게이트 상태 디버그."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.mtf_loader import load_normalized_daily, resample_multi_tf
from scripts._common.mtf_indicators import compute_mtf_indicators
from scripts._common.signals import _compute_range_threshold
from scripts._common.tf_selector import determine_eval_kind, select_eval_tfs
from scripts._common.recommend_runner import EVAL_TFS

SYM = "012750"
DATES = [
    ("Thu", pd.Timestamp("2026-06-11")),
    ("Fri", pd.Timestamp("2026-06-12")),
    ("Mon", pd.Timestamp("2026-06-15")),
]


def main():
    df_full = load_normalized_daily("kr", SYM)
    print(f"=== {SYM} 에스원 — 최근 10일 OHLC ===")
    print(df_full[["open", "high", "low", "close"]].tail(10).to_string())
    print()

    for label, cutoff in DATES:
        df_d = df_full[df_full.index <= cutoff]
        th = _compute_range_threshold(df_d)
        today_low = float(df_d["low"].iloc[-1])
        close = float(df_d["close"].iloc[-1])
        print(f"=== [{label} cutoff={cutoff.date()}] close={close:,.0f}  today_low={today_low:,.0f}  th_abs={th:,.0f} ({th/close*100:.2f}%) ===")

        mtf = resample_multi_tf(df_d)
        allowed = set(select_eval_tfs(mtf))
        for tf in EVAL_TFS:
            df_tf = mtf[tf]
            kind = determine_eval_kind(df_tf)
            allow = tf in allowed
            if kind == "skip" or not allow:
                print(f"  {tf:3s}: skip (kind={kind}, allowed={allow})")
                continue
            df_ind = compute_mtf_indicators(df_tf, kind)
            last = df_ind.iloc[-1]
            ma10 = last["ma10"]
            ma20 = last.get("ma20")
            sl10 = last["slope_pct_ma10"]
            sl20 = last.get("slope_pct_ma20")

            if kind == "full":
                g_align = (ma10 > ma20) and (close > ma20)
                g_slope = (sl10 > 0) and (sl20 > 0)
                d10 = abs(today_low - ma10)
                d20 = abs(today_low - ma20)
                g_touch = (d10 <= th) or (d20 <= th)
                passed = g_align and g_slope and g_touch
                near10 = d10 / th if th > 0 else float("inf")
                near20 = d20 / th if th > 0 else float("inf")
                signed_d20 = today_low - ma20
                print(f"  {tf:3s}: MA10={ma10:,.0f}  MA20={ma20:,.0f}  sl10={sl10*100:+.2f}%  sl20={sl20*100:+.2f}%  "
                      f"align={g_align}  slope+={g_slope}  near10={near10:.2f}  near20={near20:.2f}  signed20={signed_d20:+,.0f}  touch={g_touch}  PASS={passed}")
            else:
                d10 = abs(today_low - ma10)
                g_align = close > ma10
                g_slope = sl10 > 0
                g_touch = d10 <= th
                near10 = d10 / th if th > 0 else float("inf")
                passed = g_align and g_slope and g_touch
                print(f"  {tf:3s}: PARTIAL MA10={ma10:,.0f}  sl10={sl10*100:+.2f}%  align={g_align}  slope+={g_slope}  near10={near10:.2f}  touch={g_touch}  PASS={passed}")
        print()


if __name__ == "__main__":
    main()
