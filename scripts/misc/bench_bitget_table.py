"""Bench: how long does the Bitget table's candle pass take at N=50 vs N=all?

Measures the local-cache compute path (``compute_from_cache``) over a real
Bitget ticker snapshot so the numbers match what the dashboard actually does.
Previously this script execed the page module to grab its inner functions;
since the page was split into ``dashboards/live/`` modules it now imports the
compute helper directly.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from dashboards.live._crypto_compute import compute_from_cache  # noqa: E402
from data.sources.bitget_live import load_snapshot  # noqa: E402


def _load_ticker_snapshot():
    """Reuse the persisted Bitget snapshot if present; otherwise None.

    The original bench fetched live tickers via the page's ``fetch_tickers``
    helper, but that lived inside the page module and used aiohttp directly.
    The persisted snapshot is what the dashboard actually displays, so using
    it here keeps the bench's symbol/price universe consistent with reality.
    """
    df = load_snapshot()
    if df is None or df.empty:
        return None
    return df


def main() -> None:
    t0 = time.perf_counter()
    df0 = _load_ticker_snapshot()
    t_ticker = time.perf_counter() - t0
    if df0 is None:
        print(
            "No persisted snapshot at data/cache/crypto/_live_snapshot.parquet — "
            "run `python -m data.sources.bitget_live` first or open the Live "
            "dashboard and click '라이브 가격 갱신'."
        )
        return
    print(f"snapshot load: {t_ticker*1000:6.1f} ms  rows={len(df0)}")

    df0 = df0.sort_values("quoteVolume", ascending=False, na_position="last").reset_index(drop=True)
    syms_50 = df0["symbol"].head(50).astype(str).tolist()
    syms_all = df0["symbol"].astype(str).tolist()

    def bench(symbols: list[str], label: str, repeats: int = 3) -> dict:
        sub = df0[df0["symbol"].astype(str).isin(symbols)].copy()
        current_prices = dict(zip(sub["symbol"].astype(str), sub["markPrice"]))

        timings = []
        for _ in range(repeats):
            t = time.perf_counter()
            out = compute_from_cache(current_prices, symbols)  # all windows
            overlap = [c for c in out.columns if c != "symbol" and c in sub.columns]
            base = sub.drop(columns=overlap) if overlap else sub
            merged = base.merge(out, on="symbol", how="left")
            timings.append(time.perf_counter() - t)
        best = min(timings)
        avg = sum(timings) / len(timings)
        print(
            f"[{label}] N={len(symbols):>3}  "
            f"compute+merge: best {best*1000:7.1f} ms  avg {avg*1000:7.1f} ms  "
            f"(over {repeats} runs)"
        )
        return {"best": best, "avg": avg, "N": len(symbols)}

    print("\n--- compute_from_cache + merge (no API; local parquet only) ---")
    r50 = bench(syms_50, "  50")
    ra = bench(syms_all, f"all={len(syms_all)}")

    print(
        f"\nratio (best):  {ra['best']/r50['best']:.2f}x slower for "
        f"{ra['N']/r50['N']:.2f}x more symbols"
    )
    print(
        f"per-symbol (best):  50→{r50['best']*1000/r50['N']:.2f} ms/sym   "
        f"all→{ra['best']*1000/ra['N']:.2f} ms/sym"
    )

    print("\nReal render = snapshot load (above) + compute+merge (above)")
    print("              + AgGrid serialize + browser render (not measured)")


if __name__ == "__main__":
    main()
