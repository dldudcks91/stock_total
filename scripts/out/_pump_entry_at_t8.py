"""
pump_held_above_ma10_8bars_30d.csv 후처리:
  t+8 close 를 entry 로 두고, 그 이후 변화율을 t+8 기준으로 재계산.

새 표기:
  new_t+1 (= 원래 t+9), ..., new_t+12 (= 원래 t+20)
  current vs t+8
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import numpy as np
import pandas as pd

OUT_DIR = Path("scripts/out")
SRC = OUT_DIR / "pump_held_above_ma10_8bars_30d.csv"
NEW_FORWARD = 12


def main():
    ev = pd.read_csv(SRC).sort_values("ts_kst", ascending=False).reset_index(drop=True)

    t8 = ev["t+8_close"]
    for k in range(1, NEW_FORWARD + 1):
        orig = 8 + k
        col_close = f"t+{orig}_close"
        if col_close not in ev.columns:
            ev[f"new_t+{k}_pct"] = np.nan
        else:
            ev[f"new_t+{k}_pct"] = (ev[col_close] - t8) / t8 * 100
    ev["change_now_vs_t8_pct"] = (ev["close_now"] - t8) / t8 * 100

    print(f"=== t+8 entry 후 forward 통계 (n={len(ev)}) ===")
    for k in [1, 2, 3, 5, 8, 10, 12]:
        col = f"new_t+{k}_pct"
        s = ev[col].dropna()
        if len(s) == 0:
            continue
        print(f"  new t+{k:2d} (= 원래 t+{8+k:2d}, n={len(s):3d}): "
              f"평균 {s.mean():+.2f}%, 중앙값 {s.median():+.2f}%, "
              f"양수 {(s>0).sum()}/{len(s)} ({(s>0).mean()*100:.1f}%), "
              f"P25 {s.quantile(0.25):+.2f}, P75 {s.quantile(0.75):+.2f}, "
              f"최대 {s.max():+.2f}, 최소 {s.min():+.2f}")
    s = ev["change_now_vs_t8_pct"].dropna()
    print(f"  현재 vs t+8 (n={len(s)}): 평균 {s.mean():+.2f}%, 중앙값 {s.median():+.2f}%, "
          f"양수 {(s>0).sum()}/{len(s)} ({(s>0).mean()*100:.1f}%), "
          f"P25 {s.quantile(0.25):+.2f}, P75 {s.quantile(0.75):+.2f}, "
          f"최대 {s.max():+.2f}, 최소 {s.min():+.2f}")

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 280)
    pd.set_option("display.max_rows", None)
    cols = ["symbol", "ts_kst", "body_pct", "t+8_close",
            "new_t+1_pct", "new_t+2_pct", "new_t+3_pct", "new_t+4_pct",
            "new_t+6_pct", "new_t+8_pct", "new_t+10_pct", "new_t+12_pct",
            "change_now_vs_t8_pct"]
    print(f"\n=== t+8 entry 기준 변화율(%) — 시간 desc, 상위 50건 ===")
    print(ev[cols].head(50).to_string(index=False, float_format=lambda x: f"{x:+.2f}" if isinstance(x, float) else x))

    out = OUT_DIR / "pump_entry_at_t8_30d.csv"
    ev.to_csv(out, index=False)
    print(f"\nsaved → {out}")


if __name__ == "__main__":
    main()
