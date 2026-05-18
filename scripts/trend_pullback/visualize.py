"""Visualize a bars × angle-quantile cell. Args select which cell.

Run:
  .venv/Scripts/python.exe -m scripts.trend_pullback.visualize \
      --bars-lo 1 --bars-hi 3 --angle-lo -0.1214 --angle-hi -0.0773 \
      --label "bars1-3_q4" --title "bars 1-3 x Q4"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "crypto" / "1h"

# Plot window
PRE_BARS = 30           # bars before impulse
POST_BARS = 200         # bars after impulse (covers 168h horizon)


def filter_events(events: pd.DataFrame, bars_lo: int, bars_hi: int,
                   angle_lo: float, angle_hi: float,
                   wick_lo: float = -1.0, wick_hi: float = 1e9) -> pd.DataFrame:
    mask = (events["touched_ma10"] &
            (events["bars_to_touch_ma10"] >= bars_lo) &
            (events["bars_to_touch_ma10"] <= bars_hi) &
            (events["angle_per_bar_ma10"] > angle_lo) &
            (events["angle_per_bar_ma10"] <= angle_hi) &
            events["fwd_168h_ma10"].notna())
    if "upper_wick_pct" in events.columns:
        mask = mask & (events["upper_wick_pct"] > wick_lo) & (events["upper_wick_pct"] <= wick_hi)
    return events[mask].copy()


def add_impulse_high(events: pd.DataFrame) -> pd.DataFrame:
    events = events.copy()
    events["impulse_high"] = np.nan
    for sym, grp in events.groupby("symbol"):
        path = CACHE_DIR / f"{sym}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path).sort_values("timestamp").reset_index(drop=True)
        highs = df["high"].to_numpy()
        idx = grp["impulse_idx"].astype(int).to_numpy()
        valid = (idx >= 0) & (idx < len(highs))
        events.loc[grp.index[valid], "impulse_high"] = highs[idx[valid]]
    events["upper_wick_pct"] = (events["impulse_high"] - events["impulse_close"]) / events["impulse_close"]
    return events


def stratified_sample(events: pd.DataFrame, k_win=4, k_mid=3, k_loss=3,
                       seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ev = events.sort_values("fwd_168h_ma10").reset_index(drop=True)
    # losers: bottom 30%, mid: middle 40%, winners: top 30%
    n = len(ev)
    losers = ev.iloc[:int(n*0.3)]
    mid = ev.iloc[int(n*0.3):int(n*0.7)]
    winners = ev.iloc[int(n*0.7):]
    pick = pd.concat([
        winners.sample(n=min(k_win, len(winners)), random_state=seed),
        mid.sample(n=min(k_mid, len(mid)), random_state=seed+1),
        losers.sample(n=min(k_loss, len(losers)), random_state=seed+2),
    ]).reset_index(drop=True)
    return pick


def load_ohlcv(symbol: str) -> pd.DataFrame:
    df = pd.read_parquet(CACHE_DIR / f"{symbol}.parquet")
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def plot_event(ax, df: pd.DataFrame, event: pd.Series) -> None:
    imp_i = int(event["impulse_idx"])
    touch_i = int(event["touch_idx_ma10"]) if pd.notna(event["touch_idx_ma10"]) else None
    lo = max(0, imp_i - PRE_BARS)
    hi = min(len(df) - 1, imp_i + POST_BARS)
    sub = df.iloc[lo:hi + 1].copy()

    ma10 = sub["close"].rolling(10, min_periods=10).mean()
    ma20 = sub["close"].rolling(20, min_periods=20).mean()

    x = mdates.date2num(sub["dt"].dt.to_pydatetime())
    width = (x[1] - x[0]) * 0.7 if len(x) > 1 else 0.02
    op = sub["open"].to_numpy()
    cl = sub["close"].to_numpy()
    hi_v = sub["high"].to_numpy()
    lo_v = sub["low"].to_numpy()
    up = cl >= op
    ax.vlines(x, lo_v, hi_v, color="black", linewidth=0.5, alpha=0.6)
    ax.bar(x[up], (cl - op)[up], bottom=op[up],
           width=width, color="#26a69a", linewidth=0)
    ax.bar(x[~up], (op - cl)[~up], bottom=cl[~up],
           width=width, color="#ef5350", linewidth=0)
    # MAs
    ax.plot(x, ma10.values, color="#ffa726", linewidth=1.2, label="MA10")
    ax.plot(x, ma20.values, color="#42a5f5", linewidth=1.2, label="MA20")

    # markers
    imp_x = mdates.date2num(df["dt"].iloc[imp_i].to_pydatetime())
    ax.scatter([imp_x], [df["close"].iloc[imp_i]], color="red", s=80,
                 zorder=5, marker="^", label="impulse")
    if touch_i is not None and touch_i < len(df):
        t_x = mdates.date2num(df["dt"].iloc[touch_i].to_pydatetime())
        ax.scatter([t_x], [df["low"].iloc[touch_i]], color="blue", s=80,
                     zorder=5, marker="v", label="MA10 touch")
    # 168h marker
    end_i = imp_i + 0  # we measure from touch
    if touch_i is not None:
        end_i = touch_i + 168
        if end_i < len(df):
            e_x = mdates.date2num(df["dt"].iloc[end_i].to_pydatetime())
            ax.scatter([e_x], [df["close"].iloc[end_i]], color="green", s=60,
                         zorder=5, marker="o", label="+168h")
            ax.axhline(df["close"].iloc[touch_i], color="gray",
                        linestyle="--", linewidth=0.6, alpha=0.5)

    ax.set_title(
        f"{event['symbol']}  bars={int(event['bars_to_touch_ma10'])}, "
        f"drop={event['drop_pct_ma10']*100:+.2f}%, "
        f"angle={event['angle_per_bar_ma10']*100:+.2f}%/봉  →  "
        f"168h={event['fwd_168h_ma10']*100:+.2f}%",
        fontsize=9
    )
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.tick_params(axis="both", labelsize=7)
    ax.grid(True, alpha=0.2)
    ax.legend(loc="upper left", fontsize=6, ncol=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, required=True,
                    help="run folder containing output/events.parquet (writes PNG here too)")
    ap.add_argument("--bars-lo", type=int, required=True)
    ap.add_argument("--bars-hi", type=int, required=True)
    ap.add_argument("--angle-lo", type=float, required=True)
    ap.add_argument("--angle-hi", type=float, required=True)
    ap.add_argument("--wick-lo", type=float, default=-1.0)
    ap.add_argument("--wick-hi", type=float, default=1e9)
    ap.add_argument("--label", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--all", action="store_true", help="show all cases (not stratified 10)")
    args = ap.parse_args()

    out_dir = args.out_dir.resolve() / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "events.parquet"
    if not events_path.exists():
        print(f"events parquet not found: {events_path}")
        return 1
    events = pd.read_parquet(events_path)
    events = add_impulse_high(events)
    events["touch_idx_ma10"] = (events["impulse_idx"] + events["bars_to_touch_ma10"])

    pool = filter_events(events, args.bars_lo, args.bars_hi,
                         args.angle_lo, args.angle_hi,
                         args.wick_lo, args.wick_hi)
    n_pool = len(pool)
    mean_168 = pool["fwd_168h_ma10"].mean() * 100
    med_168 = pool["fwd_168h_ma10"].median() * 100
    win_168 = (pool["fwd_168h_ma10"] > 0).mean() * 100
    print(f"{args.title} pool: n={n_pool}, mean={mean_168:+.2f}%, med={med_168:+.2f}%, win={win_168:.0f}%")

    if args.all:
        pick = pool.sort_values("fwd_168h_ma10", ascending=False).reset_index(drop=True)
    else:
        pick = stratified_sample(pool)
    print(f"plotting {len(pick)} cases")

    # dynamic grid
    n = len(pick)
    ncols = 3 if n > 12 else 2
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 7.5, nrows * 3.2))
    axes = np.array(axes).flatten()
    for k, (_, ev) in enumerate(pick.iterrows()):
        df = load_ohlcv(ev["symbol"])
        plot_event(axes[k], df, ev)
    for k in range(len(pick), len(axes)):
        axes[k].axis("off")

    fig.suptitle(
        f"{args.title} — ALL {n_pool} cases (sorted by 168h)\n"
        f"mean 168h={mean_168:+.2f}%, median={med_168:+.2f}%, win={win_168:.0f}%",
        fontsize=12, y=0.995
    )
    fig.tight_layout(rect=(0, 0, 1, 0.99))
    out = out_dir / f"{args.label}_visualize.png"
    fig.savefig(out, dpi=100, bbox_inches="tight")
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
