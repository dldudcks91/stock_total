"""곡률 fit 시각 검증 — 다양한 케이스의 MA20에 2차 fit 후 R² 표시.

좋은 U자 (높은 R²) / V자 떡상 (낮은 R²) / 직선 / 등을 한눈에 보기.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.count_slope_turn_signals import load_crypto_weekly, load_stock_weekly  # noqa: E402

# 보여줄 케이스 — (label, asset, file, entry_date)
CASES = [
    ("ATOMUSDT 2024-11-25 (V-spike leak)",          "crypto", "data/cache/crypto/1h/ATOMUSDT.parquet", "2024-11-25"),
    ("SANDUSDT 2024-11-11 (clean U-curl)",          "crypto", "data/cache/crypto/1h/SANDUSDT.parquet", "2024-11-11"),
    ("CRVUSDT 2024-11-25 (strong U, best case)",    "crypto", "data/cache/crypto/1h/CRVUSDT.parquet",  "2024-11-25"),
    ("KR 011790 (SKC) 2023-11-17",                  "kr",     "data/cache/kr/011790.parquet",          "2023-11-17"),
    ("KR 377300 (Kakao Pay) 2025-05-23",            "kr",     "data/cache/kr/377300.parquet",          "2025-05-23"),
    ("US TEAM (Atlassian) 2023-07-07",              "us",     "data/cache/us/TEAM.parquet",            "2023-07-07"),
]

WINDOW = 8  # 곡률 fit 윈도우 (curl_window)


def fit_curl(ma_vals: np.ndarray):
    """ma_vals (length=WINDOW) → (a, R², y_hat)"""
    t = np.arange(len(ma_vals), dtype=float)
    coef = np.polyfit(t, ma_vals, 2)
    a = coef[0]
    y_hat = np.polyval(coef, t)
    ss_res = ((ma_vals - y_hat) ** 2).sum()
    ss_tot = ((ma_vals - ma_vals.mean()) ** 2).sum()
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return a, r2, y_hat


def main():
    fig, axes = plt.subplots(3, 2, figsize=(22, 16))
    axes = axes.flatten()
    plt.rcParams.update({"font.size": 12})

    for i, (label, asset, fp, entry_str) in enumerate(CASES):
        ax = axes[i]
        path = ROOT / fp
        if not path.exists():
            ax.set_title(f"{label}\n(file missing)")
            continue
        if asset == "crypto":
            df_w = load_crypto_weekly(path)
        else:
            df_w = load_stock_weekly(path)
        df_w = df_w.sort_index()
        entry_dt = pd.Timestamp(entry_str)
        # 가장 가까운 봉
        idx = df_w.index.get_indexer([entry_dt], method="nearest")[0]
        # 표시 범위: 진입봉 기준 -12주 ~ +6주 = 18봉
        lo = max(0, idx - 12)
        hi = min(len(df_w), idx + 7)
        seg = df_w.iloc[lo:hi]
        # MA20
        ma20 = df_w["close"].rolling(20).mean()
        ma10 = df_w["close"].rolling(10).mean()

        # fit window: 진입봉 직전 WINDOW봉 [idx-WINDOW+1 ... idx]
        fit_lo = idx - WINDOW + 1
        fit_hi = idx + 1
        fit_x = df_w.index[fit_lo:fit_hi]
        fit_w = ma20.iloc[fit_lo:fit_hi].values
        a, r2, y_hat = fit_curl(fit_w)
        # MA10도 fit
        fit_w10 = ma10.iloc[fit_lo:fit_hi].values
        a10, r2_10, _ = fit_curl(fit_w10)

        # 가격
        ax.plot(seg.index, seg["close"], color="#888", lw=1, label="close")
        # MA10, MA20
        ax.plot(seg.index, ma10.loc[seg.index], color="orange", lw=1.4, label="MA10")
        ax.plot(seg.index, ma20.loc[seg.index], color="royalblue", lw=1.8, label="MA20")
        # fit window highlight
        ax.axvspan(fit_x[0], fit_x[-1], color="yellow", alpha=0.15, label="fit window")
        # 2차 fit 곡선
        ax.plot(fit_x, y_hat, color="red", ls="--", lw=2,
                label=f"poly2 fit (a={a:.3g}, R²={r2:.2f})")
        # entry marker
        ax.axvline(df_w.index[idx], color="green", ls=":", lw=1.5, alpha=0.7)
        ax.annotate("entry", xy=(df_w.index[idx], seg["close"].max()),
                    xytext=(5, -5), textcoords="offset points",
                    fontsize=9, color="green", weight="bold")

        # 통과 여부 표시
        passed_ma20 = (a > 0) and (r2 >= 0.80)
        passed_ma10 = (a10 > 0) and (r2_10 >= 0.80)
        verdict = "PASS" if (passed_ma20 and passed_ma10) else "FAIL"
        v_color = "darkgreen" if verdict == "PASS" else "darkred"
        title = f"{label}\nMA20: a={a:.3g}, R²={r2:.2f}  |  MA10: a={a10:.3g}, R²={r2_10:.2f}  → {verdict}"
        ax.set_title(title, fontsize=14, color=v_color, weight="bold")
        ax.legend(loc="upper left", fontsize=11)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.grid(alpha=0.3)
        for tick in ax.get_xticklabels():
            tick.set_rotation(30)

    fig.suptitle(f"MA20 quadratic-fit curl check  (window={WINDOW} weeks, a>0 AND R²≥0.80)",
                 fontsize=18, weight="bold")
    fig.tight_layout()
    out = ROOT / "scripts" / "out" / "curl_examples.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
