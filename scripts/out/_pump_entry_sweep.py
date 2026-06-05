"""
pump_held_above_ma10_8bars_30d.csv 의 254건에 대해
entry 시점을 t+0(트리거), t+5, t+8, t+10, t+12, t+15, t+18, t+20 각각 시뮬레이션:
  - 각 entry → 현재가격 변화율 통계
  - 각 entry → forward +1/+5/+10봉 변화율 통계
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import numpy as np
import pandas as pd

OUT_DIR = Path("scripts/out")
SRC = OUT_DIR / "pump_held_above_ma10_8bars_30d.csv"


def entry_close(ev, entry_k):
    if entry_k == 0:
        return ev["close"]
    col = f"t+{entry_k}_close"
    return ev[col] if col in ev.columns else None


def main():
    ev = pd.read_csv(SRC)

    print(f"=== 표 1. entry 시점별 → 현재까지 변화율 (n_total=254) ===")
    print(f"{'entry':>8} {'n':>5} {'평균_%':>9} {'중앙값_%':>10} {'양수_%':>8} {'P25_%':>8} {'P75_%':>8} {'max_%':>9} {'min_%':>9}")
    rows = []
    for k in [0, 5, 8, 10, 12, 15, 18, 20]:
        e = entry_close(ev, k)
        if e is None:
            continue
        valid = e.notna() & ev["close_now"].notna()
        sub_e = e[valid]
        sub_n = ev["close_now"][valid]
        if len(sub_e) == 0:
            continue
        pct = (sub_n - sub_e) / sub_e * 100
        line = (f"{'t+'+str(k):>8} {len(pct):>5d} {pct.mean():>+9.2f} {pct.median():>+10.2f} "
                f"{(pct>0).mean()*100:>7.1f}% {pct.quantile(0.25):>+8.2f} {pct.quantile(0.75):>+8.2f} "
                f"{pct.max():>+9.2f} {pct.min():>+9.2f}")
        print(line)
        rows.append({"entry": f"t+{k}", "n": len(pct), "평균_%": pct.mean(),
                     "중앙값_%": pct.median(), "양수_%": (pct > 0).mean() * 100,
                     "P25": pct.quantile(0.25), "P75": pct.quantile(0.75),
                     "max": pct.max(), "min": pct.min()})

    pd.DataFrame(rows).to_csv(OUT_DIR / "pump_entry_sweep_current.csv", index=False)

    print(f"\n=== 표 2. entry 시점별 short-term forward (+1 / +3 / +5 / +10 봉) ===")
    print(f"{'entry':>8} {'fwd':>5} {'n':>5} {'평균_%':>9} {'중앙값_%':>10} {'양수_%':>8} {'P25_%':>8} {'P75_%':>8}")
    rows2 = []
    for k in [0, 5, 8, 10, 12, 15, 18, 20]:
        e = entry_close(ev, k)
        if e is None:
            continue
        for fwd in [1, 3, 5, 10]:
            target_k = k + fwd
            target_col = f"t+{target_k}_close"
            if target_col not in ev.columns:
                continue
            valid = e.notna() & ev[target_col].notna()
            sub_e = e[valid]
            sub_t = ev[target_col][valid]
            if len(sub_e) == 0:
                continue
            pct = (sub_t - sub_e) / sub_e * 100
            print(f"{'t+'+str(k):>8} {'+'+str(fwd):>5} {len(pct):>5d} {pct.mean():>+9.2f} "
                  f"{pct.median():>+10.2f} {(pct>0).mean()*100:>7.1f}% "
                  f"{pct.quantile(0.25):>+8.2f} {pct.quantile(0.75):>+8.2f}")
            rows2.append({"entry": f"t+{k}", "fwd": f"+{fwd}", "n": len(pct),
                          "평균_%": pct.mean(), "중앙값_%": pct.median(),
                          "양수_%": (pct > 0).mean() * 100})
    pd.DataFrame(rows2).to_csv(OUT_DIR / "pump_entry_sweep_fwd.csv", index=False)
    print(f"\nsaved → {OUT_DIR/'pump_entry_sweep_current.csv'}")
    print(f"saved → {OUT_DIR/'pump_entry_sweep_fwd.csv'}")


if __name__ == "__main__":
    main()
