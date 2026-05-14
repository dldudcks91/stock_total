"""특정 시그널 종목의 차트 직접 확인 — 박치기(false breakout) 있는지 시각.

MA10 노랑, MA20 빨강, MA50 파랑.
"""
from __future__ import annotations
import sys, numpy as np, pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.quiet_bottom.count_slope_turn_signals import load_crypto_weekly

SYMS = ["PENGUUSDT", "CHZUSDT", "SUNUSDT", "MORPHOUSDT"]
LOOKBACK_WEEKS = 78   # 직전 1.5년


def count_false_breakouts(close, ma20, lookback):
    """MA20 위로 올라갔다가 다시 아래로 빠진 시도 횟수 (직전 lookback 봉 중)."""
    above = (close >= ma20).to_numpy()
    n_visible = min(lookback, len(close))
    sub = above[-n_visible:]
    cu = 0
    for j in range(1, len(sub)):
        if sub[j] and not sub[j-1]:
            cu += 1
    # 마지막 cross-up이 현재 ON으로 이어지면 -1 (그건 진입 시도가 아니라 우리가 보는 신호)
    if cu > 0 and above[-1]:
        cu -= 1
    return cu


def main():
    fig, axes = plt.subplots(len(SYMS), 1, figsize=(15, 4*len(SYMS)))
    if len(SYMS) == 1:
        axes = [axes]
    for ax, sym in zip(axes, SYMS):
        path = ROOT / f"data/cache/crypto/1h/{sym}.parquet"
        if not path.exists():
            ax.set_title(f"{sym} (no data)")
            continue
        df_w = load_crypto_weekly(path).sort_index()
        if len(df_w) < 60:
            ax.set_title(f"{sym} (too short)")
            continue
        ma10 = df_w["close"].rolling(10).mean()
        ma20 = df_w["close"].rolling(20).mean()
        ma50 = df_w["close"].rolling(50).mean()
        seg = df_w.iloc[-LOOKBACK_WEEKS:]
        m10s = ma10.loc[seg.index]
        m20s = ma20.loc[seg.index]
        m50s = ma50.loc[seg.index]

        # 박치기 카운트 (직전 lookback)
        n_bumps = count_false_breakouts(df_w["close"], ma20, LOOKBACK_WEEKS)

        # 가격 (candle 대신 선)
        ax.plot(seg.index, seg["close"], color="#333", lw=1.4, label="close")
        ax.fill_between(seg.index, seg["low"], seg["high"], color="#999", alpha=0.15, label="high-low range")
        # MA10 노랑, MA20 빨강, MA50 파랑
        ax.plot(m10s.index, m10s.values, color="orange",    lw=2.0, label="MA10")
        ax.plot(m20s.index, m20s.values, color="red",       lw=2.0, label="MA20")
        ax.plot(m50s.index, m50s.values, color="royalblue", lw=2.0, label="MA50")
        # close가 MA20 위로 올라간 시점 표시
        above = (seg["close"] >= m20s)
        for i in range(1, len(seg)):
            if above.iloc[i] and not above.iloc[i-1]:
                ax.axvline(seg.index[i], color="green", ls=":", lw=1, alpha=0.6)

        # 최신 봉 강조
        ax.axvline(df_w.index[-1], color="black", ls="--", lw=1.5, alpha=0.8)
        ax.scatter([df_w.index[-1]], [df_w["close"].iloc[-1]], color="black", s=70, zorder=5)

        ax.set_title(f"{sym}  —  close={df_w['close'].iloc[-1]:.6g}  "
                     f"|  '박치기'(false-breakouts) in last {LOOKBACK_WEEKS}w: {n_bumps}",
                     fontsize=13, weight="bold")
        ax.legend(loc="upper left", fontsize=10)
        ax.grid(alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        for tick in ax.get_xticklabels():
            tick.set_rotation(20)

    fig.tight_layout()
    out = ROOT / "scripts/out/signal_check.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
