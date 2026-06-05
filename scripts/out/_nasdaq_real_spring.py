"""실제 NASDAQ Wyckoff Spring 사례 — META / NVDA / CRWD.

Wyckoff 5-phase annotation (SC → AR → ST → Spring → LPS → SOS → Markup).
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


def load_slice(sym: str, start: str, end: str) -> pd.DataFrame:
    df = pd.read_parquet(ROOT / "data" / "cache" / "us" / f"{sym}.parquet")
    return df.loc[start:end].copy()


def draw(ax_p, ax_v, df, title, annots=None, hlines=None):
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
                  color=col, linewidth=1.3, label=f"MA{ma}", alpha=0.9)
    ax_p.legend(loc="upper left", fontsize=9, framealpha=0.9)
    ax_p.set_title(title, fontsize=12, fontweight="bold")
    ax_p.grid(alpha=0.25)
    ax_p.set_xlim(-1, n)
    pad = (df.High.max() - df.Low.min()) * 0.05
    ax_p.set_ylim(df.Low.min() - pad, df.High.max() + pad * 2)

    if hlines:
        for h in hlines:
            ax_p.axhline(h["y"], color=h.get("color", "gray"),
                         linestyle="--", linewidth=0.9, alpha=0.7)
            ax_p.text(n - 0.5, h["y"], " " + h["text"], fontsize=8,
                      color=h.get("color", "gray"), va="center")

    if annots:
        for a in annots:
            i = min(max(a["i"], 0), n - 1)
            price = a.get("price", df.High.iat[i] if a.get("above", True) else df.Low.iat[i])
            dx, dy = a.get("dx", 0), a.get("dy", 40 if a.get("above", True) else -40)
            color = a.get("color", "black")
            ax_p.annotate(a["text"], xy=(i, price),
                          xytext=(dx, dy), textcoords="offset points",
                          fontsize=9, color=color, ha="center",
                          arrowprops=dict(arrowstyle="->", color=color, lw=1.0),
                          bbox=dict(boxstyle="round,pad=0.3", fc="white",
                                    ec=color, lw=0.8, alpha=0.95))

    for i in range(n):
        c_color = "#26a69a" if df.Close.iat[i] >= df.Open.iat[i] else "#ef5350"
        ax_v.bar(i, df.Volume.iat[i], color=c_color, width=0.7, alpha=0.7)
    ax_v.grid(alpha=0.25)
    ax_v.set_xlim(-1, n)
    ax_v.set_ylabel("Vol", fontsize=9)
    n_ticks = min(10, n)
    tick_idx = np.linspace(0, n - 1, n_ticks).astype(int)
    ax_v.set_xticks(tick_idx)
    ax_v.set_xticklabels([df.index[i].strftime("%Y-%m-%d") for i in tick_idx],
                         rotation=15, fontsize=8)
    ax_p.tick_params(labelsize=8)
    plt.setp(ax_p.get_xticklabels(), visible=False)


def render(out_name, df, title, annots, hlines):
    fig = plt.figure(figsize=(14, 7.5))
    gs = fig.add_gridspec(2, 1, height_ratios=[3.2, 1], hspace=0.05,
                          left=0.06, right=0.97, top=0.93, bottom=0.10)
    ax_p = fig.add_subplot(gs[0])
    ax_v = fig.add_subplot(gs[1], sharex=ax_p)
    draw(ax_p, ax_v, df, title, annots, hlines)
    out_path = OUT / out_name
    fig.savefig(out_path, dpi=130, facecolor="white")
    plt.close(fig)
    print(f"saved: {out_path}")


def idx_of(df: pd.DataFrame, date: str) -> int:
    d = pd.Timestamp(date)
    return int(df.index.get_indexer([d], method="nearest")[0])


# ─── META 2022-10 ~ 2023-02 ───────────────────────────────────────
def meta():
    df = load_slice("META", "2022-10-15", "2023-02-15")
    annots = [
        {"i": idx_of(df, "2022-10-26"), "text": "earnings shock\n-24.6% gap", "dy": 30, "color": "gray", "above": True},
        {"i": idx_of(df, "2022-10-27"), "text": "SC\n(panic, vol 232M)", "dy": -50, "color": "gray", "above": False},
        {"i": idx_of(df, "2022-10-31"), "text": "AR\n(반등 시도)", "dy": -40, "color": "gray", "above": False, "dx": 25},
        {"i": idx_of(df, "2022-11-04"), "text": "Spring low\n$88.09\n(false breakdown)", "dy": -55, "color": "#c62828", "above": False},
        {"i": idx_of(df, "2022-11-10"), "text": "SOS +10%\nvol×1.7", "dy": 50, "color": "#2e7d32", "above": True, "dx": -20},
        {"i": idx_of(df, "2022-12-22"), "text": "LPS\n(higher low)", "dy": -40, "color": "#1976d2", "above": False, "dx": 5},
        {"i": idx_of(df, "2023-02-02"), "text": "+23%\n(Q4 earnings\nbeat = markup)", "dy": 35, "color": "#2e7d32", "above": True, "dx": -20},
    ]
    return df, "META — Wyckoff Spring (2022-10 SC → 2022-11-04 Spring → 2023-02 markup, $88 → $197 +124%)", annots, [
        {"y": 88.09, "text": "Spring low", "color": "#c62828"},
    ]


# ─── NVDA 2022-09 ~ 2023-02 ───────────────────────────────────────
def nvda_spring():
    df = load_slice("NVDA", "2022-09-01", "2023-02-28")
    annots = [
        {"i": idx_of(df, "2022-09-13"), "text": "SC #1\n-9.5%", "dy": -45, "color": "gray", "above": False},
        {"i": idx_of(df, "2022-10-13"), "text": "Spring low\n$10.81\n(범위 이탈+회복)", "dy": -55, "color": "#c62828", "above": False, "dx": -10},
        {"i": idx_of(df, "2022-11-10"), "text": "SOS +14.3%\nvol×1.55", "dy": 50, "color": "#2e7d32", "above": True, "dx": -15},
        {"i": idx_of(df, "2022-12-27"), "text": "LPS\nretest (higher low)", "dy": -45, "color": "#1976d2", "above": False, "dx": 5},
        {"i": idx_of(df, "2023-01-23"), "text": "markup\n+7.6%", "dy": 30, "color": "#2e7d32", "above": True},
        {"i": idx_of(df, "2023-02-23"), "text": "+14% earnings\nbreakout", "dy": 35, "color": "#2e7d32", "above": True, "dx": -25},
    ]
    return df, "NVDA — Wyckoff Spring (2022-10-13 Spring $10.81 → 2023-02 markup, +120% in 4 months)", annots, [
        {"y": 10.81, "text": "Spring low", "color": "#c62828"},
    ]


# ─── CRWD 2024-07 ~ 2024-12 ───────────────────────────────────────
def crwd():
    df = load_slice("CRWD", "2024-07-08", "2024-12-15")
    annots = [
        {"i": idx_of(df, "2024-07-19"), "text": "global IT outage\n-11% gap", "dy": 30, "color": "gray", "above": True},
        {"i": idx_of(df, "2024-07-22"), "text": "SC\n-13.5%\nvol ×7", "dy": -50, "color": "gray", "above": False, "dx": -5},
        {"i": idx_of(df, "2024-07-30"), "text": "AR / ST", "dy": -40, "color": "gray", "above": False, "dx": 5},
        {"i": idx_of(df, "2024-08-05"), "text": "Spring low\n$200.81\n(yen carry panic)", "dy": -55, "color": "#c62828", "above": False},
        {"i": idx_of(df, "2024-08-08"), "text": "AR\n+4.3% recovery", "dy": 50, "color": "#2e7d32", "above": True, "dx": -10},
        {"i": idx_of(df, "2024-09-06"), "text": "LPS\nretest (higher low)", "dy": -45, "color": "#1976d2", "above": False, "dx": 5},
        {"i": idx_of(df, "2024-10-29"), "text": "earnings markup", "dy": 30, "color": "#2e7d32", "above": True, "dx": -10},
        {"i": idx_of(df, "2024-12-04"), "text": "전 고점 회복\n(full markup)", "dy": 30, "color": "#2e7d32", "above": True, "dx": 10},
    ]
    return df, "CRWD — Wyckoff Spring (2024-08-05 Spring $200 → 2024-12 markup, $200 → $400 +99%)", annots, [
        {"y": 200.81, "text": "Spring low", "color": "#c62828"},
    ]


def main():
    render("real_nasdaq_spring_meta.png", *meta())
    render("real_nasdaq_spring_nvda.png", *nvda_spring())
    render("real_nasdaq_spring_crwd.png", *crwd())


if __name__ == "__main__":
    main()
