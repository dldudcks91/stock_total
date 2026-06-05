"""META 2022~ 주봉 차트 — 우리 전략 시그널 + 좋은 타점 annotation.

3개 시스템 전략 시그널 + 외부 토론 패턴 (VCP / Spring / MA Pullback) 사후 표기.

전략 시그널:
  - quiet_bottom  (1w binary)         - 🟣 조용한 바닥
  - trend_pullback(1w binary)         - 🟠 수렴 (Stage 2 풀백)
  - trend_chase   (1w binary)         - 🔵 추격 (강양봉+거래량 폭증)

사후 마킹:
  - Wyckoff Spring (2022-11-04)
  - VCP breakout / MA Pullback / earnings markup
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
sys.path.insert(0, str(ROOT))

for fname in ("Malgun Gothic", "AppleGothic", "NanumGothic"):
    try:
        matplotlib.font_manager.findfont(fname, fallback_to_default=False)
        matplotlib.rcParams["font.family"] = fname
        break
    except Exception:
        continue
matplotlib.rcParams["axes.unicode_minus"] = False

from backtest.strategies import quiet_bottom, trend_pullback, trend_chase


# ─── 데이터 ────────────────────────────────────────────────────
SYM = "META"
PLOT_START = "2022-01-01"
PLOT_END = "2026-05-22"

df_d = pd.read_parquet(ROOT / "data" / "cache" / "us" / f"{SYM}.parquet")
# 일봉 → 주봉 (W-MON, label/closed='left' — CLAUDE.md 시간 표준)
df_w = df_d.resample("W-MON", label="left", closed="left").agg({
    "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
}).dropna(subset=["Close"])

# 시그널 계산 — 전체 데이터로 (lookback 충분). 전략 함수는 lowercase 컬럼 요구
df_w_lower = df_w.rename(columns={c: c.lower() for c in df_w.columns}).reset_index(drop=True)
sig_qb = quiet_bottom.signal(df_w_lower, quiet_bottom.DEFAULT_PARAMS)
sig_pb = trend_pullback.signal(df_w_lower, trend_pullback.DEFAULT_PARAMS)
sig_ch = trend_chase.signal(df_w_lower, trend_chase.DEFAULT_PARAMS)
for s in (sig_qb, sig_pb, sig_ch):
    s.index = df_w.index

# plot 구간만 slice
df_plot = df_w.loc[PLOT_START:PLOT_END].copy()
sig_qb_p = sig_qb.loc[PLOT_START:PLOT_END]
sig_pb_p = sig_pb.loc[PLOT_START:PLOT_END]
sig_ch_p = sig_ch.loc[PLOT_START:PLOT_END]

# 신규 진입 (0 → 1 전환)
def new_entries(sig: pd.Series) -> list:
    diff = sig.diff().fillna(sig.iloc[0])
    return [df_plot.index.get_loc(t) for t in sig[diff == 1].index if t in df_plot.index]

qb_idx = new_entries(sig_qb_p)
pb_idx = new_entries(sig_pb_p)
ch_idx = new_entries(sig_ch_p)

print(f"META weekly 2022+ — qb entries: {len(qb_idx)} / pb entries: {len(pb_idx)} / ch entries: {len(ch_idx)}")
print(f"  qb dates: {[df_plot.index[i].date() for i in qb_idx]}")
print(f"  pb dates: {[df_plot.index[i].date() for i in pb_idx]}")
print(f"  ch dates: {[df_plot.index[i].date() for i in ch_idx]}")


# ─── 그리기 ────────────────────────────────────────────────────
def draw(ax_p, ax_v, df, title):
    n = len(df)
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
    ax_p.set_title(title, fontsize=13, fontweight="bold")
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


def mark_signal(ax, idx_list, color, marker, label, y_offset_pct=0.95):
    n = len(df_plot)
    y_top = df_plot.High.max() * y_offset_pct
    for i in idx_list:
        ax.scatter(i, y_top, marker=marker, s=140, color=color,
                   edgecolors="black", linewidths=0.8, zorder=10,
                   label=label if i == idx_list[0] else None)
        ax.plot([i, i], [df_plot.Low.iloc[i] * 0.98, y_top],
                color=color, linewidth=0.7, linestyle=":", alpha=0.5)


fig = plt.figure(figsize=(20, 10))
gs = fig.add_gridspec(2, 1, height_ratios=[3.5, 1], hspace=0.05,
                      left=0.04, right=0.97, top=0.94, bottom=0.07)
ax_p = fig.add_subplot(gs[0])
ax_v = fig.add_subplot(gs[1], sharex=ax_p)
draw(ax_p, ax_v, df_plot,
     "META 주봉 (2022-01 ~ 2026-05) — 시스템 전략 시그널 + 사후 좋은 타점")

# 시스템 전략 시그널 (top band)
mark_signal(ax_p, qb_idx, "#9c27b0", "P", "🟣 quiet_bottom", 0.98)
mark_signal(ax_p, pb_idx, "#ff9800", "o", "🟠 trend_pullback", 0.93)
mark_signal(ax_p, ch_idx, "#2196f3", "^", "🔵 trend_chase", 0.88)

# 사후 좋은 타점 (manual)
def idx_of(date):
    d = pd.Timestamp(date)
    return int(df_plot.index.get_indexer([d], method="nearest")[0])

manual = [
    # 2022 panic + spring
    {"date": "2022-10-31", "text": "Wyckoff Spring\n$88 (panic low)", "dy": -55, "color": "#c62828", "above": False},
    {"date": "2022-11-21", "text": "SOS\n(반등 시작)", "dy": -45, "color": "#2e7d32", "above": False, "dx": 20},
    # 2023 Stage 2 markup
    {"date": "2023-02-06", "text": "Q4 earnings\n+23% gap", "dy": 30, "color": "#2e7d32", "above": True},
    {"date": "2023-05-01", "text": "MA Pullback #1\n(stage 2 진입)", "dy": -50, "color": "#ff6f00", "above": False, "dx": 5},
    # 2023 후반 — pullback
    {"date": "2023-10-23", "text": "MA Pullback #2\n(MA50 터치)", "dy": -50, "color": "#ff6f00", "above": False},
    # 2024 — 추세 진행
    {"date": "2024-04-29", "text": "Q1 earnings\n-12% 가짜 풀백", "dy": -50, "color": "#9e9e9e", "above": False, "dx": -10},
    {"date": "2024-08-05", "text": "yen carry\npanic dip\n(spring-like)", "dy": -55, "color": "#c62828", "above": False, "dx": -5},
    # 2025 — VCP-like base
    {"date": "2025-03-31", "text": "VCP base\n시작", "dy": 35, "color": "#1565c0", "above": True, "dx": -10},
    {"date": "2025-04-21", "text": "tariff panic\n-30%", "dy": -55, "color": "#c62828", "above": False},
    {"date": "2025-08-04", "text": "신고가 돌파", "dy": 30, "color": "#2e7d32", "above": True, "dx": -5},
    # 2025-26 boundary
    {"date": "2025-10-27", "text": "분배 시작?\n(MA10/20 cross)", "dy": -50, "color": "#ef6c00", "above": False, "dx": 5},
]
for a in manual:
    i = idx_of(a["date"])
    if i < 0 or i >= len(df_plot):
        continue
    price = df_plot.High.iat[i] if a.get("above", True) else df_plot.Low.iat[i]
    dx, dy = a.get("dx", 0), a.get("dy", 40 if a.get("above", True) else -45)
    color = a.get("color", "black")
    ax_p.annotate(a["text"], xy=(i, price),
                  xytext=(dx, dy), textcoords="offset points",
                  fontsize=8.5, color=color, ha="center",
                  arrowprops=dict(arrowstyle="->", color=color, lw=1.0),
                  bbox=dict(boxstyle="round,pad=0.3", fc="white",
                            ec=color, lw=0.7, alpha=0.95))

# 범례 — 시스템 시그널만
ax_p.legend(loc="upper left", fontsize=10, framealpha=0.95)

out_path = OUT / "meta_weekly_strategy_review.png"
fig.savefig(out_path, dpi=130, facecolor="white")
plt.close(fig)
print(f"saved: {out_path}")
