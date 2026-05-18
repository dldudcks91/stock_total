"""Stage A (threshold sweep) + Stage B (exit sweep) 자동 실행.

전체 흐름:
  Stage A: 각 (asset, strategy, interval) 에 대해 default exit 로 threshold 그리드
           {60, 70, 75, 80, 85, 90} → grid_{asset}_{strategy}_{interval}_stageA.csv
  Stage B: Stage A best threshold 에서 exit_rule 그리드 → ..._stageB.csv

  quiet_bottom 은 binary 이므로 Stage A 의 threshold sweep 은 생략.
  KR/US quiet_bottom 은 QUIET_BOTTOM.md 에 검증된 값을 그대로 사용 → Stage B 도 skip
  (crypto quiet_bottom 만 재튜닝).

CLI:
  python -m scripts.optimize.stage_runner --stage A
  python -m scripts.optimize.stage_runner --stage B
  python -m scripts.optimize.stage_runner --stage both
  python -m scripts.optimize.stage_runner --stage A --only kr,trend_chase,1d
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.optimize.threshold_grid import (  # noqa: E402
    OUT_DIR, STRATEGIES, _universe, run_grid,
    stage_a_exit_default, stage_b_exit_grid,
)

# 조합 정의 — (asset, strategy, interval)
COMBOS_STAGE_A: list[tuple[str, str, str]] = []
COMBOS_STAGE_B: list[tuple[str, str, str]] = []

for asset in ("kr", "us"):
    for itv in ("1d", "1w"):
        COMBOS_STAGE_A.append((asset, "trend_chase", itv))
        COMBOS_STAGE_A.append((asset, "trend_pullback", itv))
    # quiet_bottom 1w only (binary, KR/US 검증 완료 → Stage B 만 sanity check)
    COMBOS_STAGE_A.append((asset, "quiet_bottom", "1w"))

for itv in ("1h", "4h", "1d", "1w"):
    COMBOS_STAGE_A.append(("crypto", "trend_chase", itv))
    COMBOS_STAGE_A.append(("crypto", "trend_pullback", itv))
# crypto quiet_bottom 1w (재튜닝 대상 — Stage B 에서 다양한 exit 그리드)
COMBOS_STAGE_A.append(("crypto", "quiet_bottom", "1w"))

THRESHOLDS = [60.0, 70.0, 75.0, 80.0, 85.0, 90.0]

# 자산별 universe 캐시 (FDR 호출 비싸므로 1회만)
_UNIVERSE_CACHE: dict[str, set] = {}


def get_universe(asset: str) -> set:
    if asset not in _UNIVERSE_CACHE:
        print(f"  building universe for {asset}...", flush=True)
        _UNIVERSE_CACHE[asset] = _universe(asset)
        print(f"  universe[{asset}] = {len(_UNIVERSE_CACHE[asset])} symbols", flush=True)
    return _UNIVERSE_CACHE[asset]


def append_progress(line: str):
    p = OUT_DIR / "PROGRESS.md"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S KST")
    with p.open("a", encoding="utf-8") as f:
        f.write(f"- [{ts}] {line}\n")


def filter_combos(combos, only: str) -> list[tuple[str, str, str]]:
    """only='kr,trend_chase,1d' → 해당만 필터. 빈 칸은 와일드카드."""
    if not only:
        return combos
    parts = only.split(",")
    if len(parts) < 3:
        parts += [""] * (3 - len(parts))
    a, s, i = parts[0].strip(), parts[1].strip(), parts[2].strip()
    out = []
    for c in combos:
        if (not a or c[0] == a) and (not s or c[1] == s) and (not i or c[2] == i):
            out.append(c)
    return out


def run_stage_a(only: str = ""):
    combos = filter_combos(COMBOS_STAGE_A, only)
    print(f"\n========== Stage A — threshold sweep ({len(combos)} combos) ==========")
    append_progress(f"Stage A 시작: {len(combos)} combos")

    all_rows = []
    for i, (asset, strat, itv) in enumerate(combos, 1):
        t0 = time.time()
        print(f"\n[{i}/{len(combos)}] {asset} / {strat} / {itv}", flush=True)
        try:
            uni = get_universe(asset)
            exit_rule = stage_a_exit_default(asset, strat, itv)
            print(f"  exit: {exit_rule.name} hold={exit_rule.max_hold} tr={exit_rule.trailing_pct} tp={exit_rule.take_profit_pct} cut={exit_rule.cut_early_neg}")
            df = run_grid(asset, itv, strat, THRESHOLDS, [exit_rule], universe=uni, verbose=True)
            csv_path = OUT_DIR / f"grid_{asset}_{strat}_{itv}_stageA.csv"
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            all_rows.append(df)
            elapsed = time.time() - t0
            print(f"  saved {csv_path.name} ({elapsed:.1f}s)", flush=True)
        except Exception as e:
            import traceback
            print(f"  ERROR: {type(e).__name__}: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            append_progress(f"Stage A ERROR {asset}/{strat}/{itv}: {e}")

    if all_rows:
        combined = pd.concat(all_rows, ignore_index=True)
        combined.to_csv(OUT_DIR / "stageA_all.csv", index=False, encoding="utf-8-sig")
        print(f"\nstageA_all.csv saved ({len(combined)} rows)", flush=True)

    append_progress(f"Stage A 완료: {len(all_rows)} combos OK")
    return combined if all_rows else pd.DataFrame()


def _pick_best_threshold(df: pd.DataFrame) -> float:
    """최적 threshold 결정 — Sharpe 최대, tie 시 n>=20 우선, 그래도 tie 면 작은 threshold."""
    if df.empty:
        return 80.0
    # n_trades >= 10 필터 (의미있는 표본)
    candidates = df[df["n"] >= 10].copy()
    if candidates.empty:
        candidates = df.copy()
    candidates = candidates.sort_values(["sharpe", "n", "threshold"],
                                        ascending=[False, False, True])
    return float(candidates.iloc[0]["threshold"])


def run_stage_b(only: str = ""):
    """Stage A 결과에서 각 combo 의 best threshold 를 골라 exit grid 실행."""
    combos = filter_combos(COMBOS_STAGE_A, only)  # stage_B 도 같은 combos
    print(f"\n========== Stage B — exit rule sweep at best threshold ({len(combos)} combos) ==========")
    append_progress(f"Stage B 시작: {len(combos)} combos")

    all_rows = []
    for i, (asset, strat, itv) in enumerate(combos, 1):
        t0 = time.time()
        print(f"\n[{i}/{len(combos)}] {asset} / {strat} / {itv}", flush=True)

        # Stage A best threshold
        a_csv = OUT_DIR / f"grid_{asset}_{strat}_{itv}_stageA.csv"
        if not a_csv.exists():
            print(f"  skip — no stageA result ({a_csv.name})", flush=True)
            continue
        a_df = pd.read_csv(a_csv)
        best_th = _pick_best_threshold(a_df)
        print(f"  best threshold from Stage A = {best_th}")

        exit_rules = stage_b_exit_grid(asset, strat, itv)
        if not exit_rules:
            print(f"  skip — no exit grid defined")
            continue
        print(f"  exit rules: {len(exit_rules)}")

        try:
            uni = get_universe(asset)
            df = run_grid(asset, itv, strat, [best_th], exit_rules, universe=uni, verbose=True)
            csv_path = OUT_DIR / f"grid_{asset}_{strat}_{itv}_stageB.csv"
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            all_rows.append(df)
            elapsed = time.time() - t0
            print(f"  saved {csv_path.name} ({elapsed:.1f}s)", flush=True)
        except Exception as e:
            import traceback
            print(f"  ERROR: {type(e).__name__}: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            append_progress(f"Stage B ERROR {asset}/{strat}/{itv}: {e}")

    if all_rows:
        combined = pd.concat(all_rows, ignore_index=True)
        combined.to_csv(OUT_DIR / "stageB_all.csv", index=False, encoding="utf-8-sig")
        print(f"\nstageB_all.csv saved ({len(combined)} rows)", flush=True)

    append_progress(f"Stage B 완료: {len(all_rows)} combos OK")
    return combined if all_rows else pd.DataFrame()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["A", "B", "both"], default="A")
    ap.add_argument("--only", default="", help="e.g. 'kr,trend_chase,1d' or 'crypto,,1h'")
    args = ap.parse_args()

    if args.stage in ("A", "both"):
        run_stage_a(args.only)
    if args.stage in ("B", "both"):
        run_stage_b(args.only)


if __name__ == "__main__":
    main()
