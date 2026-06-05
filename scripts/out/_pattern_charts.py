"""Synthetic chart examples — VCP / Stage 2 Pullback / Wyckoff Spring (3 variants each).

Outputs:
  scripts/out/pattern_vcp.png
  scripts/out/pattern_pullback.png
  scripts/out/pattern_spring.png

각 PNG = 3-panel 가로 (textbook / variant / failure).
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# 한글 폰트 (Windows: Malgun Gothic)
for fname in ("Malgun Gothic", "AppleGothic", "NanumGothic"):
    try:
        matplotlib.font_manager.findfont(fname, fallback_to_default=False)
        matplotlib.rcParams["font.family"] = fname
        break
    except Exception:
        continue
matplotlib.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "scripts" / "out"
OUT.mkdir(parents=True, exist_ok=True)

sys.stdout.reconfigure(encoding="utf-8")


def make_close(segments, smooth=2, noise_scale=0.4):
    """segments = list of (n_bars, start, end) — concat 후 가벼운 노이즈 + smooth."""
    parts = []
    for n, s, e in segments:
        seg = np.linspace(s, e, n)
        seg += np.random.randn(n) * (abs(e - s) * 0.05 + noise_scale)
        parts.append(seg)
    close = np.concatenate(parts)
    if smooth > 1:
        close = pd.Series(close).rolling(smooth, min_periods=1).mean().values
    return close


def make_ohlcv(close, vol_pattern=None, base_vol=1.0, noise_pct=0.010):
    n = len(close)
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    rng = np.abs(np.random.randn(n)) * noise_pct
    high = np.maximum(open_, close) * (1 + rng * 0.6 + 0.001)
    low = np.minimum(open_, close) * (1 - rng * 0.6 - 0.001)
    if vol_pattern is None:
        vol = np.full(n, base_vol) * (1 + np.random.randn(n) * 0.15)
    else:
        vp = np.asarray(vol_pattern, dtype=float)
        vol = base_vol * vp * (1 + np.random.randn(n) * 0.08)
    vol = np.clip(vol, 0.1 * base_vol, None)
    return pd.DataFrame({"o": open_, "h": high, "l": low, "c": close, "v": vol})


def vol_profile(segments, kinds):
    """segments 각각의 길이에 맞춰 volume multiplier array 생성.
    kinds: list of multipliers (each segment), 같은 길이.
    """
    out = []
    for (n, _, _), k in zip(segments, kinds):
        out.append(np.full(n, k))
    return np.concatenate(out)


def draw_panel(ax_price, ax_vol, df, title,
               mas=(10, 20, 50), ma_colors=("#ff9800", "#1976d2", "#7e57c2"),
               annots=None, h_lines=None):
    n = len(df)
    for i in range(n):
        o, h, l, c = df.o.iat[i], df.h.iat[i], df.l.iat[i], df.c.iat[i]
        color = "#26a69a" if c >= o else "#ef5350"
        body_low, body_high = min(o, c), max(o, c)
        body_h = max(body_high - body_low, (h - l) * 0.02, 0.01)
        ax_price.add_patch(patches.Rectangle((i - 0.3, body_low), 0.6, body_h,
                                             facecolor=color, edgecolor=color, linewidth=0))
        ax_price.plot([i, i], [l, h], color=color, linewidth=0.7)
    x = np.arange(n)
    for ma, col in zip(mas, ma_colors):
        s = df.c.rolling(ma).mean()
        ax_price.plot(x, s, color=col, linewidth=1.3, label=f"MA{ma}", alpha=0.9)
    ax_price.legend(loc="upper left", fontsize=8, framealpha=0.9)
    ax_price.set_title(title, fontsize=11, fontweight="bold")
    ax_price.grid(alpha=0.25)
    ax_price.set_xlim(-1, n)
    pad = (df.h.max() - df.l.min()) * 0.05
    ax_price.set_ylim(df.l.min() - pad, df.h.max() + pad * 2)

    if h_lines:
        for h in h_lines:
            ax_price.axhline(h["y"], color=h.get("color", "gray"),
                             linestyle="--", linewidth=0.9, alpha=0.7)
            ax_price.text(n - 0.5, h["y"], " " + h["text"], fontsize=7,
                          color=h.get("color", "gray"), va="center")

    if annots:
        for a in annots:
            i = min(max(a["i"], 0), n - 1)
            price = a.get("price", df.h.iat[i] if a.get("above", True) else df.l.iat[i])
            dx, dy = a.get("dx", 0), a.get("dy", 35 if a.get("above", True) else -35)
            color = a.get("color", "black")
            ax_price.annotate(a["text"], xy=(i, price),
                              xytext=(dx, dy), textcoords="offset points",
                              fontsize=8, color=color, ha="center",
                              arrowprops=dict(arrowstyle="->", color=color, lw=1.0),
                              bbox=dict(boxstyle="round,pad=0.3", fc="white",
                                        ec=color, lw=0.8, alpha=0.95))

    for i in range(n):
        c_color = "#26a69a" if df.c.iat[i] >= df.o.iat[i] else "#ef5350"
        ax_vol.bar(i, df.v.iat[i], color=c_color, width=0.7, alpha=0.7)
    ax_vol.grid(alpha=0.25)
    ax_vol.set_xlim(-1, n)
    ax_vol.set_ylabel("Vol", fontsize=8)
    ax_vol.tick_params(labelsize=7)
    ax_price.tick_params(labelsize=7)


# ═══════════════════════════════════════════════════════════════
# 1. VCP
# ═══════════════════════════════════════════════════════════════

def vcp_textbook():
    segs = [
        (30, 100, 145),   # uptrend +45%
        (15, 145, 109),   # T1 -25%
        (12, 109, 142),   # recover
        (12, 142, 125),   # T2 -12%
        (10, 125, 140),   # recover
        (10, 140, 132),   # T3 -6%
        (8,  132, 139),   # recover
        (8,  139, 135),   # T4 -3% tight
        (5,  135, 139),   # very tight
        (12, 139, 175),   # 🚀 BREAKOUT
    ]
    close = make_close(segs)
    vp = vol_profile(segs, [1.1, 1.5, 0.8, 1.2, 0.7, 0.9, 0.6, 0.7, 0.4, 2.5])
    df = make_ohlcv(close, vol_pattern=vp, base_vol=1.0)
    pivot = 140
    annots = [
        {"i": 15, "text": "uptrend\n+45%", "dy": 30, "color": "gray", "above": True},
        {"i": 37, "text": "T1 -25%", "dy": -35, "color": "#c62828", "above": False},
        {"i": 63, "text": "T2 -12%", "dy": -30, "color": "#c62828", "above": False},
        {"i": 85, "text": "T3 -6%", "dy": -25, "color": "#c62828", "above": False},
        {"i": 105, "text": "T4 -3%\n(tight)", "dy": -30, "color": "#c62828", "above": False},
        {"i": 119, "text": "🚀 BREAKOUT\nvol ×2.5", "dy": 35, "color": "#2e7d32", "above": True},
    ]
    return df, "① 교과서 VCP — 4 contractions → breakout w/ volume", annots, \
           [{"y": pivot, "text": "pivot", "color": "#1565c0"}]


def vcp_tight():
    segs = [
        (25, 100, 135),
        (10, 135, 115),   # -15%
        (8,  115, 132),
        (8,  132, 121),   # -8%
        (7,  121, 130),
        (6,  130, 125),   # -4%
        (5,  125, 129),
        (5,  129, 127),   # -2% very tight
        (4,  127, 129),
        (10, 129, 158),   # breakout
    ]
    close = make_close(segs, noise_scale=0.25)
    vp = vol_profile(segs, [1.0, 1.3, 0.7, 1.0, 0.6, 0.7, 0.5, 0.5, 0.35, 2.2])
    df = make_ohlcv(close, vol_pattern=vp, base_vol=1.0)
    annots = [
        {"i": 32, "text": "-15%", "dy": -25, "color": "#c62828", "above": False},
        {"i": 49, "text": "-8%", "dy": -25, "color": "#c62828", "above": False},
        {"i": 62, "text": "-4%", "dy": -22, "color": "#c62828", "above": False},
        {"i": 72, "text": "-2%\nVDU", "dy": -25, "color": "#c62828", "above": False},
        {"i": 83, "text": "🚀 BREAKOUT", "dy": 30, "color": "#2e7d32", "above": True},
    ]
    return df, "② Tight VCP — 압축률 가파름 (15→8→4→2%), VDU 후 돌파", annots, \
           [{"y": 129, "text": "pivot", "color": "#1565c0"}]


def vcp_failed():
    segs = [
        (30, 100, 145),
        (15, 145, 109),
        (12, 109, 142),
        (12, 142, 125),
        (10, 125, 140),
        (10, 140, 132),
        (8,  132, 139),
        (8,  139, 135),
        (5,  135, 139),
        (4,  139, 145),   # breakout 살짝
        (10, 145, 120),   # 거래량 부족 → 되돌림
    ]
    close = make_close(segs)
    vp = vol_profile(segs, [1.1, 1.5, 0.8, 1.2, 0.7, 0.9, 0.6, 0.7, 0.4, 0.8, 1.4])
    df = make_ohlcv(close, vol_pattern=vp, base_vol=1.0)
    annots = [
        {"i": 38, "text": "T1 -25%", "dy": -30, "color": "#c62828", "above": False},
        {"i": 110, "text": "pivot touch\n(거래량 X)", "dy": 30, "color": "#ef6c00", "above": True},
        {"i": 119, "text": "💀 REVERSAL\nundercut → 손절", "dy": -35, "color": "#c62828", "above": False},
    ]
    return df, "③ 실패 VCP — 돌파 시 거래량 부족 → 되돌림", annots, \
           [{"y": 140, "text": "pivot", "color": "#1565c0"}]


# ═══════════════════════════════════════════════════════════════
# 2. Stage 2 Pullback
# ═══════════════════════════════════════════════════════════════

def pullback_1st():
    segs = [
        (40, 100, 102),   # Stage 1 base (flat)
        (8,  102, 125),   # Stage 2 BREAKOUT
        (20, 125, 152),   # advance
        (12, 152, 138),   # 1st pullback to MA20/50
        (3,  138, 140),   # touch
        (15, 140, 168),   # ENTRY → continuation
    ]
    close = make_close(segs)
    vp = vol_profile(segs, [0.5, 2.0, 1.0, 0.6, 0.6, 1.5])
    df = make_ohlcv(close, vol_pattern=vp, base_vol=1.0)
    annots = [
        {"i": 20, "text": "Stage 1\n(base)", "dy": 30, "color": "gray", "above": True},
        {"i": 45, "text": "Stage 2\nBREAKOUT\nvol ×2", "dy": 30, "color": "#2e7d32", "above": True},
        {"i": 70, "text": "advance\n+22%", "dy": 25, "color": "gray", "above": True},
        {"i": 82, "text": "1st 풀백\n(vol ↓)", "dy": -30, "color": "#ef6c00", "above": False},
        {"i": 86, "text": "MA20 touch\n→ ENTRY", "dy": 30, "color": "#2e7d32", "above": True},
    ]
    return df, "① 1차 풀백 — Stage 2 진입 후 첫 MA20/50 풀백 (best)", annots, None


def pullback_2nd():
    segs = [
        (20, 105, 130),   # advance
        (8,  130, 122),   # 1st small pullback
        (15, 122, 152),   # rally
        (12, 152, 138),   # 2nd pullback to MA50
        (3,  138, 140),
        (15, 140, 170),   # continuation
    ]
    close = make_close(segs)
    vp = vol_profile(segs, [1.0, 0.6, 1.2, 0.5, 0.5, 1.4])
    df = make_ohlcv(close, vol_pattern=vp, base_vol=1.0)
    annots = [
        {"i": 10, "text": "advance #1", "dy": 25, "color": "gray", "above": True},
        {"i": 24, "text": "1차 풀백\n(skip)", "dy": -30, "color": "#9e9e9e", "above": False},
        {"i": 38, "text": "advance #2", "dy": 25, "color": "gray", "above": True},
        {"i": 49, "text": "2차 풀백\nMA50 touch", "dy": -30, "color": "#ef6c00", "above": False},
        {"i": 62, "text": "ENTRY\n(vol ↑)", "dy": 30, "color": "#2e7d32", "above": True},
    ]
    return df, "② 2차 풀백 — 추세 진행 중 더 깊은 풀백 (MA50)", annots, None


def pullback_failed():
    segs = [
        (20, 100, 145),   # late stage 2
        (15, 145, 152),   # weakening (MA flattening hint)
        (10, 152, 138),   # pullback
        (8,  138, 130),   # breaks MA20
        (10, 130, 118),   # breaks MA50 → stage 4
    ]
    close = make_close(segs)
    vp = vol_profile(segs, [1.0, 0.7, 0.8, 1.4, 1.7])
    df = make_ohlcv(close, vol_pattern=vp, base_vol=1.0)
    annots = [
        {"i": 30, "text": "Stage 3\n(MA 평탄화)", "dy": 25, "color": "#ef6c00", "above": True},
        {"i": 42, "text": "거짓 풀백\nMA20 깨짐", "dy": -30, "color": "#c62828", "above": False},
        {"i": 55, "text": "💀 Stage 4\n진입 (분배 끝)", "dy": -30, "color": "#c62828", "above": False},
    ]
    return df, "③ 실패 풀백 — Stage 3 분배 구간 (MA20/50 깨짐)", annots, None


# ═══════════════════════════════════════════════════════════════
# 3. Wyckoff Spring
# ═══════════════════════════════════════════════════════════════

def spring_classic():
    segs = [
        (10, 130, 105),   # SC (selling climax)
        (5,  105, 118),   # AR
        (15, 118, 108),   # ST
        (15, 108, 117),   # ranging
        (10, 117, 109),   # ranging
        (3,  109, 102),   # 💥 SPRING dip
        (2,  102, 116),   # quick recovery
        (8,  116, 110),   # TEST (low vol)
        (15, 110, 135),   # markup
    ]
    close = make_close(segs)
    vp = vol_profile(segs, [2.5, 1.5, 1.0, 0.7, 0.6, 2.2, 2.2, 0.5, 1.6])
    df = make_ohlcv(close, vol_pattern=vp, base_vol=1.0)
    annots = [
        {"i": 5, "text": "SC\n(panic)", "dy": -25, "color": "gray", "above": False},
        {"i": 30, "text": "ST", "dy": -22, "color": "gray", "above": False},
        {"i": 56, "text": "💥 SPRING\n(이탈)", "dy": -35, "color": "#c62828", "above": False},
        {"i": 59, "text": "회복+vol\n→ ENTRY", "dy": 35, "color": "#2e7d32", "above": True},
        {"i": 65, "text": "TEST\n(low vol)", "dy": -25, "color": "#1976d2", "above": False},
        {"i": 78, "text": "MARKUP", "dy": 25, "color": "#2e7d32", "above": True},
    ]
    return df, "① 클래식 Spring + Test — 이탈→회복→retest→markup", annots, \
           [{"y": 108, "text": "support", "color": "#7e57c2"}]


def spring_lps():
    segs = [
        (10, 125, 110),
        (5,  110, 120),
        (20, 120, 115),   # accumulation (no spring)
        (15, 115, 122),
        (5,  122, 135),   # SOS BREAKOUT
        (8,  135, 123),   # pullback to former range high
        (3,  123, 125),   # LPS
        (15, 125, 152),   # markup
    ]
    close = make_close(segs)
    vp = vol_profile(segs, [2.0, 1.4, 0.7, 0.6, 2.3, 0.8, 0.5, 1.7])
    df = make_ohlcv(close, vol_pattern=vp, base_vol=1.0)
    annots = [
        {"i": 30, "text": "accumulation\n(no spring)", "dy": 25, "color": "gray", "above": True},
        {"i": 52, "text": "SOS\n(돌파, vol ×2.3)", "dy": 30, "color": "#2e7d32", "above": True},
        {"i": 58, "text": "pullback to\nformer high", "dy": -30, "color": "#ef6c00", "above": False},
        {"i": 64, "text": "LPS\n→ ENTRY", "dy": 30, "color": "#2e7d32", "above": True},
        {"i": 75, "text": "MARKUP", "dy": 25, "color": "#2e7d32", "above": True},
    ]
    return df, "② Spring 없이 LPS 진입 — 돌파 후 former resistance 풀백", annots, \
           [{"y": 122, "text": "range high", "color": "#7e57c2"}]


def spring_fake():
    segs = [
        (10, 130, 108),
        (5,  108, 118),
        (20, 118, 110),
        (10, 110, 116),
        (3,  116, 102),   # dip
        (3,  102, 108),   # weak recovery (low vol)
        (15, 108, 90),    # real breakdown
    ]
    close = make_close(segs)
    vp = vol_profile(segs, [2.2, 1.3, 0.8, 0.7, 1.8, 0.6, 1.6])
    df = make_ohlcv(close, vol_pattern=vp, base_vol=1.0)
    annots = [
        {"i": 30, "text": "base", "dy": 25, "color": "gray", "above": True},
        {"i": 46, "text": "support 이탈\n(spring like)", "dy": -30, "color": "#ef6c00", "above": False},
        {"i": 49, "text": "회복 약함\n(vol ↓)", "dy": 30, "color": "#c62828", "above": True},
        {"i": 60, "text": "💀 진짜 breakdown", "dy": -30, "color": "#c62828", "above": False},
    ]
    return df, "③ 가짜 Spring — 회복 봉 거래량 없음 → 진짜 breakdown", annots, \
           [{"y": 110, "text": "support", "color": "#7e57c2"}]


# ═══════════════════════════════════════════════════════════════
# Render
# ═══════════════════════════════════════════════════════════════

def render(name, panels):
    fig = plt.figure(figsize=(20, 7))
    gs = fig.add_gridspec(2, 3, height_ratios=[3.2, 1], hspace=0.05, wspace=0.18,
                          left=0.04, right=0.98, top=0.92, bottom=0.06)
    for col, (df, title, annots, hlines) in enumerate(panels):
        ax_p = fig.add_subplot(gs[0, col])
        ax_v = fig.add_subplot(gs[1, col], sharex=ax_p)
        draw_panel(ax_p, ax_v, df, title, annots=annots, h_lines=hlines)
        plt.setp(ax_p.get_xticklabels(), visible=False)
    out_path = OUT / f"pattern_{name}.png"
    fig.savefig(out_path, dpi=120, facecolor="white")
    plt.close(fig)
    print(f"saved: {out_path}")


def render_single(name, idx, df, title, annots, hlines):
    """Single-panel 큰 사이즈 — 인라인 표시용."""
    fig = plt.figure(figsize=(11, 6.5))
    gs = fig.add_gridspec(2, 1, height_ratios=[3.2, 1], hspace=0.05,
                          left=0.07, right=0.97, top=0.93, bottom=0.06)
    ax_p = fig.add_subplot(gs[0, 0])
    ax_v = fig.add_subplot(gs[1, 0], sharex=ax_p)
    draw_panel(ax_p, ax_v, df, title, annots=annots, h_lines=hlines)
    plt.setp(ax_p.get_xticklabels(), visible=False)
    out_path = OUT / f"pattern_{name}_{idx}.png"
    fig.savefig(out_path, dpi=130, facecolor="white")
    plt.close(fig)
    print(f"saved: {out_path}")


def main():
    np.random.seed(7)
    vcp_panels = [vcp_textbook(), vcp_tight(), vcp_failed()]
    render("vcp", vcp_panels)
    for i, p in enumerate(vcp_panels, 1):
        render_single("vcp", i, *p)

    np.random.seed(13)
    pb_panels = [pullback_1st(), pullback_2nd(), pullback_failed()]
    render("pullback", pb_panels)
    for i, p in enumerate(pb_panels, 1):
        render_single("pullback", i, *p)

    np.random.seed(21)
    sp_panels = [spring_classic(), spring_lps(), spring_fake()]
    render("spring", sp_panels)
    for i, p in enumerate(sp_panels, 1):
        render_single("spring", i, *p)


if __name__ == "__main__":
    main()
