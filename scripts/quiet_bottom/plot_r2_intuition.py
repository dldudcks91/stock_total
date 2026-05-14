"""R² 의미를 시각으로 보여주기 — 다양한 가격 패턴의 R² 값.

6가지 가공 패턴 + 실제 종목 케이스 2개.
"""
from __future__ import annotations
import sys, numpy as np, pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.quiet_bottom.count_slope_turn_signals import load_stock_weekly, load_crypto_weekly


def linear_r2(y):
    t = np.arange(len(y), dtype=float)
    coef = np.polyfit(t, y, 1)
    y_hat = np.polyval(coef, t)
    ss_res = ((y - y_hat) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    return 1 - ss_res / ss_tot if ss_tot > 0 else 0.0


def main():
    np.random.seed(0)
    n = 52
    t = np.arange(n)

    # 6가지 패턴
    patterns = []
    # 1) 직선 하락 (R² 높음)
    y = 100 - t * 1.0 + np.random.normal(0, 1, n)
    patterns.append(("Linear decline (steady drop)", y, "거친 차트 — 일관된 하락"))
    # 2) 직선 상승
    y = 100 + t * 1.5 + np.random.normal(0, 2, n)
    patterns.append(("Linear rise (steady up)", y, "일관된 상승"))
    # 3) U자 (조용한 바닥) — 통과
    y = 100 - 30 * np.exp(-((t - 25) ** 2) / 200) * 0  # 비활성
    y = 100 + 0.06 * (t - 26) ** 2 + np.random.normal(0, 2, n)
    patterns.append(("U-shape (quiet bottom)", y, "조용한 바닥 — 통과"))
    # 4) V자 폭락 (R² 중간)
    y = 100 - np.where(t < 26, t * 2, (52 - t) * 1.5) + np.random.normal(0, 2, n)
    patterns.append(("V-spike (sharp drop+bounce)", y, "V자 폭락"))
    # 5) 박스권 횡보
    y = 50 + 8 * np.sin(t * 0.8) + np.random.normal(0, 2, n)
    patterns.append(("Sideways box", y, "박스권 횡보"))
    # 6) 침잠 후 회복 (실제 우리가 원하는 패턴)
    y = 100 - 50 * (1 - np.exp(-t / 10)) * (t < 26) - 50 * np.exp(-(t - 25) / 30) * (t >= 26) + np.random.normal(0, 2, n)
    patterns.append(("Deep dive + bottom + recover", y, "푹 잠긴 후 회복 — 통과"))

    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    axes = axes.flatten()
    for ax, (label, y, hint) in zip(axes, patterns):
        log_y = np.log(np.maximum(y, 0.01))
        r2 = linear_r2(log_y)
        coef = np.polyfit(t, log_y, 1)
        line = np.exp(np.polyval(coef, t))
        ax.plot(t, y, "o-", color="steelblue", lw=1.2, ms=3, label="price")
        ax.plot(t, line, "--", color="red", lw=1.6, label="linear fit (log)")
        passed = r2 <= 0.50
        verdict = "PASS (조건 통과)" if passed else "FAIL (거름)"
        color = "darkgreen" if passed else "darkred"
        ax.set_title(f"{label}\nR² = {r2:.3f}  →  {verdict}", color=color, weight="bold", fontsize=11)
        ax.legend(fontsize=9, loc="best")
        ax.grid(alpha=0.3)
        ax.set_xlabel("week")
    fig.suptitle("R² of linear fit on log-price (window=52w)  —  R² ≤ 0.50 통과", fontsize=14, weight="bold")
    fig.tight_layout()
    out = ROOT / "scripts/out/r2_intuition.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
