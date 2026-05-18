"""scripts/out/optimize/*_grid.csv 파일들을 모아 _all_grids.csv 와 best-of 표 생성.

산출:
  scripts/out/optimize/_all_grids.csv (모든 그리드 행 concat)
  scripts/out/optimize/_best_per_combo.csv (asset×strategy×interval 별 Sharpe 최고 1개)
  스토아우트에 Markdown 표 (SUMMARY.md 에 붙여넣기용)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "scripts" / "out" / "optimize"

# 시뇨할 평가 기준
MIN_N = 20  # n_trades >= 20 만 유효 (작은 표본 제외)


def load_all() -> pd.DataFrame:
    rows = []
    for p in sorted(OUT_DIR.glob("*_grid.csv")):
        if p.name.startswith("_"):
            continue
        try:
            d = pd.read_csv(p)
        except Exception as e:
            print(f"skip {p.name}: {e}", file=sys.stderr)
            continue
        rows.append(d)
    if not rows:
        return pd.DataFrame()
    df = pd.concat(rows, ignore_index=True)
    return df


def best_per_combo(df: pd.DataFrame) -> pd.DataFrame:
    """asset×strategy×interval 별 Sharpe 가장 높은 (th, rule) 1개씩."""
    valid = df[df["n"] >= MIN_N].copy()
    if valid.empty:
        return pd.DataFrame()
    valid = valid.sort_values("Sharpe_ann", ascending=False)
    best = valid.groupby(["asset", "strategy", "interval"], as_index=False).first()
    cols = ["asset", "strategy", "interval", "score_th", "rule",
            "n", "win%", "mean%", "median%", "MDD%", "Sharpe_ann", "PF", "held"]
    return best[cols].sort_values(["asset", "strategy", "interval"]).reset_index(drop=True)


def render_md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "(no data)"
    headers = ["asset", "strategy", "interval", "score_th", "rule",
               "n", "win%", "mean%", "MDD%", "Sharpe_ann", "PF"]
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    for _, r in df.iterrows():
        cells = []
        for h in headers:
            v = r[h]
            if isinstance(v, float):
                cells.append(f"{v:.2f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def recommend_threshold(df: pd.DataFrame) -> dict:
    """알림 시스템용 자산별 권장 threshold.

    기준:
      - quiet_bottom 은 binary (threshold 무관). 자산별 Sharpe 가 가장 좋은 인터벌 / 청산룰 추천.
      - trend_chase/trend_pullback 은 (interval, threshold, rule) 의 Sharpe 우선,
        단 n >= 30 인 셀에서.
      - 자산 종합 권장 threshold: 3 전략 중 Sharpe 가장 높은 셀의 threshold.
        단 quiet_bottom 은 binary 이라 score_th 가 무의미하므로 trend_* 만 본다.
    """
    rec = {}
    valid = df[(df["n"] >= MIN_N) & (df["strategy"] != "quiet_bottom")].copy()
    if valid.empty:
        return rec
    for asset, sub in valid.groupby("asset"):
        sub2 = sub.sort_values("Sharpe_ann", ascending=False).head(1)
        if not sub2.empty:
            r = sub2.iloc[0]
            rec[asset] = {
                "score_th": r["score_th"],
                "strategy": r["strategy"],
                "interval": r["interval"],
                "rule": r["rule"],
                "Sharpe_ann": r["Sharpe_ann"],
                "n": int(r["n"]),
            }
    return rec


def main():
    df = load_all()
    if df.empty:
        print("no _grid.csv files yet")
        return 1
    all_csv = OUT_DIR / "_all_grids.csv"
    df.to_csv(all_csv, index=False, encoding="utf-8-sig")
    print(f"saved: {all_csv}  rows={len(df)}")

    best = best_per_combo(df)
    best_csv = OUT_DIR / "_best_per_combo.csv"
    best.to_csv(best_csv, index=False, encoding="utf-8-sig")
    print(f"saved: {best_csv}  rows={len(best)}\n")

    print("## 자산×전략×인터벌 최고 (Sharpe 기준, n>={})\n".format(MIN_N))
    print(render_md_table(best))

    print("\n## 알림 권장 threshold (trend_* 기준)\n")
    rec = recommend_threshold(df)
    for a, v in rec.items():
        print(f"- {a}: score>={v['score_th']} ({v['strategy']} {v['interval']}, "
              f"{v['rule']}, Sharpe={v['Sharpe_ann']:.2f}, n={v['n']})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
