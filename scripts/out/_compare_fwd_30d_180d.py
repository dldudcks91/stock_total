"""
30일 vs 180일 윈도우의 t+1~t+20 forward 변화율 비교
(entry = 트리거 봉, t+1~t+8 MA10 위 유지한 케이스).
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import pandas as pd

OUT_DIR = Path("scripts/out")


def load(fn):
    df = pd.read_csv(OUT_DIR / fn)
    for k in range(1, 21):
        c = f"t+{k}_close"
        if c in df.columns:
            df[f"t+{k}_pct"] = (df[c] - df["close"]) / df["close"] * 100
    return df


def main():
    ev30 = load("pump_held_above_ma10_8bars_30d.csv")
    ev180 = load("pump_held_above_ma10_8bars_180d.csv")

    print(f"30일  윈도우: {len(ev30)}건")
    print(f"180일 윈도우: {len(ev180)}건")

    print(f"\n{'봉':>5}  "
          f"{'30일_n':>6} {'30일_평균':>9} {'30일_중앙값':>10} {'30일_양수_%':>10}  "
          f"{'180일_n':>7} {'180일_평균':>10} {'180일_중앙값':>11} {'180일_양수_%':>11}  "
          f"{'평균_diff':>9} {'중앙값_diff':>11}")
    for k in range(1, 21):
        col = f"t+{k}_pct"
        s30 = ev30[col].dropna()
        s180 = ev180[col].dropna()
        d_mean = s180.mean() - s30.mean()
        d_med = s180.median() - s30.median()
        print(f"{'t+'+str(k):>5}  "
              f"{len(s30):>6d} {s30.mean():>+9.2f} {s30.median():>+10.2f} {(s30>0).mean()*100:>9.1f}%  "
              f"{len(s180):>7d} {s180.mean():>+10.2f} {s180.median():>+11.2f} {(s180>0).mean()*100:>10.1f}%  "
              f"{d_mean:>+9.2f} {d_med:>+11.2f}")


if __name__ == "__main__":
    main()
