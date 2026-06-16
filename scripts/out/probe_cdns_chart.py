"""CDNS (Cadence Design Systems) 일/주/월봉 + MA10/MA20 + 최근 N=10 윈도우 2차 적합 시각화."""
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
SYM = "CDNS"

tfs = load_multi_tf("us", SYM)

# 각 TF / MA 조합 적합
configs = [
    ("1D", 20, "1d_MA20"),
    ("1W", 10, "1w_MA10"),
    ("1W", 20, "1w_MA20"),
    ("1M", 10, "1M_MA10"),
    ("1M", 20, "1M_MA20"),
]

def fit_quad(y):
    x = np.arange(len(y), dtype=float)
    a, b, c = np.polyfit(x, y, 2)
    y_fit = a * x * x + b * x + c
    y_mean = y.mean()
    a_pct = a / y_mean * 100
    b_pct = b / y_mean * 100
    vertex_x = -b / (2 * a) if abs(a) > 1e-15 else float("nan")
    vertex_pos = vertex_x / (len(y) - 1) if not np.isnan(vertex_x) else float("nan")
    ss_res = float(np.sum((y - y_fit) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    slope3 = (y[-1] / y[-3] - 1) * 100
    return dict(a_pct=a_pct, b_pct=b_pct, vertex_pos=vertex_pos, r2=r2, y_fit=y_fit, slope3=slope3)

print(f"{SYM} — 5 조합 적합 결과:")
print(f"{'combo':12s} {'gap%':>8s} {'a_pct':>10s} {'b_pct':>10s} {'vtx_pos':>9s} {'slope3':>9s} {'R²':>6s}")
for tf, ma_len, label in configs:
    df = tfs[tf]
    if len(df) < ma_len + WINDOW:
        print(f"{label:12s}  insufficient data"); continue
    ma = df["close"].rolling(ma_len).mean()
    ma_win = ma.values[-WINDOW:]
    last_close = float(df["close"].iloc[-1])
    last_ma = float(ma.iloc[-1])
    px_gap = (last_close / last_ma - 1) * 100
    f = fit_quad(ma_win)
    print(f"{label:12s} {px_gap:+8.2f}  {f['a_pct']:+10.4f} {f['b_pct']:+10.4f} {f['vertex_pos']:+9.3f} {f['slope3']:+8.2f}% {f['r2']:+6.3f}")

# 5조합 차트 (2x3)
fig, axes = plt.subplots(2, 3, figsize=(20, 11))
axes = axes.flatten()

for idx, (tf, ma_len, label) in enumerate(configs):
    df = tfs[tf]
    ax = axes[idx]
    if len(df) < ma_len + WINDOW + 30:
        ax.set_title(f"{label}  insufficient data"); continue
    ma = df["close"].rolling(ma_len).mean()
    ma_win = ma.values[-WINDOW:]
    win_idx = df.index[-WINDOW:]
    f = fit_quad(ma_win)
    # 차트 = 직전 50봉 + 윈도우 + 적합 곡선
    ctx_n = 40 if tf == "1D" else (30 if tf == "1W" else 24)
    ctx = df.iloc[-(WINDOW + ctx_n):]
    ma_ctx = ma.iloc[-(WINDOW + ctx_n):]
    ax.plot(ctx.index, ctx["close"], color="black", lw=0.9, label="Close")
    ax.plot(ma_ctx.index, ma_ctx, color="steelblue", lw=1.8, label=f"MA{ma_len}")
    ax.plot(win_idx, ma_win, color="orange", lw=3.5, label=f"window (N={WINDOW})")
    ax.plot(win_idx, f["y_fit"], color="red", lw=2, linestyle="--", label="fit")
    last_close = float(df["close"].iloc[-1])
    last_ma = float(ma.iloc[-1])
    gap = (last_close / last_ma - 1) * 100
    ax.set_title(
        f"{label}  gap={gap:+.1f}%\n"
        f"a_pct={f['a_pct']:+.3f}  vtx={f['vertex_pos']:+.2f}  slope3={f['slope3']:+.2f}%  R²={f['r2']:.3f}",
        fontsize=10,
    )
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.3)
    if tf == "1D":
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    elif tf == "1W":
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    else:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

# 6번째: 일봉 풀 차트 (전체 흐름)
ax = axes[5]
df = tfs["1D"]
ax.plot(df.index, df["close"], color="black", lw=0.8, label="Daily Close")
ma20 = df["close"].rolling(20).mean()
ma60 = df["close"].rolling(60).mean()
ax.plot(df.index, ma20, color="steelblue", lw=1.2, label="MA20")
ax.plot(df.index, ma60, color="orange", lw=1.2, label="MA60")
ax.set_title(f"{SYM}  Daily (full history)  rows={len(df)}", fontsize=10)
ax.legend(loc="best", fontsize=8)
ax.grid(alpha=0.3)

fig.suptitle(f"{SYM}  Cadence Design Systems  granville analysis (5 TF/MA)",
             fontsize=12, fontweight="bold")
fig.tight_layout()
out = Path(f"scripts/out/_probe_{SYM.lower()}_chart.png")
fig.savefig(out, dpi=100, bbox_inches="tight")
print(f"\nsaved: {out}")
