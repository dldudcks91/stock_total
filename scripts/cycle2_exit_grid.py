"""Cycle 2 — 청산 룰 미세 그리드 (OOS 평가).

Cycle 1 의 IS/OOS 검증을 통과한 6 조합에 대해 trail/TP/hold 그리드를
**OOS 기간 (2024-05-17 ~ 2026-05-17)** 한정으로 평가.

대상 조합:
  - KR / US trend_pullback 1d   (90 = 5×6×3)
  - KR / US trend_chase    1d   (90 = 5×6×3)
  - KR / US quiet_bottom   1w   (60 = 5×6×2)
총 480 combos.

그리드:
  trail_pct  ∈ {0.10, 0.15, 0.20, 0.25, 0.30}
  take_profit ∈ {0.20, 0.25, 0.30, 0.40, 0.50, None}
  hold       ∈ KR/US 1d: {60, 120, 252} / KR/US 1w: {26, 52}

score_threshold 고정: trend_pullback 70 / trend_chase 70 / quiet_bottom binary.

산출:
  scripts/out/optimize/cycle_2/exit_grid_{asset}_{strategy}_{interval}.csv
  scripts/out/optimize/cycle_2/winners.csv
  scripts/out/optimize/cycle_2/heatmap.md
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.optimize_grid import (  # noqa: E402
    STRATEGIES,
    ExitRule,
    simulate,
    COST_RT,
    MIN_BARS,
    _build_universe,
    _files_for,
    load_symbol,
)

OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "cycle_2"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS = ROOT / "scripts" / "out" / "optimize" / "PROGRESS.md"

# OOS 평가 윈도우 (Cycle 1 split 과 동일)
OOS_START = pd.Timestamp("2024-05-17")
OOS_END = pd.Timestamp("2026-05-17")
OOS_YEARS = (OOS_END - OOS_START).days / 365.25  # ~2.0

# Score threshold 고정
SCORE_TH = {"trend_pullback": 70, "trend_chase": 70, "quiet_bottom": "binary"}

# 그리드
TRAIL_GRID = [0.10, 0.15, 0.20, 0.25, 0.30]
TP_GRID = [0.20, 0.25, 0.30, 0.40, 0.50, None]   # None = TP 미사용
HOLD_1D = [60, 120, 252]
HOLD_1W = [26, 52]

TARGETS = [
    ("kr", "trend_pullback", "1d", HOLD_1D),
    ("us", "trend_pullback", "1d", HOLD_1D),
    ("kr", "trend_chase",    "1d", HOLD_1D),
    ("us", "trend_chase",    "1d", HOLD_1D),
    ("kr", "quiet_bottom",   "1w", HOLD_1W),
    ("us", "quiet_bottom",   "1w", HOLD_1W),
]


def _append_progress(line: str) -> None:
    try:
        with PROGRESS.open("a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
    except Exception as e:
        print(f"[warn] PROGRESS append failed: {e}", file=sys.stderr)


def _summarize(rets: np.ndarray, held: np.ndarray, period_years: float) -> dict:
    if rets.size == 0:
        return {"n": 0, "win%": 0.0, "mean%": 0.0, "median%": 0.0,
                "MDD%": 0.0, "Sharpe": 0.0, "PF": 0.0, "held_mean": 0.0,
                "total%": 0.0}
    win = float((rets > 0).mean() * 100)
    mean = float(rets.mean() * 100)
    med = float(np.median(rets) * 100)
    eq = np.cumprod(1.0 + rets)
    peak = np.maximum.accumulate(eq)
    mdd = float((eq / peak - 1.0).min() * 100)
    total = float((eq[-1] - 1.0) * 100)
    if rets.std() > 0:
        sharpe_pt = rets.mean() / rets.std()
        ann_factor = np.sqrt(max(1, len(rets)) / period_years)
        sharpe = float(sharpe_pt * ann_factor)
    else:
        sharpe = 0.0
    gains = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = float(gains / losses) if losses > 0 else 99.99
    return {
        "n": int(rets.size),
        "win%": round(win, 1),
        "mean%": round(mean, 2),
        "median%": round(med, 2),
        "MDD%": round(mdd, 1),
        "Sharpe": round(sharpe, 2),
        "PF": round(pf, 2),
        "held_mean": round(float(held.mean()), 1),
        "total%": round(total, 1),
    }


def _build_entry_cache(asset: str, strategy: str, interval: str):
    """종목별 (close, entry positions in OOS window) 사전 계산."""
    strat = STRATEGIES[strategy]
    min_bars = MIN_BARS[interval]
    universe = _build_universe(asset)
    files = _files_for(asset, interval)
    is_quiet = (strategy == "quiet_bottom")
    th_raw = SCORE_TH[strategy]

    cache: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}  # symbol -> (close, entry_positions)
    n_done = 0
    n_skip = 0
    t0 = time.time()
    for p in files:
        sym = p.stem
        if sym not in universe:
            continue
        try:
            df = load_symbol(asset, p, interval)
        except Exception:
            n_skip += 1
            continue
        if df is None or df.empty or len(df) < min_bars:
            n_skip += 1
            continue
        df = df.sort_index()
        df_r = df.reset_index(drop=True)
        try:
            if is_quiet:
                sig = strat.signal(df_r, {})
                val = sig.to_numpy().astype("int8")
                sig01 = val
            else:
                sc = strat.score(df_r, {})
                val = sc.to_numpy().astype("float32")
                sig01 = (val >= float(th_raw)).astype("int8")
        except Exception:
            n_skip += 1
            continue
        close = df["close"].astype("float64").to_numpy()
        if len(sig01) < 2:
            continue
        dt_idx = pd.DatetimeIndex(df.index)
        in_oos = np.asarray((dt_idx >= OOS_START) & (dt_idx <= OOS_END))
        diff = np.diff(sig01.astype("int16"), prepend=0)
        enter = np.where((diff == 1) & in_oos)[0]
        if enter.size == 0:
            continue
        # 유효 진입만 보존 (마지막 봉 직전까지)
        enter = enter[enter < len(close) - 1]
        if enter.size == 0:
            continue
        cache[sym] = (close, enter)
        n_done += 1
        if n_done % 100 == 0:
            print(f"  loaded {n_done} symbols (skipped {n_skip})", flush=True)

    elapsed = time.time() - t0
    print(f"  total cache: {n_done} symbols (skipped {n_skip}, elapsed {elapsed:.1f}s)", flush=True)
    return cache


def _run_combo(asset: str, strategy: str, interval: str, holds: List[int]) -> pd.DataFrame:
    cost = COST_RT[asset]
    th = SCORE_TH[strategy]
    print(f"\n=== {asset.upper()} / {strategy} / {interval}  (score_th={th}) ===", flush=True)
    cache = _build_entry_cache(asset, strategy, interval)
    if not cache:
        print("  [warn] empty cache — skip", flush=True)
        return pd.DataFrame()

    rows = []
    grid_n = len(TRAIL_GRID) * len(TP_GRID) * len(holds)
    print(f"  grid size: {grid_n} cells", flush=True)
    t_grid = time.time()

    for trail in TRAIL_GRID:
        for tp in TP_GRID:
            for hold in holds:
                rule = ExitRule(
                    name=f"trail{int(trail*100)}_TP{('NA' if tp is None else int(tp*100))}_hold{hold}",
                    max_hold=hold,
                    trailing_pct=trail,
                    take_profit_pct=(tp if tp is not None else 0.0),
                )
                rets_list: List[float] = []
                held_list: List[int] = []
                for sym, (close, enter) in cache.items():
                    for pos in enter:
                        exit_pos, gross = simulate(close, int(pos), rule)
                        if exit_pos == pos:
                            continue
                        rets_list.append(gross - cost)
                        held_list.append(int(exit_pos - pos))
                rets = np.asarray(rets_list, dtype="float64")
                held = np.asarray(held_list, dtype="float64")
                s = _summarize(rets, held, OOS_YEARS)
                rows.append({
                    "asset": asset,
                    "strategy": strategy,
                    "interval": interval,
                    "score_th": th,
                    "trail_pct": trail,
                    "take_profit": (None if tp is None else tp),
                    "hold_bars": hold,
                    **s,
                })

    df = pd.DataFrame(rows)
    out_csv = OUT_DIR / f"exit_grid_{asset}_{strategy}_{interval}.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"  saved: {out_csv}  ({len(df)} rows, grid elapsed {time.time()-t_grid:.1f}s)", flush=True)
    return df


def _heatmap_block(df: pd.DataFrame, title: str, hold_pref: Optional[int] = None) -> str:
    """trail × TP 표 (특정 hold 고정) — Sharpe 값."""
    if df.empty:
        return f"### {title}\n\n(no data)\n"
    if hold_pref is None:
        # 최대 Sharpe 의 hold 선택
        best_row = df.loc[df["Sharpe"].idxmax()]
        hold_pref = int(best_row["hold_bars"])
    sub = df[df["hold_bars"] == hold_pref].copy()
    if sub.empty:
        return f"### {title}\n\n(no data for hold={hold_pref})\n"
    sub["tp_str"] = sub["take_profit"].apply(lambda x: "None" if pd.isna(x) or x is None else f"{int(x*100)}%")
    pivot = sub.pivot_table(index="trail_pct", columns="tp_str", values="Sharpe")
    # 컬럼 정렬
    order = []
    for v in [0.20, 0.25, 0.30, 0.40, 0.50]:
        c = f"{int(v*100)}%"
        if c in pivot.columns:
            order.append(c)
    if "None" in pivot.columns:
        order.append("None")
    pivot = pivot[order]
    lines = [f"### {title} (hold={hold_pref})", "",
             "| trail \\ TP | " + " | ".join(pivot.columns) + " |",
             "|" + "---|" * (len(pivot.columns) + 1)]
    for trail in sorted(pivot.index):
        row = [f"{int(trail*100)}%"] + [f"{pivot.loc[trail, c]:.2f}" if pd.notna(pivot.loc[trail, c]) else "—"
                                          for c in pivot.columns]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines)


def _write_winners_and_heatmap(all_df: pd.DataFrame) -> None:
    # Winners
    win_rows = []
    blocks = []
    for (asset, strat, itv), sub in all_df.groupby(["asset", "strategy", "interval"], sort=False):
        if sub.empty:
            continue
        best = sub.loc[sub["Sharpe"].idxmax()].to_dict()
        top5 = sub.sort_values("Sharpe", ascending=False).head(5).copy()
        win_rows.append(best)
        # heatmap block (best hold 기준)
        blocks.append(_heatmap_block(sub, f"{asset.upper()} {strat} {itv}", int(best["hold_bars"])))
        # 추가: top5 표
        top_lines = [f"#### {asset.upper()} {strat} {itv} — Top 5",
                     "",
                     "| rank | trail | TP | hold | Sharpe | win% | mean% | MDD% | n |",
                     "|---|---|---|---|---|---|---|---|---|"]
        for i, (_, r) in enumerate(top5.iterrows(), 1):
            tp_s = "None" if pd.isna(r["take_profit"]) else f"{int(r['take_profit']*100)}%"
            top_lines.append(f"| {i} | {int(r['trail_pct']*100)}% | {tp_s} | {int(r['hold_bars'])} | "
                             f"{r['Sharpe']:.2f} | {r['win%']:.1f} | {r['mean%']:+.2f} | "
                             f"{r['MDD%']:+.1f} | {int(r['n'])} |")
        top_lines.append("")
        blocks.append("\n".join(top_lines))

    win_df = pd.DataFrame(win_rows)
    if not win_df.empty:
        col_order = ["asset", "strategy", "interval", "score_th",
                     "trail_pct", "take_profit", "hold_bars",
                     "Sharpe", "win%", "mean%", "median%", "MDD%", "PF",
                     "n", "held_mean", "total%"]
        win_df = win_df[[c for c in col_order if c in win_df.columns]]
        win_df.to_csv(OUT_DIR / "winners.csv", index=False, encoding="utf-8-sig")
        print(f"  saved: winners.csv  ({len(win_df)} rows)")

    # Heatmap MD
    md_lines = ["# Cycle 2 — 청산 룰 미세 그리드 (OOS 2024-05-17 ~ 2026-05-17)",
                "",
                "score_threshold 고정 (trend_pullback 70 / trend_chase 70 / quiet_bottom binary),",
                "trail × TP × hold 그리드 총 480 combos.",
                "",
                "각 (asset, strategy, interval) 블록은 **best hold 기준 trail×TP heatmap** 과 **Top 5** 표.",
                ""]
    md_lines.extend(blocks)
    (OUT_DIR / "heatmap.md").write_text("\n".join(md_lines), encoding="utf-8")
    print("  saved: heatmap.md")


def main():
    t_start = time.time()
    all_parts: List[pd.DataFrame] = []
    for (asset, strat, itv, holds) in TARGETS:
        try:
            df = _run_combo(asset, strat, itv, holds)
            if not df.empty:
                all_parts.append(df)
            # incremental PROGRESS log
            ts = pd.Timestamp.now(tz="Asia/Seoul").strftime("%H:%M")
            _append_progress(f"- [{ts}] Cycle2: {asset}/{strat} {itv} done ({len(df)} cells)")
        except Exception as e:
            print(f"FAIL {asset}/{strat}/{itv}: {type(e).__name__}: {e}", file=sys.stderr)
            import traceback; traceback.print_exc()
    if not all_parts:
        print("no data produced", file=sys.stderr)
        return 1
    all_df = pd.concat(all_parts, ignore_index=True)
    _write_winners_and_heatmap(all_df)
    print(f"\nALL DONE — total elapsed {time.time()-t_start:.1f}s, "
          f"total rows {len(all_df)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
