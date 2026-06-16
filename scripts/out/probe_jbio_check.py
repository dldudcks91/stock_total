"""JBIO 월봉 MA10 윈도우 N=10 적합 시각 검증."""
import sys
from pathlib import Path
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from scripts._common.mtf_loader import load_multi_tf

WINDOW = 10
MA_LEN = 10

tfs = load_multi_tf("us", "JBIO")
df_d = tfs["1D"]
df_m = tfs["1M"]
print(f"JBIO 1D rows: {len(df_d)}, first={df_d.index[0].date()}, last={df_d.index[-1].date()}")
print(f"JBIO 1M rows: {len(df_m)}, first={df_m.index[0].date()}, last={df_m.index[-1].date()}")

df_m = df_m.copy()
df_m["MA10"] = df_m["close"].rolling(MA_LEN).mean()
print(f"\n월봉 close (전체):")
print(df_m[["close", "MA10"]].to_string())

ma = df_m["MA10"].values[-WINDOW:]
print(f"\nMA10 last {WINDOW} (window) values:")
for i, v in enumerate(ma):
    print(f"  x={i}  {v:.4f}")

# 적합
x = np.arange(WINDOW, dtype=float)
a, b, c = np.polyfit(x, ma, 2)
y_fit = a * x * x + b * x + c
y_mean = ma.mean()
a_pct = a / y_mean * 100
b_pct = b / y_mean * 100
vertex_x = -b / (2 * a)
vertex_pos = vertex_x / (WINDOW - 1)
ss_res = float(np.sum((ma - y_fit) ** 2))
ss_tot = float(np.sum((ma - ma.mean()) ** 2))
r2 = 1 - ss_res / ss_tot
print(f"\n적합 결과:")
print(f"  a = {a:.6f},  b = {b:.6f},  c = {c:.4f}")
print(f"  a_pct = {a_pct:+.4f},  b_pct = {b_pct:+.4f}")
print(f"  vertex_x = {vertex_x:.2f},  vertex_pos = {vertex_pos:.3f}")
print(f"  R² = {r2:.4f}")
print(f"  y_mean (MA avg) = {y_mean:.4f}")
print(f"  MA range = [{ma.min():.4f}, {ma.max():.4f}]")
print(f"  range / mean = {(ma.max()-ma.min())/y_mean*100:.2f}%")

# 차트
win_idx = df_m.index[-WINDOW:]
fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=False)

# 상단: 일봉 + 월봉 MA10
ax = axes[0]
ax.plot(df_d.index, df_d["close"], color="lightgray", lw=0.8, label="Daily Close")
ax.plot(df_m.index, df_m["close"], color="black", lw=1.5, marker="o", markersize=5, label="Monthly Close")
ax.plot(df_m.index, df_m["MA10"], color="steelblue", lw=2.5, label="Monthly MA10")
ax.plot(win_idx, ma, color="orange", lw=4, label=f"fit window (N={WINDOW})")
ax.plot(win_idx, y_fit, color="red", lw=2, linestyle="--", label="quadratic fit")
ax.set_title(
    f"JBIO  Monthly MA10 quadratic fit  (N={WINDOW})\n"
    f"a_pct={a_pct:+.4f}  b_pct={b_pct:+.4f}  vertex_pos={vertex_pos:.2f}  R²={r2:.3f}",
    fontsize=11,
)
ax.legend(loc="best", fontsize=9)
ax.grid(alpha=0.3)

# 하단: MA10 + 적합 zoom
ax2 = axes[1]
ax2.plot(df_m.index, df_m["MA10"], color="steelblue", lw=1.5, marker="o", label="Monthly MA10")
ax2.plot(win_idx, ma, color="orange", lw=4, label="window")
ax2.plot(win_idx, y_fit, color="red", lw=2, linestyle="--", label="fit")
ax2.set_title("MA10 zoom", fontsize=10)
ax2.legend(loc="best", fontsize=9)
ax2.grid(alpha=0.3)

fig.tight_layout()
out = Path("scripts/out/_probe_jbio_check.png")
fig.savefig(out, dpi=100, bbox_inches="tight")
print(f"\nsaved: {out}")
