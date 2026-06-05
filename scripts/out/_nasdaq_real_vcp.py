"""실제 NASDAQ VCP 사례 — NVDA / SMCI / PLTR.

각 종목을 base 시작 ~ breakout 후 몇 주까지 잘라 candle + MA + volume + 패턴 annotation.
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

# 한글 폰트
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


# ─── NVDA 2023-08 ~ 2024-02 (Minervini cited example) ──────────────
def nvda():
    df = load_slice("NVDA", "2023-07-15", "2024-02-20")
    annots = [
        {"i": idx_of(df, "2023-08-24"), "text": "high $49.7\n(base 시작)", "dy": 35, "color": "gray", "above": True},
        {"i": idx_of(df, "2023-10-13"), "text": "T1 -22%\nlow $39.3", "dy": -45, "color": "#c62828", "above": False},
        {"i": idx_of(df, "2023-11-21"), "text": "high $50.5", "dy": 30, "color": "gray", "above": True},
        {"i": idx_of(df, "2023-12-14"), "text": "T2 -10%", "dy": -40, "color": "#c62828", "above": False},
        {"i": idx_of(df, "2024-01-03"), "text": "T3 -4%\n(tight base, VDU)", "dy": -45, "color": "#c62828", "above": False},
        {"i": idx_of(df, "2024-01-08"), "text": "BREAKOUT\n+8.5% vol×1.6", "dy": 50, "color": "#2e7d32", "above": True, "dx": -10},
        {"i": idx_of(df, "2024-01-09"), "text": "follow-through\n+1.7% vol×1.93", "dy": 30, "color": "#2e7d32", "above": True, "dx": 60},
    ]
    return df, "NVDA — Minervini VCP (2023-08 base → 2024-01-08 breakout, post-split adj)", annots, [
        {"y": 50.43, "text": "pivot $50.43", "color": "#1565c0"},
    ]


# ─── SMCI 2023-09 ~ 2024-02 (Earnings catalyst VCP) ──────────────
def smci():
    df = load_slice("SMCI", "2023-09-01", "2024-02-29")
    annots = [
        {"i": idx_of(df, "2023-09-12"), "text": "base 시작\nhigh ~$36", "dy": 35, "color": "gray", "above": True},
        {"i": idx_of(df, "2023-10-26"), "text": "T1 -33%\nlow $22.7", "dy": -45, "color": "#c62828", "above": False},
        {"i": idx_of(df, "2023-11-30"), "text": "T2 -18%", "dy": -40, "color": "#c62828", "above": False},
        {"i": idx_of(df, "2024-01-08"), "text": "tight base\n(VDU)", "dy": -45, "color": "#c62828", "above": False},
        {"i": idx_of(df, "2024-01-19"), "text": "BREAKOUT\n+36% (earnings)\nvol×6.5", "dy": 60, "color": "#2e7d32", "above": True, "dx": -20},
        {"i": idx_of(df, "2024-02-15"), "text": "+14% follow-through", "dy": 30, "color": "#2e7d32", "above": True, "dx": -50},
        {"i": idx_of(df, "2024-02-22"), "text": "+33%\n(blow-off)", "dy": 30, "color": "#2e7d32", "above": True, "dx": 40},
    ]
    return df, "SMCI — Earnings-driven VCP (2023-09 base → 2024-01-19 breakout, +400% in 30 days)", annots, None


# ─── PLTR 2024-07 ~ 2024-10 (S&P 500 inclusion catalyst) ──────────────
def pltr():
    df = load_slice("PLTR", "2024-07-01", "2024-10-20")
    annots = [
        {"i": idx_of(df, "2024-07-22"), "text": "prior uptrend\nhigh $28.8", "dy": 35, "color": "gray", "above": True},
        {"i": idx_of(df, "2024-08-05"), "text": "T1 -18%\n(yen carry panic)", "dy": -45, "color": "#c62828", "above": False},
        {"i": idx_of(df, "2024-08-22"), "text": "회복 + 횡보", "dy": 30, "color": "gray", "above": True},
        {"i": idx_of(df, "2024-09-06"), "text": "T2 -7%\n(VDU)", "dy": -40, "color": "#c62828", "above": False},
        {"i": idx_of(df, "2024-09-09"), "text": "BREAKOUT\n+14% S&P 500\ninclusion\nvol×2.8", "dy": 60, "color": "#2e7d32", "above": True, "dx": 15},
        {"i": idx_of(df, "2024-10-04"), "text": "stair-step\ncontinuation", "dy": 30, "color": "#2e7d32", "above": True, "dx": 40},
    ]
    return df, "PLTR — VCP + S&P 500 inclusion catalyst (2024-07 base → 2024-09-09 breakout)", annots, None


def main():
    render("real_nasdaq_vcp_nvda.png", *nvda())
    render("real_nasdaq_vcp_smci.png", *smci())
    render("real_nasdaq_vcp_pltr.png", *pltr())


if __name__ == "__main__":
    main()
