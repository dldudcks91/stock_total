"""Cycle 2 — best_exits.md + heatmap.md 생성.

Reads exit_grid_*.csv (per-combo) and produces:
  - best_exits.md — 조합별 최적 (trail, TP, hold) 권장 + IS/OOS Sharpe + n
  - heatmap.md — trail × TP heatmap (조합별, OOS Sharpe 값)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
CYCLE2 = ROOT / "scripts" / "out" / "optimize" / "cycle_2"


def fmt_tp(v) -> str:
    if pd.isna(v) or v is None:
        return "None"
    return f"{int(round(float(v) * 100))}"


def fmt_trail(v) -> str:
    return f"{int(round(float(v) * 100))}"


def best_exits_for(df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    """Best by OOS Sharpe, requiring OOS_n >= max(20, 0.1 * max OOS_n)."""
    if df.empty:
        return df
    max_oos = int(df["OOS_n"].max())
    floor = max(20, int(0.1 * max_oos))
    elig = df[df["OOS_n"] >= floor].copy()
    if elig.empty:
        elig = df.copy()
    elig = elig.sort_values("OOS_Sharpe", ascending=False).head(top_n)
    return elig


def heatmap_oos_table(df: pd.DataFrame, hold: int) -> str:
    sub = df[df["hold"] == hold].copy()
    if sub.empty:
        return f"(no data for hold={hold})"
    # Use a string TP key so 'None' sorts after numbers
    tps = list(dict.fromkeys(sub["tp"].tolist()))
    # Ensure deterministic order
    def tp_key(v):
        return (1, 0) if pd.isna(v) or v is None else (0, float(v))
    tps_sorted = sorted(tps, key=tp_key)
    trails_sorted = sorted(sub["trail"].unique())
    header = "| trail \\ TP |" + "".join(f" TP{fmt_tp(tp)} |" for tp in tps_sorted)
    sep = "|---|" + "---|" * len(tps_sorted)
    lines = [header, sep]
    for tr in trails_sorted:
        row = [f"| **{fmt_trail(tr)}%** |"]
        for tp in tps_sorted:
            cell = sub[(sub["trail"] == tr) & (
                (sub["tp"].isna() & (tp is None or pd.isna(tp))) |
                (sub["tp"] == tp))]
            if cell.empty:
                row.append(" – |")
            else:
                v = float(cell["OOS_Sharpe"].iloc[0])
                n = int(cell["OOS_n"].iloc[0])
                row.append(f" {v:+.2f} (n={n}) |")
        lines.append("".join(row))
    return "\n".join(lines)


def best_row_line(row: pd.Series) -> str:
    tp = "None" if pd.isna(row.get("tp")) else f"{fmt_tp(row['tp'])}%"
    return (f"trail={fmt_trail(row['trail'])}% / TP={tp} / hold={int(row['hold'])} → "
            f"OOS Sharpe **{row['OOS_Sharpe']:+.2f}** "
            f"(IS Sharpe {row['IS_Sharpe']:+.2f}, "
            f"OOS n={int(row['OOS_n'])}, OOS win {row['OOS_win%']:.1f}%, "
            f"OOS mean {row['OOS_mean%']:+.2f}%, decay {row.get('Sharpe_decay')})")


def main():
    # Find all per-combo files
    csvs = sorted(CYCLE2.glob("exit_grid_*_1d.csv")) + \
        sorted(CYCLE2.glob("exit_grid_*_1w.csv"))
    if not csvs:
        # fallback to master
        master = CYCLE2 / "exit_grid_all.csv"
        if not master.exists():
            print("no per-combo csvs found", file=sys.stderr)
            return 1
        all_df = pd.read_csv(master)
    else:
        all_df = pd.concat([pd.read_csv(p) for p in csvs], ignore_index=True)

    # best_exits.md
    best_lines = ["# Cycle 2 — 조합별 최적 청산 룰\n",
                  "선정 기준: OOS Sharpe 최대 (OOS_n ≥ max(20, 10% of max OOS_n) 필터).\n",
                  "각 조합 Top 5 + best 권장.\n"]
    combos = (all_df[["asset", "strategy", "interval", "score_th"]]
              .drop_duplicates()
              .sort_values(["asset", "strategy", "interval"])
              .to_records(index=False))

    best_rows: List[dict] = []
    for asset, strategy, interval, score_th in combos:
        sub = all_df[(all_df["asset"] == asset) &
                     (all_df["strategy"] == strategy) &
                     (all_df["interval"] == interval) &
                     (all_df["score_th"].astype(str) == str(score_th))]
        if sub.empty:
            continue
        top = best_exits_for(sub, top_n=5)
        best_lines.append(f"\n## {asset.upper()} / {strategy} / {interval} (score_th={score_th})\n")
        best_lines.append("**Best:** " + best_row_line(top.iloc[0]) + "\n")
        best_lines.append("\n| Rank | trail | TP | hold | IS_Sharpe | IS_n | OOS_Sharpe | OOS_n | OOS_win% | OOS_mean% | decay |")
        best_lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(top.itertuples(index=False), 1):
            tp_s = "None" if pd.isna(getattr(r, "tp")) else f"{fmt_tp(getattr(r, 'tp'))}%"
            best_lines.append(
                f"| {i} | {fmt_trail(r.trail)}% | {tp_s} | {int(r.hold)} | "
                f"{r.IS_Sharpe:+.2f} | {int(r.IS_n)} | {r.OOS_Sharpe:+.2f} | "
                f"{int(r.OOS_n)} | {getattr(r, '_8'):.1f} | "  # OOS_win% — col name with %
                f"placeholder")  # we'll rebuild below using dict
        # rebuild rows using dict to avoid named-tuple % issue
        # rewrite the table cleanly
        # (replace last len(top)+? block)

    # Simpler: rebuild best_lines from scratch using dict-based iteration
    best_lines = ["# Cycle 2 — 조합별 최적 청산 룰\n",
                  "선정 기준: OOS Sharpe 최대 (OOS_n ≥ max(20, 10% of max OOS_n) 필터).\n",
                  "각 조합 Top 5 + best 권장.\n",
                  "그리드: trail ∈ {10,15,20,25,30}%, TP ∈ {20,25,30,40,50,None}%, hold (1d) ∈ {60,120,252}, hold (1w) ∈ {13,26,52}.\n"]

    summary_rows = []
    for asset, strategy, interval, score_th in combos:
        sub = all_df[(all_df["asset"] == asset) &
                     (all_df["strategy"] == strategy) &
                     (all_df["interval"] == interval) &
                     (all_df["score_th"].astype(str) == str(score_th))]
        if sub.empty:
            continue
        top = best_exits_for(sub, top_n=5)
        best_lines.append(f"\n## {asset.upper()} / {strategy} / {interval} (score_th={score_th})\n")
        best_lines.append("**Best:** " + best_row_line(top.iloc[0]) + "\n\n")
        best_lines.append("| Rank | trail | TP | hold | IS_Sharpe | IS_n | OOS_Sharpe | OOS_n | OOS_win% | OOS_mean% | decay |")
        best_lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(top.to_dict("records"), 1):
            tp_s = "None" if pd.isna(r.get("tp")) else f"{fmt_tp(r['tp'])}%"
            decay = r.get("Sharpe_decay")
            decay_s = f"{decay:+.2f}" if (decay is not None and not pd.isna(decay)) else "-"
            best_lines.append(
                f"| {i} | {fmt_trail(r['trail'])}% | {tp_s} | {int(r['hold'])} | "
                f"{r['IS_Sharpe']:+.2f} | {int(r['IS_n'])} | "
                f"{r['OOS_Sharpe']:+.2f} | {int(r['OOS_n'])} | "
                f"{r['OOS_win%']:.1f} | {r['OOS_mean%']:+.2f} | {decay_s} |"
            )
        # Plateau check: how many cells within 90% of top OOS Sharpe?
        top_v = float(top.iloc[0]["OOS_Sharpe"])
        plateau_thresh = 0.9 * top_v if top_v > 0 else top_v + 0.1
        plateau_n = int((sub["OOS_Sharpe"] >= plateau_thresh).sum())
        best_lines.append(f"\n_Plateau: {plateau_n}/{len(sub)} cells within 90% of top OOS Sharpe._\n")
        # collect for summary
        b = top.iloc[0].to_dict()
        summary_rows.append({
            "combo": f"{asset.upper()} {strategy} {interval}",
            "score_th": score_th,
            "best_trail": f"{fmt_trail(b['trail'])}%",
            "best_TP": "None" if pd.isna(b.get("tp")) else f"{fmt_tp(b['tp'])}%",
            "best_hold": int(b["hold"]),
            "IS_Sharpe": round(b["IS_Sharpe"], 2),
            "OOS_Sharpe": round(b["OOS_Sharpe"], 2),
            "OOS_n": int(b["OOS_n"]),
            "OOS_win%": round(b["OOS_win%"], 1),
            "decay": b.get("Sharpe_decay"),
            "plateau_cells": plateau_n,
        })

    # Summary table at top (move it)
    summary_md = ["\n## 종합 요약 (조합별 best 1줄)\n",
                  "| combo | th | trail | TP | hold | IS_Sharpe | OOS_Sharpe | OOS_n | OOS_win% | decay | plateau |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in summary_rows:
        decay = r["decay"]
        decay_s = f"{decay:+.2f}" if (decay is not None and not pd.isna(decay)) else "-"
        summary_md.append(
            f"| **{r['combo']}** | {r['score_th']} | {r['best_trail']} | {r['best_TP']} | "
            f"{r['best_hold']} | {r['IS_Sharpe']:+.2f} | {r['OOS_Sharpe']:+.2f} | "
            f"{r['OOS_n']} | {r['OOS_win%']:.1f}% | {decay_s} | {r['plateau_cells']} |"
        )
    # Insert summary after header lines
    final_best = best_lines[:4] + summary_md + best_lines[4:]
    (CYCLE2 / "best_exits.md").write_text("\n".join(final_best), encoding="utf-8")
    print(f"saved: {CYCLE2/'best_exits.md'}")

    # heatmap.md
    heat_lines = ["# Cycle 2 — trail × TP heatmap (OOS Sharpe)\n",
                  "각 조합·hold 별 trail × TP 그리드. 값은 OOS Sharpe (n=OOS trade수).\n"]
    for asset, strategy, interval, score_th in combos:
        sub = all_df[(all_df["asset"] == asset) &
                     (all_df["strategy"] == strategy) &
                     (all_df["interval"] == interval) &
                     (all_df["score_th"].astype(str) == str(score_th))]
        if sub.empty:
            continue
        heat_lines.append(f"\n## {asset.upper()} / {strategy} / {interval} (score_th={score_th})\n")
        holds = sorted(sub["hold"].unique())
        for h in holds:
            heat_lines.append(f"\n### hold = {int(h)}\n")
            heat_lines.append(heatmap_oos_table(sub, int(h)))
        heat_lines.append("")
    (CYCLE2 / "heatmap.md").write_text("\n".join(heat_lines), encoding="utf-8")
    print(f"saved: {CYCLE2/'heatmap.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
