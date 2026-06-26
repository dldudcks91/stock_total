"""PCRX (Pacira BioSciences) 차트 3종 — 1d / 1w / 1M, MA10/20/50 오버레이."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from pathlib import Path

SYM = "PCRX"
PATH = Path(f"data/cache/us/{SYM}.parquet")
OUT_DIR = Path("scripts/out")

df = pd.read_parquet(PATH)
df.index = pd.to_datetime(df.index)
df = df.sort_index()
df.columns = [c.lower() for c in df.columns]
df = df[["open", "high", "low", "close", "volume"]].copy()

def resample(df, rule):
    o = df["open"].resample(rule).first()
    h = df["high"].resample(rule).max()
    l = df["low"].resample(rule).min()
    c = df["close"].resample(rule).last()
    v = df["volume"].resample(rule).sum()
    out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}).dropna()
    return out

def plot_candles(ax, d, title, bars):
    d = d.tail(bars).copy()
    ma10 = d["close"].rolling(10).mean()
    ma20 = d["close"].rolling(20).mean()
    ma50 = d["close"].rolling(50).mean()
    x = np.arange(len(d))
    up = d["close"] >= d["open"]
    width = 0.6
    for i, (idx, row) in enumerate(d.iterrows()):
        color = "#1FCC81" if row["close"] >= row["open"] else "#F6465D"
        ax.vlines(i, row["low"], row["high"], color=color, linewidth=0.8)
        body = abs(row["close"] - row["open"]) or 1e-9 * row["close"]
        bottom = min(row["open"], row["close"])
        ax.add_patch(plt.Rectangle((i - width / 2, bottom), width, row["close"] - row["open"] if row["close"] != row["open"] else 1e-3 * row["close"], color=color, alpha=0.9))
    ax.plot(x, ma10.values, color="#FFD166", linewidth=1.2, label="MA10")
    ax.plot(x, ma20.values, color="#06D6A0", linewidth=1.2, label="MA20")
    ax.plot(x, ma50.values, color="#118AB2", linewidth=1.2, label="MA50")
    ax.set_title(title, color="white", fontsize=12)
    ax.set_facecolor("#0f1117")
    ax.legend(loc="upper left", facecolor="#0f1117", edgecolor="#444", labelcolor="white", fontsize=9)
    ax.tick_params(colors="white")
    for s in ax.spines.values():
        s.set_color("#444")
    # X tick labels = sparse date strings
    n_ticks = 8
    step = max(1, len(d) // n_ticks)
    ticks = list(range(0, len(d), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([d.index[t].strftime("%Y-%m") for t in ticks], rotation=0, fontsize=8)
    ax.set_xlim(-1, len(d))
    ax.grid(True, color="#222", linestyle="--", linewidth=0.5)
    return d

specs = [
    ("1D", df, 200, "PCRX · 1D · last 200 bars (MA10/20/50)"),
    ("1W", resample(df, "W-FRI"), 150, "PCRX · 1W · last 150 bars (MA10/20/50)"),
    ("1M", resample(df, "ME"), 150, "PCRX · 1M · last 150 bars (MA10/20/50)"),
]

for label, d, bars, title in specs:
    fig, ax = plt.subplots(figsize=(13, 6), facecolor="#0f1117")
    used = plot_candles(ax, d, title, bars)
    out = OUT_DIR / f"_chart_pcrx_{label.lower()}.png"
    fig.tight_layout()
    fig.savefig(out, dpi=110, facecolor="#0f1117")
    plt.close(fig)
    last3 = used.tail(3)[["open", "high", "low", "close", "volume"]]
    print(f"[{label}] last 3 bars:")
    print(last3.to_string())
    print(f"  saved -> {out}")
