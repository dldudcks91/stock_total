"""BILLUSDT 일봉 + MA20 + 최근 15봉 2차 적합 시각 검증."""
import sys
from pathlib import Path
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

CACHE = Path("data/cache/crypto/1d/BILLUSDT.parquet")
OUT = Path("scripts/out/_probe_billusdt_check.png")

WINDOW = 15
MA_LEN = 20

df = pd.read_parquet(CACHE).sort_values("timestamp")
df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
df = df.set_index("dt")
df["MA20"] = df["close"].rolling(MA_LEN).mean()
df = df.iloc[-80:].copy()  # 최근 80봉만

ma = df["MA20"].values
y = ma[-WINDOW:]
x = np.arange(WINDOW, dtype=float)
a, b, c = np.polyfit(x, y, 2)
y_fit = a * x * x + b * x + c
y_mean = y.mean()
a_pct = a / y_mean * 100
b_pct = b / y_mean * 100
vertex_x = -b / (2 * a)
vertex_pos = vertex_x / (WINDOW - 1)
ss_res = float(np.sum((y - y_fit) ** 2))
ss_tot = float(np.sum((y - y.mean()) ** 2))
r2 = 1 - ss_res / ss_tot

print(f"a_pct={a_pct:+.4f}  b_pct={b_pct:+.4f}  vertex_pos={vertex_pos:+.3f}  R²={r2:.4f}")
print(f"vertex_x={vertex_x:+.2f}  (window: 0..{WINDOW-1})")
print(f"y_mean (MA avg) = {y_mean:.6f}")
print(f"last 5 MA20: {ma[-5:]}")
print(f"MA20 slope last 5 bars: {ma[-1] - ma[-5]:+.6f}  ({(ma[-1]/ma[-5]-1)*100:+.2f}%)")
print(f"last close = {df['close'].iloc[-1]:.6f},  last MA20 = {ma[-1]:.6f},  gap = {(df['close'].iloc[-1]/ma[-1]-1)*100:+.2f}%")

win_idx = df.index[-WINDOW:]
fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
ax = axes[0]
ax.plot(df.index, df["close"], color="black", lw=1.2, label="Close")
ax.plot(df.index, df["MA20"], color="steelblue", lw=1.8, label="MA20")
ax.plot(win_idx, ma[-WINDOW:], color="orange", lw=3, label=f"fit window (N={WINDOW})")
ax.plot(win_idx, y_fit, color="red", lw=2, linestyle="--", label="quadratic fit")
# vertex 위치 마커
if 0 <= vertex_x <= WINDOW - 1:
    v_idx = win_idx[int(round(vertex_x))]
    v_y = a * vertex_x * vertex_x + b * vertex_x + c
    ax.scatter([v_idx], [v_y], color="red", s=120, zorder=5, label=f"vertex @ pos={vertex_pos:.2f}")
ax.set_title(
    f"BILLUSDT  daily MA20 quadratic fit  (N={WINDOW})\n"
    f"a_pct={a_pct:+.4f}  b_pct={b_pct:+.4f}  vertex_pos={vertex_pos:+.2f}  R²={r2:.3f}  |  "
    f"MA20 slope last 5d = {(ma[-1]/ma[-5]-1)*100:+.2f}%",
    fontsize=11,
)
ax.legend(loc="best", fontsize=9)
ax.grid(alpha=0.3)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

# 하단: MA20만 확대 + 적합 곡선
ax2 = axes[1]
ax2.plot(df.index, df["MA20"], color="steelblue", lw=1.5, label="MA20 (full)")
ax2.plot(win_idx, ma[-WINDOW:], color="orange", lw=3, label="window")
ax2.plot(win_idx, y_fit, color="red", lw=2, linestyle="--", label="fit")
ax2.set_title("MA20 zoom + fit", fontsize=10)
ax2.legend(loc="best", fontsize=9)
ax2.grid(alpha=0.3)
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

fig.tight_layout()
fig.savefig(OUT, dpi=100, bbox_inches="tight")
print(f"saved: {OUT}")
