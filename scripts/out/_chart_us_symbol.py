"""범용 US 종목 차트 (1d / 1w / 1M) + MA10/20/50 — 명령행 인자로 심볼 받음."""
import sys, io, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--asset", default="us", choices=["us", "kr"])
    ap.add_argument("--bars1d", type=int, default=200)
    ap.add_argument("--bars1w", type=int, default=150)
    ap.add_argument("--bars1m", type=int, default=150)
    args = ap.parse_args()

    SYM = args.symbol
    PATH = Path(f"data/cache/{args.asset}/{SYM}.parquet")
    OUT_DIR = Path("scripts/out")
    df = pd.read_parquet(PATH)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].copy()

    def resample(d, rule):
        o = d["open"].resample(rule).first()
        h = d["high"].resample(rule).max()
        l = d["low"].resample(rule).min()
        c = d["close"].resample(rule).last()
        v = d["volume"].resample(rule).sum()
        return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}).dropna()

    def plot_candles(ax, d, title, bars):
        d = d.tail(bars).copy()
        ma10 = d["close"].rolling(10).mean()
        ma20 = d["close"].rolling(20).mean()
        ma50 = d["close"].rolling(50).mean()
        x = np.arange(len(d))
        width = 0.6
        for i, (idx, row) in enumerate(d.iterrows()):
            color = "#1FCC81" if row["close"] >= row["open"] else "#F6465D"
            ax.vlines(i, row["low"], row["high"], color=color, linewidth=0.8)
            body_h = row["close"] - row["open"] if row["close"] != row["open"] else 1e-3 * row["close"]
            bottom = min(row["open"], row["close"])
            ax.add_patch(plt.Rectangle((i - width / 2, bottom), width, body_h, color=color, alpha=0.9))
        ax.plot(x, ma10.values, color="#FFD166", linewidth=1.2, label="MA10")
        ax.plot(x, ma20.values, color="#06D6A0", linewidth=1.2, label="MA20")
        ax.plot(x, ma50.values, color="#118AB2", linewidth=1.2, label="MA50")
        ax.set_title(title, color="white", fontsize=12)
        ax.set_facecolor("#0f1117")
        ax.legend(loc="upper left", facecolor="#0f1117", edgecolor="#444", labelcolor="white", fontsize=9)
        ax.tick_params(colors="white")
        for s in ax.spines.values():
            s.set_color("#444")
        n_ticks = 8
        step = max(1, len(d) // n_ticks)
        ticks = list(range(0, len(d), step))
        ax.set_xticks(ticks)
        ax.set_xticklabels([d.index[t].strftime("%Y-%m") for t in ticks], rotation=0, fontsize=8)
        ax.set_xlim(-1, len(d))
        ax.grid(True, color="#222", linestyle="--", linewidth=0.5)
        return d

    specs = [
        ("1D", df, args.bars1d, f"{SYM} · 1D · last {args.bars1d} bars (MA10/20/50)"),
        ("1W", resample(df, "W-FRI"), args.bars1w, f"{SYM} · 1W · last {args.bars1w} bars (MA10/20/50)"),
        ("1M", resample(df, "ME"), args.bars1m, f"{SYM} · 1M · last {args.bars1m} bars (MA10/20/50)"),
    ]
    for label, d, bars, title in specs:
        fig, ax = plt.subplots(figsize=(13, 6), facecolor="#0f1117")
        used = plot_candles(ax, d, title, bars)
        out = OUT_DIR / f"_chart_{SYM.lower()}_{label.lower()}.png"
        fig.tight_layout()
        fig.savefig(out, dpi=110, facecolor="#0f1117")
        plt.close(fig)
        last3 = used.tail(3)[["open", "high", "low", "close", "volume"]]
        print(f"[{label}] last 3 bars:")
        print(last3.to_string())
        ma10v = used["close"].rolling(10).mean().iloc[-1]
        ma20v = used["close"].rolling(20).mean().iloc[-1]
        ma50v = used["close"].rolling(50).mean().iloc[-1]
        last_close = used["close"].iloc[-1]
        print(f"  MA10={ma10v:.3f}  MA20={ma20v:.3f}  MA50={ma50v:.3f}  close={last_close:.3f}  px_vs_ma20={(last_close/ma20v-1)*100:+.2f}%")
        print(f"  saved -> {out}")

if __name__ == "__main__":
    main()
