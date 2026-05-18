"""Cycle 4b — Universe sensitivity test.

목적: best 청산룰을 universe top-N (100/300/500) 으로 변경했을 때 결과 견고성.
대상: KR/US trend_pullback 1d (Cycle 2 best 조합).

산출: scripts/out/optimize/cycle_4/universe_sensitivity.csv
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from scripts.optimize.cycle2_exit_grid import (  # noqa: E402
    ExitRule, run_combo,
)

OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "cycle_4"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 캐시된 universe 일부만 사용
UNI_CACHE = ROOT / "scripts" / "out" / "optimize" / "_universe_cache.json"


def _slice_universe(asset: str, top_n: int) -> set:
    data = json.loads(UNI_CACHE.read_text(encoding="utf-8"))
    return set(data[asset][:top_n])


# Cycle 2 best 청산룰
BEST_RULES = {
    ("kr", "trend_pullback", "1d", 60.0): ExitRule(
        "h252_tr25_TP30", max_hold=252, trailing_pct=0.25, take_profit_pct=0.30,
    ),
    ("us", "trend_pullback", "1d", 70.0): ExitRule(
        "h252_tr20_TP30", max_hold=252, trailing_pct=0.20, take_profit_pct=0.30,
    ),
}


def main():
    rows = []
    for (asset, strat, itv, th), rule in BEST_RULES.items():
        for top_n in (100, 300, 500):
            # Monkey-patch the universe (cycle2 imports as local names)
            import scripts.optimize.cycle2_exit_grid as c2
            import scripts.trend_strategies.forward_returns as fr
            _orig_us = c2.us_universe
            _orig_kr = c2.kr_universe
            _orig_us_fr = fr.us_universe
            _orig_kr_fr = fr.kr_universe
            if asset == "kr":
                c2.kr_universe = lambda n: _slice_universe("kr", min(n, top_n))
                fr.kr_universe = c2.kr_universe
            else:
                c2.us_universe = lambda n: _slice_universe("us", min(n, top_n))
                fr.us_universe = c2.us_universe

            try:
                t0 = time.time()
                print(f"\n=== {asset} {strat} {itv} th={th} top_n={top_n} ===", flush=True)
                df_one = run_combo(asset, strat, itv, th, [rule])
                if df_one.empty:
                    print("  empty result"); continue
                m = df_one.iloc[0].to_dict()
                m["top_n"] = top_n
                rows.append(m)
                print(f"  -> n_full={m.get('n_full')} Sharpe_full={m.get('Sharpe_full')} "
                      f"Sharpe_oos={m.get('Sharpe_oos')} mean%={m.get('mean%_full')} "
                      f"(elapsed {time.time()-t0:.1f}s)", flush=True)
            finally:
                c2.us_universe = _orig_us
                c2.kr_universe = _orig_kr
                fr.us_universe = _orig_us_fr
                fr.kr_universe = _orig_kr_fr

    df = pd.DataFrame(rows)
    cols = ["asset", "strategy", "interval", "score_th", "top_n",
            "n_full", "win%_full", "mean%_full", "Sharpe_full",
            "n_oos", "win%_oos", "mean%_oos", "Sharpe_oos"]
    cols = [c for c in cols if c in df.columns]
    df = df[cols]
    out = OUT_DIR / "universe_sensitivity.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\nsaved: {out}")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
