"""KOSPI vs ex-4 주단위 차트 (2025-05 ~ 2026-06).

상단: KOSPI (좌축) + ex-4 KOSPI (우축) 듀얼 라인
하단: 4종 시총 비중 (%)
주요 swing point 마커.
"""
import sys
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import FinanceDataReader as fdr

# 한글 폰트
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

sys.stdout.reconfigure(encoding="utf-8")

EXCLUDE = ["000660", "005930", "402340", "009150"]
START, END = "2025-05-01", "2026-06-30"
CACHE = Path("data/cache/kr")
OUT = Path("scripts/out/kospi_ex4_weekly.png")

snap = pd.read_parquet(CACHE / "_live_snapshot.parquet")
snap = snap[snap["marketValue"].notna() & (snap["closePrice"] > 0)].copy()
snap["shares"] = snap["marketValue"] / snap["closePrice"]
shares = snap.set_index("itemCode")["shares"]

closes = {}
for p in CACHE.glob("*.parquet"):
    if p.stem.startswith("_") or p.stem not in shares.index:
        continue
    df = pd.read_parquet(p)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = df[(df.index >= START) & (df.index <= END)]
    if not df.empty:
        closes[p.stem] = df["Close"]
closes_df = pd.DataFrame(closes).sort_index()
mcap = closes_df.mul(shares.reindex(closes_df.columns), axis=1)

total_4 = mcap[EXCLUDE].sum(axis=1)
total_all = mcap.sum(axis=1)
w4 = total_4 / total_all

kospi = fdr.DataReader("KS11", START, END)
kospi.index = pd.to_datetime(kospi.index).tz_localize(None)
kospi_close = kospi["Close"].reindex(total_all.index).ffill()

ex4 = kospi_close * (1 - w4)

# 주 단위 (주말 = 마지막 거래일)
weekly_idx = total_all.groupby([total_all.index.isocalendar().year,
                                total_all.index.isocalendar().week]).apply(lambda s: s.index[-1])
weekly_idx = pd.DatetimeIndex(weekly_idx.values)

kospi_w = kospi_close.loc[weekly_idx]
ex4_w = ex4.loc[weekly_idx]
w4_w = w4.loc[weekly_idx]

# === 차트 ===
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), height_ratios=[3, 1], sharex=True)

# 상단: KOSPI (좌축) + ex-4 (우축)
color_k = "#1f77b4"
color_e = "#ff7f0e"

ax1.plot(weekly_idx, kospi_w, color=color_k, linewidth=2, marker="o", markersize=3, label="KOSPI (좌축)")
ax1.set_ylabel("KOSPI", color=color_k, fontsize=11)
ax1.tick_params(axis="y", labelcolor=color_k)
ax1.grid(True, alpha=0.3)

ax1r = ax1.twinx()
ax1r.plot(weekly_idx, ex4_w, color=color_e, linewidth=2, marker="s", markersize=3, label="ex-4 KOSPI (우축)")
ax1r.set_ylabel("ex-4 KOSPI (4종 제외)", color=color_e, fontsize=11)
ax1r.tick_params(axis="y", labelcolor=color_e)

# 주요 swing 마커
swing_points = [
    ("2026-02-27", ex4_w, "ex-4 봉우리1\n3,627", color_e, ax1r),
    ("2026-05-08", ex4_w, "ex-4 봉우리2 (피크)\n3,852", color_e, ax1r),
    ("2026-06-19", kospi_w, "KOSPI 피크\n9,052", color_k, ax1),
    ("2026-06-24", kospi_w, "현재\nKOSPI 8,471\nex-4 3,397", "black", ax1),
]
for date_str, series, label, color, ax in swing_points:
    d = pd.Timestamp(date_str)
    # 가장 가까운 weekly idx
    closest = weekly_idx[weekly_idx.get_indexer([d], method="nearest")[0]]
    y = series.loc[closest]
    ax.plot(closest, y, "o", color=color, markersize=10, markeredgecolor="black", markeredgewidth=1.5, zorder=5)
    ax.annotate(label, xy=(closest, y), xytext=(10, 15), textcoords="offset points",
                fontsize=9, color=color, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=color, alpha=0.9))

# 2월 봉우리1 수평선 (ex-4 우축 기준)
feb_peak_ex4 = ex4_w.loc[pd.Timestamp("2026-02-27")] if pd.Timestamp("2026-02-27") in weekly_idx else ex4_w.loc[weekly_idx[weekly_idx.get_indexer([pd.Timestamp("2026-02-27")], method="nearest")[0]]]
ax1r.axhline(y=feb_peak_ex4, color=color_e, linestyle="--", linewidth=0.8, alpha=0.5)
ax1r.text(weekly_idx[0], feb_peak_ex4, f"  2월 고점 {feb_peak_ex4:.0f}", fontsize=8, color=color_e, va="bottom")

# 4월 골 수평선
apr_low_ex4 = ex4_w.loc[weekly_idx[weekly_idx.get_indexer([pd.Timestamp("2026-04-03")], method="nearest")[0]]]
ax1r.axhline(y=apr_low_ex4, color="red", linestyle="--", linewidth=0.8, alpha=0.5)
ax1r.text(weekly_idx[0], apr_low_ex4, f"  3~4월 골 {apr_low_ex4:.0f} (추세확정 트리거)", fontsize=8, color="red", va="bottom")

# 범례
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax1r.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=10)
ax1.set_title("KOSPI vs ex-4 KOSPI (주단위, 2025-05 ~ 2026-06)", fontsize=13, fontweight="bold")

# 하단: 4종 비중
ax2.fill_between(weekly_idx, w4_w * 100, color="gray", alpha=0.4)
ax2.plot(weekly_idx, w4_w * 100, color="dimgray", linewidth=1.5)
ax2.set_ylabel("4종 시총 비중 (%)", fontsize=10)
ax2.set_xlabel("주말일")
ax2.grid(True, alpha=0.3)
ax2.axhline(y=50, color="red", linestyle=":", linewidth=0.8, alpha=0.6)
ax2.text(weekly_idx[0], 50, " 50% line", fontsize=8, color="red", va="bottom")

# 주요 수치 표기
ax2.annotate(f"23% → 60%", xy=(weekly_idx[-1], w4_w.iloc[-1] * 100),
             xytext=(-90, -15), textcoords="offset points", fontsize=9, color="dimgray", fontweight="bold")

# x축 포맷
ax2.xaxis.set_major_locator(mdates.MonthLocator())
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
fig.autofmt_xdate()

plt.tight_layout()
OUT.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(OUT, dpi=120, bbox_inches="tight")
print(f"[ok] saved -> {OUT.resolve()}")
