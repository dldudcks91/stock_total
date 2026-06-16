"""한미반도체 주봉 + 주봉 MA5/10/20 + 타점 마커 (주봉 관점 검증)."""
import sys
from pathlib import Path
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import pandas as pd
import mplfinance as mpf
from scripts._common.mtf_loader import load_normalized_daily, resample_multi_tf

d = load_normalized_daily("kr", "042700").copy()
w = resample_multi_tf(d)["1W"].copy()          # weekly OHLCV (소문자)
w = w.loc["2025-04-01":"2026-06-15"]
w.columns = [c.capitalize() for c in w.columns]

# 타점 일자 -> 그 주의 주봉 봉으로 매핑
dates = {
    "2026-01-27": ("1/27", "blue"),
    "2026-02-23": ("2/23", "blue"),
    "2026-02-24": ("2/24", "blue"),
    "2026-03-24": ("3/24-FAIL", "red"),
    "2026-04-17": ("4/17", "orange"),
}
def week_of(dt):
    ts = pd.Timestamp(dt)
    cand = w.index[w.index <= ts]
    return cand[-1] if len(cand) else None

ap = []
labels = {}
for dt, (lab, color) in dates.items():
    wk = week_of(dt)
    if wk is None:
        continue
    m = pd.Series(np.nan, index=w.index)
    m.loc[wk] = w.loc[wk, "Low"] * 0.97
    ap.append(mpf.make_addplot(m, type="scatter", marker="^", markersize=220, color=color))
    labels.setdefault(wk, []).append((lab, color))

fig, axes = mpf.plot(
    w, type="candle", style="yahoo", mav=(5, 10, 20), volume=True,
    addplot=ap, returnfig=True, figsize=(20, 10),
    title="Hanmi (042700)  WEEKLY  MA5/10/20",
    datetime_format="%Y-%m-%d", xrotation=20,
)
ax = axes[0]
for wk, labs in labels.items():
    x = w.index.get_loc(wk)
    y = w.loc[wk, "High"] * 1.03
    txt = " ".join(l for l, _ in labs)
    ax.annotate(txt, xy=(x, y), ha="center", fontsize=11, fontweight="bold", color=labs[0][1])

out = Path("scripts/out/_chart_042700_weekly.png")
fig.savefig(out, dpi=90, bbox_inches="tight")
print("saved", out)
