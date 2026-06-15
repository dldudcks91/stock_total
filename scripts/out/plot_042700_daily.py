"""한미반도체(042700) 일봉 + 주봉 차트 — 2025-09 ~ 2026-06.

분석 의도: 2~3월에 왜 포함됐어야 하는지 스스로 확인 + 시그널 마커.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.mtf_loader import load_normalized_daily, resample_multi_tf

SYM = "042700"

# 신호 통과 일자 (앞 분석 결과)
PASS_DATES = [
    "2026-01-02", "2026-04-01", "2026-04-08", "2026-04-09", "2026-04-13",
    "2026-04-21", "2026-04-22", "2026-04-27", "2026-05-19", "2026-05-22",
    "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29", "2026-06-01",
    "2026-06-04", "2026-06-12",
]

START = pd.Timestamp("2025-09-01")
END = pd.Timestamp("2026-06-15")


def main():
    df_d = load_normalized_daily("kr", SYM)
    df_d = df_d[(df_d.index >= START) & (df_d.index <= END)].copy()
    df_d["ma10_d"] = df_d["close"].rolling(10).mean()
    df_d["ma20_d"] = df_d["close"].rolling(20).mean()

    mtf = resample_multi_tf(df_d)
    df_w = mtf["1W"].copy()
    df_w["ma10_w"] = df_w["close"].rolling(10).mean()
    df_w["ma20_w"] = df_w["close"].rolling(20).mean()

    fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=False)

    # 일봉 + 일봉 MA10/MA20
    ax = axes[0]
    ax.plot(df_d.index, df_d["close"], color="black", lw=0.9, label="close")
    ax.plot(df_d.index, df_d["ma10_d"], color="orange", lw=1.0, label="MA10 (daily)")
    ax.plot(df_d.index, df_d["ma20_d"], color="blue", lw=1.0, label="MA20 (daily)")

    # 시그널 표시
    for d in PASS_DATES:
        ts = pd.Timestamp(d)
        if ts in df_d.index:
            ax.axvline(ts, color="green", alpha=0.25, lw=1.0)
            ax.scatter([ts], [df_d.loc[ts, "close"]], color="green", zorder=5, s=40, marker="^")

    # 2~3월 강조
    ax.axvspan(pd.Timestamp("2026-01-02"), pd.Timestamp("2026-02-25"),
               color="red", alpha=0.08, label="1~2월 (user 의도 구간)")
    ax.set_title(f"042700 한미반도체 — 일봉 + MA10/20 일봉, ▲ = ma_touch 통과일")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))

    # 주봉 + 주봉 MA10/MA20
    ax = axes[1]
    ax.plot(df_w.index, df_w["close"], color="black", lw=0.9, label="close (weekly)")
    ax.plot(df_w.index, df_w["ma10_w"], color="orange", lw=1.2, label="MA10 (weekly)")
    ax.plot(df_w.index, df_w["ma20_w"], color="blue", lw=1.2, label="MA20 (weekly)")
    ax.axvspan(pd.Timestamp("2026-01-02"), pd.Timestamp("2026-02-25"),
               color="red", alpha=0.08, label="1~2월")
    ax.set_title("042700 한미반도체 — 주봉 + MA10/20 주봉")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))

    plt.tight_layout()
    out_png = Path(__file__).parent / "_chart_042700.png"
    plt.savefig(out_png, dpi=110, bbox_inches="tight")
    print(f"saved {out_png.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
