"""한미반도체 일봉 + MA5/20/60 + 후보 매수 타점 마커 (그랜빌 분류용)."""
import sys
from pathlib import Path
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd
import mplfinance as mpf
from scripts._common.mtf_loader import load_normalized_daily

df = load_normalized_daily("kr", "042700").copy()
df = df.loc["2025-09-15":"2026-06-15"]
df.columns = [c.capitalize() for c in df.columns]   # mpf 요구: Open/High/Low/Close/Volume

mav = (5, 20, 60)
# 날짜: (라벨, 그랜빌분류, 색)
dates = {
    "2025-12-19": ("12/19  [1번]", "green"),
    "2025-12-26": ("12/26  [1번]", "green"),
    "2026-01-27": ("1/27  [3번]", "blue"),
    "2026-02-23": ("2/23  [3번]", "blue"),
    "2026-02-24": ("2/24  [3번]", "blue"),
    "2026-03-24": ("3/24  [2번실패]", "red"),
    "2026-04-17": ("4/17  [2번]", "orange"),
}
import numpy as np
ap = []
for d, (lab, color) in dates.items():
    ts = pd.Timestamp(d)
    if ts in df.index:
        m = pd.Series(np.nan, index=df.index)
        m.loc[ts] = df.loc[ts, "Low"] * 0.985
        ap.append(mpf.make_addplot(m, type="scatter", marker="^", markersize=200, color=color))

fig, axes = mpf.plot(
    df, type="candle", style="yahoo", mav=mav, volume=True,
    addplot=ap, returnfig=True, figsize=(20, 10),
    title="Hanmi Semiconductor (042700)  daily  MA5/20/60",
    datetime_format="%m-%d", xrotation=0,
)
ax = axes[0]
# 날짜 라벨 텍스트 (분류 색)
for d, (lab, color) in dates.items():
    ts = pd.Timestamp(d)
    if ts in df.index:
        x = df.index.get_loc(ts)
        y = df.loc[ts, "High"] * 1.02
        ax.annotate(lab, xy=(x, y), ha="center", fontsize=11, fontweight="bold", color=color)
# 범례
ax.annotate("[1번] 전환/돌파   [3번] 상승중 지지눌림   [2번] 조정후 눌림목",
            xy=(0.5, 0.97), xycoords="axes fraction", ha="center", fontsize=13,
            fontweight="bold", color="black")

out = Path("scripts/out/_chart_042700_granville.png")
fig.savefig(out, dpi=90, bbox_inches="tight")
print("saved", out)
