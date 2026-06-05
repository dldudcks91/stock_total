"""META 주봉 2022~ — 3개 패턴 (VCP / MA Pullback / Wyckoff Spring) 진입 자리.

시스템 시그널은 표기하지 않음. 외부 토론 3 패턴만.

마커:
  🔵 ◆ VCP base 시작 / breakout
  🟠 ● MA Pullback (Stage 2 풀백) 진입
  🔴 ★ Wyckoff Spring (panic low + 회복)
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "scripts" / "out"
OUT.mkdir(parents=True, exist_ok=True)

sys.stdout.reconfigure(encoding="utf-8")

for fname in ("Malgun Gothic", "AppleGothic", "NanumGothic"):
    try:
        matplotlib.font_manager.findfont(fname, fallback_to_default=False)
        matplotlib.rcParams["font.family"] = fname
        break
    except Exception:
        continue
matplotlib.rcParams["axes.unicode_minus"] = False


df_d = pd.read_parquet(ROOT / "data" / "cache" / "us" / "META.parquet")
df_w = df_d.resample("W-MON", label="left", closed="left").agg({
    "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
}).dropna(subset=["Close"])
df = df_w.loc["2022-01-01":"2026-05-22"].copy()
n = len(df)


def idx_of(date):
    d = pd.Timestamp(date)
    return int(df.index.get_indexer([d], method="nearest")[0])


fig = plt.figure(figsize=(20, 10))
gs = fig.add_gridspec(2, 1, height_ratios=[3.5, 1], hspace=0.05,
                      left=0.04, right=0.97, top=0.94, bottom=0.07)
ax_p = fig.add_subplot(gs[0])
ax_v = fig.add_subplot(gs[1], sharex=ax_p)

med = df.Close.median()
for i in range(n):
    o, h, l, c = df.Open.iat[i], df.High.iat[i], df.Low.iat[i], df.Close.iat[i]
    color = "#26a69a" if c >= o else "#ef5350"
    body_low, body_high = min(o, c), max(o, c)
    body_h = max(body_high - body_low, (h - l) * 0.02, med * 0.001)
    ax_p.add_patch(patches.Rectangle((i - 0.3, body_low), 0.6, body_h,
                                     facecolor=color, edgecolor=color, linewidth=0))
    ax_p.plot([i, i], [l, h], color=color, linewidth=0.7)

x = np.arange(n)
for ma, col in zip((10, 20, 50), ("#ff9800", "#1976d2", "#7e57c2")):
    ax_p.plot(x, df.Close.rolling(ma).mean().values,
              color=col, linewidth=1.4, label=f"MA{ma}", alpha=0.9)
ax_p.set_title("META 주봉 (2022-01 ~ 2026-05) — VCP / MA Pullback / Wyckoff Spring 진입 자리",
               fontsize=13, fontweight="bold")
ax_p.grid(alpha=0.25)
ax_p.set_xlim(-1, n)
pad = (df.High.max() - df.Low.min()) * 0.05
ax_p.set_ylim(df.Low.min() - pad, df.High.max() + pad * 2)

for i in range(n):
    c_color = "#26a69a" if df.Close.iat[i] >= df.Open.iat[i] else "#ef5350"
    ax_v.bar(i, df.Volume.iat[i], color=c_color, width=0.7, alpha=0.7)
ax_v.grid(alpha=0.25)
ax_v.set_xlim(-1, n)
ax_v.set_ylabel("Vol", fontsize=9)
n_ticks = 14
tick_idx = np.linspace(0, n - 1, n_ticks).astype(int)
ax_v.set_xticks(tick_idx)
ax_v.set_xticklabels([df.index[i].strftime("%Y-%m") for i in tick_idx],
                     rotation=20, fontsize=8)
ax_p.tick_params(labelsize=8)
plt.setp(ax_p.get_xticklabels(), visible=False)


# ─── 3개 패턴 마커 ──────────────────────────────────────────
# 🔴 ★ Wyckoff Spring (panic low + 즉시 회복)
spring_entries = [
    ("2022-10-31", "Spring #1\n$88 (Q3 earnings panic)\n→ +24% 다음주", "#c62828"),
    ("2024-07-22", "Spring #2\n$442 (Q2 + yen carry)\n→ Aug 회복", "#c62828"),
    ("2025-04-21", "Spring #3\n$479 (tariff panic)\n→ 5월 회복", "#c62828"),
]

# 🟠 ● MA Pullback (Stage 2 진행 중 MA20/MA50 풀백)
pullback_entries = [
    ("2023-08-21", "MA Pullback #1\n(MA10 풀백, Stage 2 첫 풀백)", "#ff6f00"),
    ("2023-10-30", "MA Pullback #2\n(MA20 깊은 풀백)", "#ff6f00"),
    ("2024-09-09", "MA Pullback #3\n(yen carry 후 MA20)", "#ff6f00"),
    ("2025-05-12", "MA Pullback #4\n(tariff 회복 후 첫 풀백)", "#ff6f00"),
    ("2025-12-01", "MA Pullback #5\n(Q3 후 MA20 풀백)", "#ff6f00"),
]

# 🔵 ◆ VCP base + breakout (변동성 압축 후 신고가)
vcp_entries = [
    ("2024-11-04", "VCP base 시작\n($560~$595, 8주)", "#1565c0", "base"),
    ("2025-01-27", "VCP BREAKOUT\n+20% Q4 earnings\nvol×1.7", "#1565c0", "breakout"),
    ("2025-07-28", "VCP base 시작\n($700~$750, 5주)", "#1565c0", "base"),
    ("2025-09-08", "ATH 돌파\nVCP breakout", "#1565c0", "breakout"),
]

y_top = df.High.max()
y_offsets = {"spring": 0.99, "pullback": 0.94, "vcp": 0.89}

def mark(entries, marker, y_off_key, label_key):
    used = []
    for entry in entries:
        date, text, color = entry[:3]
        i = idx_of(date)
        if 0 <= i < n:
            ax_p.scatter(i, y_top * y_offsets[y_off_key], marker=marker, s=180,
                         color=color, edgecolors="black", linewidths=0.8, zorder=10)
            ax_p.plot([i, i], [df.Low.iloc[i] * 0.97, y_top * y_offsets[y_off_key]],
                      color=color, linewidth=0.7, linestyle=":", alpha=0.5)
            used.append((i, text, color))
    return used


sp_used = mark(spring_entries, "*", "spring", "Spring")
pb_used = mark(pullback_entries, "o", "pullback", "Pullback")
vcp_used = mark(vcp_entries, "D", "vcp", "VCP")

# annotations
def annot(i, text, color, above=True, dx=0, dy=None):
    price = df.High.iat[i] if above else df.Low.iat[i]
    if dy is None:
        dy = 40 if above else -50
    ax_p.annotate(text, xy=(i, price),
                  xytext=(dx, dy), textcoords="offset points",
                  fontsize=8.5, color=color, ha="center",
                  arrowprops=dict(arrowstyle="->", color=color, lw=1.0),
                  bbox=dict(boxstyle="round,pad=0.3", fc="white",
                            ec=color, lw=0.7, alpha=0.95))


# Spring annotations (저점 위치에 표시)
for i, text, color in sp_used:
    annot(i, text, color, above=False, dy=-55)

# Pullback annotations (저점 위치에)
for i, text, color in pb_used:
    annot(i, text, color, above=False, dy=-45)

# VCP annotations (고점 위치)
for i, text, color in vcp_used:
    annot(i, text, color, above=True, dy=35)


# 범례 (수동)
from matplotlib.lines import Line2D
legend_items = [
    Line2D([0], [0], color="#ff9800", lw=1.4, label="MA10"),
    Line2D([0], [0], color="#1976d2", lw=1.4, label="MA20"),
    Line2D([0], [0], color="#7e57c2", lw=1.4, label="MA50"),
    Line2D([0], [0], marker="*", color="w", markerfacecolor="#c62828",
           markeredgecolor="black", markersize=14, lw=0, label="Wyckoff Spring"),
    Line2D([0], [0], marker="o", color="w", markerfacecolor="#ff6f00",
           markeredgecolor="black", markersize=11, lw=0, label="MA Pullback"),
    Line2D([0], [0], marker="D", color="w", markerfacecolor="#1565c0",
           markeredgecolor="black", markersize=10, lw=0, label="VCP (base/breakout)"),
]
ax_p.legend(handles=legend_items, loc="upper left", fontsize=10, framealpha=0.95)

out_path = OUT / "meta_weekly_3patterns.png"
fig.savefig(out_path, dpi=130, facecolor="white")
plt.close(fig)
print(f"saved: {out_path}")
