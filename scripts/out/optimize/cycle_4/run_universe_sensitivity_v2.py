"""Cycle 4b v2 — Universe sensitivity.

기존 v1 은 _universe_cache.json 이 top-300 까지만 캐싱돼 top_n=500 이 300 과 동일했음.
v2 는 {50, 100, 300} (캐시 내부) + 500 (FDR 실시간) 로 확장.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from scripts.optimize.cycle2_exit_grid import ExitRule, run_combo  # noqa: E402

OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "cycle_4"
OUT_DIR.mkdir(parents=True, exist_ok=True)

UNI_CACHE = ROOT / "scripts" / "out" / "optimize" / "_universe_cache.json"


def _cache_slice(asset: str, top_n: int) -> set:
    data = json.loads(UNI_CACHE.read_text(encoding="utf-8"))
    return set(data[asset][:top_n])


def _fdr_top500(asset: str) -> set:
    """캐시 cap(300) 초과 — FDR 직접 호출."""
    try:
        import FinanceDataReader as fdr
        if asset == "kr":
            df = fdr.StockListing("KOSPI").dropna(subset=["Marcap"]).sort_values(
                "Marcap", ascending=False
            )
            return set(df["Code"].head(500).astype(str).tolist())
        if asset == "us":
            df = fdr.StockListing("NASDAQ")
            return set(df["Symbol"].head(500).astype(str).tolist())
    except Exception as e:
        print(f"[fdr] fallback (cache 300): {type(e).__name__}: {e}", flush=True)
    return _cache_slice(asset, 300)


BEST_RULES = {
    ("kr", "trend_pullback", "1d", 60.0): ExitRule(
        "h252_tr25_TP30", max_hold=252, trailing_pct=0.25, take_profit_pct=0.30,
    ),
    ("us", "trend_pullback", "1d", 70.0): ExitRule(
        "h252_tr20_TP30", max_hold=252, trailing_pct=0.20, take_profit_pct=0.30,
    ),
}

TOP_NS = [50, 100, 300, 500]


def main():
    rows = []
    for (asset, strat, itv, th), rule in BEST_RULES.items():
        for top_n in TOP_NS:
            import scripts.optimize.cycle2_exit_grid as c2
            import scripts.trend_strategies.forward_returns as fr
            _orig_us = c2.us_universe
            _orig_kr = c2.kr_universe
            _orig_us_fr = fr.us_universe
            _orig_kr_fr = fr.kr_universe
            if top_n <= 300:
                slicer = lambda n, _a=asset, _t=top_n: _cache_slice(_a, _t)
            else:
                fetched = _fdr_top500(asset)
                slicer = lambda n, _f=fetched: _f
            if asset == "kr":
                c2.kr_universe = slicer
                fr.kr_universe = slicer
            else:
                c2.us_universe = slicer
                fr.us_universe = slicer

            try:
                t0 = time.time()
                print(f"\n=== {asset} {strat} {itv} th={th} top_n={top_n} ===",
                      flush=True)
                df_one = run_combo(asset, strat, itv, th, [rule])
                if df_one.empty:
                    print("  empty result"); continue
                m = df_one.iloc[0].to_dict()
                m["top_n"] = top_n
                rows.append(m)
                print(f"  -> n_full={m.get('n_full')} "
                      f"Sharpe_full={m.get('Sharpe_full')} "
                      f"Sharpe_oos={m.get('Sharpe_oos')} "
                      f"mean%_full={m.get('mean%_full')} "
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
