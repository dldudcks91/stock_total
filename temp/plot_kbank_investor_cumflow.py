"""케이뱅크 상장 후 투자자별 누적 순매수 추이 그래프.

산출: scripts/out/kbank_investor_cumflow.png
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from temp.fetch_krx_pension_top import krx_login, UA, DATA_URL, DATA_REFERER  # noqa

OUT = ROOT / "scripts" / "out" / "kbank_investor_cumflow.png"
ISIN = "KR7279570006"
TICKER = "279570"
FR = "20260305"
TO = "20260623"

# MDCSTAT02303 TRDVAL 매핑 (검증된 매핑)
COLS = {
    "TRDVAL1": "금융투자", "TRDVAL2": "보험", "TRDVAL3": "투신",
    "TRDVAL4": "사모", "TRDVAL5": "은행", "TRDVAL6": "기타금융",
    "TRDVAL7": "연기금", "TRDVAL8": "기타법인",
    "TRDVAL9": "개인", "TRDVAL10": "외국인_본인", "TRDVAL11": "기타외국인",
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    s = krx_login(os.getenv("KRX_ID"), os.getenv("KRX_PW"))
    if s is None:
        sys.exit(1)

    r = s.post(DATA_URL, data={
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02303",
        "strtDd": FR, "endDd": TO, "isuCd": ISIN,
        "inqTpCd": "2", "trdVolVal": "2", "askBid": "3",
    }, headers={"User-Agent": UA, "Referer": DATA_REFERER,
                "X-Requested-With": "XMLHttpRequest"}, timeout=30)
    rows = r.json().get("output", [])
    if not rows:
        print("결과 없음", file=sys.stderr)
        sys.exit(2)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["TRD_DD"].str.replace("/", "-"))
    for c in COLS:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""),
                              errors="coerce").fillna(0)
    df = df.sort_values("date").reset_index(drop=True)
    # 컬럼 rename
    df = df.rename(columns=COLS)
    # 합성 컬럼
    df["외국인"] = df["외국인_본인"] + df["기타외국인"]
    df["기관"] = (df["금융투자"] + df["보험"] + df["투신"] + df["사모"]
                + df["은행"] + df["기타금융"] + df["연기금"])

    # 누적 (단위: 억원)
    plot_cols = ["개인", "외국인", "기관", "연기금", "기타법인"]
    cum = df.set_index("date")[plot_cols].cumsum() / 1e8

    # ===== 그래프 =====
    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=130)

    palette = {
        "개인": "#d62728",
        "외국인": "#1f77b4",
        "기관": "#2ca02c",
        "연기금": "#9467bd",
        "기타법인": "#7f7f7f",
    }
    for col in plot_cols:
        ax.plot(cum.index, cum[col], label=col, color=palette[col],
                linewidth=2.0 if col in ("개인", "기관", "외국인")
                else 1.6,
                linestyle="--" if col == "연기금" else "-")

    ax.axhline(0, color="black", linewidth=0.5, alpha=0.5)
    ax.set_title(f"케이뱅크 ({TICKER}) 상장 후 투자자별 누적 순매수\n"
                 f"{cum.index.min().date()} ~ {cum.index.max().date()} "
                 f"({len(cum)}영업일)", fontsize=13)
    ax.set_ylabel("누적 순매수 (억원)", fontsize=11)
    ax.set_xlabel("일자", fontsize=11)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_minor_locator(mdates.WeekdayLocator(byweekday=0))
    ax.grid(which="major", alpha=0.4)
    ax.grid(which="minor", alpha=0.15, linestyle=":")
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5),
              frameon=False, fontsize=11)
    # 마지막 시점 값 라벨
    last = cum.iloc[-1]
    for col in plot_cols:
        ax.annotate(f"{last[col]:+,.0f}억", xy=(cum.index[-1], last[col]),
                    xytext=(6, 0), textcoords="offset points",
                    fontsize=9, color=palette[col], va="center")
    fig.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, bbox_inches="tight")
    print(f"saved: {OUT}")

    # 표 요약
    print("\n[최종 누적 순매수, 억원]")
    print(last.map(lambda v: f"{v:+,.0f}").to_string())


if __name__ == "__main__":
    main()
