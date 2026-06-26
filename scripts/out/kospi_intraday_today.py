"""KOSPI 오늘 분봉 + 1시간 단위 투자자별 순매수 차트.

데이터 소스 2개:
  1. 가격: api.stock.naver.com/chart/domestic/index/KOSPI/minute (분봉)
  2. 투자자별 누적 순매수: finance.daum.net/api/investor/KOSPI/times (분 단위 누적)

투자자별은 누적값이므로 1시간 시점 차분으로 구간별 순매수 환산.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ROOT = Path(__file__).resolve().parents[2]


def fetch_kospi_minute() -> pd.DataFrame:
    url = "https://api.stock.naver.com/chart/domestic/index/KOSPI/minute"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=15)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    df["dt"] = pd.to_datetime(df["localDateTime"], format="%Y%m%d%H%M%S")
    df = df.rename(columns={
        "currentPrice": "close", "openPrice": "open",
        "highPrice": "high", "lowPrice": "low",
        "accumulatedTradingVolume": "volume_cum",
    })
    df["volume"] = df["volume_cum"].diff().fillna(df["volume_cum"]).clip(lower=0)
    return df[["dt", "open", "high", "low", "close", "volume"]]


def fetch_daum_investor_times(market: str = "KOSPI") -> pd.DataFrame:
    """누적 투자자별 순매수 (분 단위). KOSPI/KOSDAQ."""
    url = f"https://finance.daum.net/api/investor/{market}/times?perPage=1000"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": f"https://finance.daum.net/domestic/investors/{market}",
    }
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    rows = r.json()["data"]
    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["date"])
    df = df.rename(columns={
        "individualStraightPurchasePrice": "indiv_cum",
        "foreignStraightPurchasePrice": "foreign_cum",
        "institutionStraightPurchasePrice": "inst_cum",
    })
    df = df.sort_values("dt").reset_index(drop=True)
    return df[["dt", "indiv_cum", "foreign_cum", "inst_cum"]]


def hourly_investor_diff(df_inv: pd.DataFrame) -> pd.DataFrame:
    """09:00 시점 누적=0 으로 가정하고, 1시간 단위 누적값의 차분 = 시간대 순매수.

    실제 누적은 09:00 기준 시작이므로 09:00 직전 값은 0으로 prepend.
    """
    # 장 시간만 (09:00 ~ 15:30)
    open_dt = df_inv["dt"].iloc[0].normalize() + pd.Timedelta(hours=9)
    close_dt = df_inv["dt"].iloc[0].normalize() + pd.Timedelta(hours=15, minutes=30)
    df = df_inv[(df_inv["dt"] >= open_dt) & (df_inv["dt"] <= close_dt + pd.Timedelta(hours=3))].copy()
    # 0 prepend (09:00 직전 = 0)
    zero = pd.DataFrame({"dt": [open_dt - pd.Timedelta(seconds=1)],
                          "indiv_cum": [0.0], "foreign_cum": [0.0], "inst_cum": [0.0]})
    df = pd.concat([zero, df], ignore_index=True).sort_values("dt").reset_index(drop=True)
    # 1시간 단위 cumulative 의 마지막값 (asof)
    hours = pd.date_range(open_dt, close_dt + pd.Timedelta(hours=1), freq="1h")
    rows = []
    for h in hours:
        # h 이하 최신값
        prev = df[df["dt"] <= h].iloc[-1] if not df[df["dt"] <= h].empty else None
        if prev is None:
            continue
        rows.append({"hour": h, "indiv_cum": prev["indiv_cum"],
                     "foreign_cum": prev["foreign_cum"], "inst_cum": prev["inst_cum"]})
    out = pd.DataFrame(rows)
    out["indiv"] = out["indiv_cum"].diff().fillna(out["indiv_cum"]) / 1e8  # 억원
    out["foreign"] = out["foreign_cum"].diff().fillna(out["foreign_cum"]) / 1e8
    out["inst"] = out["inst_cum"].diff().fillna(out["inst_cum"]) / 1e8
    # 첫 행은 09:00 시점 = 0 으로 시작했으므로 의미 X — 라벨 단순화 위해 hour 를 [09,10,...] 로
    return out


def make_chart(df_min: pd.DataFrame, df_hour_inv: pd.DataFrame, out_path: Path) -> None:
    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), sharex=False,
                                    gridspec_kw={"height_ratios": [2, 1.4]})

    # --- 위: KOSPI 분봉 ---
    ax1.plot(df_min["dt"], df_min["close"], color="#2563eb", linewidth=1.2)
    open0 = df_min["close"].iloc[0]
    ax1.axhline(open0, color="gray", linestyle="--", linewidth=0.8, alpha=0.6,
                  label=f"시초가 {open0:.2f}")
    ax1.fill_between(df_min["dt"], df_min["close"], open0,
                       where=df_min["close"] < open0, color="#ef4444", alpha=0.12)
    ax1.fill_between(df_min["dt"], df_min["close"], open0,
                       where=df_min["close"] >= open0, color="#10b981", alpha=0.12)
    ax1.set_ylabel("KOSPI 지수", fontsize=11)
    pct = (df_min["close"].iloc[-1] / df_min["close"].iloc[0] - 1) * 100
    title = (f"KOSPI 2026-06-08 — open {df_min['close'].iloc[0]:.2f} → "
             f"close {df_min['close'].iloc[-1]:.2f} ({pct:+.2f}%, 전일대비 −8.29%)")
    ax1.set_title(title, fontsize=13, fontweight="bold")
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="upper right", fontsize=9)
    ax1.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    # --- 아래: 1시간 단위 투자자별 순매수 (개인/외인/기관) ---
    # 09:00 ~ 15:30 의미 있는 시간만 (09:00~10:00 구간 = 10:00 행)
    df_h = df_hour_inv.iloc[1:].copy()  # 첫 09:00 행 skip (그 행은 시작점, 의미 없음)
    labels = df_h["hour"].dt.strftime("%H:%M").tolist()
    n = len(df_h)
    xs = list(range(n))
    width = 0.27
    ax2.bar([x - width for x in xs], df_h["indiv"], width=width, color="#fb923c",
              label="개인", edgecolor="black", linewidth=0.3)
    ax2.bar(xs, df_h["foreign"], width=width, color="#3b82f6",
              label="외국인", edgecolor="black", linewidth=0.3)
    ax2.bar([x + width for x in xs], df_h["inst"], width=width, color="#10b981",
              label="기관", edgecolor="black", linewidth=0.3)
    ax2.axhline(0, color="black", linewidth=0.5)
    ax2.set_xticks(xs)
    ax2.set_xticklabels(labels)
    ax2.set_ylabel("순매수 (억원, 1시간 구간)", fontsize=11)
    ax2.set_xlabel("시각 (구간 종료점)", fontsize=11)
    ax2.set_title("KOSPI 시간대별 투자자 순매수 — Daum 출처 (09:00→10:00 = 10:00 막대)", fontsize=11)
    ax2.legend(loc="upper right", fontsize=10)
    ax2.grid(True, alpha=0.3, axis="y")

    # 값 라벨 표시
    for i, (ind, fore, ins) in enumerate(zip(df_h["indiv"], df_h["foreign"], df_h["inst"])):
        for off, v, color in [(-width, ind, "#fb923c"), (0, fore, "#3b82f6"), (width, ins, "#10b981")]:
            va = "bottom" if v >= 0 else "top"
            ax2.text(i + off, v, f"{v:+.0f}", ha="center", va=va, fontsize=7, color="#000")

    plt.tight_layout()
    plt.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    out_dir = ROOT / "scripts" / "out"

    print("[1/4] fetching KOSPI minute bars ...")
    df_min = fetch_kospi_minute()
    print(f"      {len(df_min)} bars, {df_min['dt'].iloc[0]} ~ {df_min['dt'].iloc[-1]}")

    print("[2/4] fetching Daum investor times (cum) ...")
    df_inv = fetch_daum_investor_times("KOSPI")
    print(f"      {len(df_inv)} rows, {df_inv['dt'].iloc[0]} ~ {df_inv['dt'].iloc[-1]}")
    print(f"      마지막 누적: 개인={df_inv['indiv_cum'].iloc[-1]/1e8:+,.0f}억 "
          f"외인={df_inv['foreign_cum'].iloc[-1]/1e8:+,.0f}억 "
          f"기관={df_inv['inst_cum'].iloc[-1]/1e8:+,.0f}억")

    print("[3/4] computing 1h diff ...")
    df_hour_inv = hourly_investor_diff(df_inv)
    print(df_hour_inv[["hour", "indiv", "foreign", "inst"]].to_string(index=False))

    print("[4/4] rendering chart ...")
    today = df_min["dt"].iloc[0].strftime("%Y%m%d")
    out_path = out_dir / f"kospi_intraday_investor_{today}.png"
    make_chart(df_min, df_hour_inv, out_path)
    print(f"      saved: {out_path}")


if __name__ == "__main__":
    main()
