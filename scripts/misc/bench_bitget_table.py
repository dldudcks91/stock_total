"""Bench: how long does the Bitget table's candle pass take at N=50 vs N=all?

Reuses the page's `fetch_tickers` + `fetch_candles_batch` so the test path
matches what the dashboard actually does. Streamlit is stubbed out so the
module can be loaded without launching a server.
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")


def _stub_streamlit() -> None:
    # Use real streamlit so st_aggrid's declare_component works.
    class _Any:
        def __getattr__(self, n):
            return _Any()
        def __call__(self, *a, **k):
            return _Any()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    try:
        import streamlit_lightweight_charts  # noqa: F401
    except ImportError:
        sys.modules["streamlit_lightweight_charts"] = _Any()
    import streamlit  # noqa: F401


def _load_page_module():
    _stub_streamlit()
    src = (ROOT / "dashboards" / "pages" / "3_Bitget.py").read_text(encoding="utf-8")
    # Drop the module-level main() invocation so importing doesn't launch the page.
    src = src.replace("\nmain()\n", "\n")
    page_path = ROOT / "dashboards" / "pages" / "3_Bitget.py"
    ns: dict = {"__name__": "bp_bench", "__file__": str(page_path)}
    exec(compile(src, str(page_path), "exec"), ns)
    return ns


def main() -> None:
    ns = _load_page_module()
    fetch_tickers = ns["fetch_tickers"]
    compute_from_cache = ns["compute_from_cache"]

    t0 = time.perf_counter()
    df0 = fetch_tickers()
    t_ticker = time.perf_counter() - t0
    print(f"ticker snapshot: {t_ticker*1000:6.1f} ms  rows={len(df0)}")

    df0 = df0.sort_values("quoteVolume", ascending=False, na_position="last").reset_index(drop=True)
    syms_50 = df0["symbol"].head(50).astype(str).tolist()
    syms_all = df0["symbol"].astype(str).tolist()

    def bench(symbols: list[str], label: str, repeats: int = 3) -> dict:
        sub = df0[df0["symbol"].astype(str).isin(symbols)].copy()
        current_prices = dict(zip(sub["symbol"].astype(str), sub["markPrice"]))

        timings = []
        for _ in range(repeats):
            t = time.perf_counter()
            out = compute_from_cache(current_prices, symbols)  # all 7 windows
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

    # Re-rendering on each rerun also includes a ticker fetch (~1s, but 3s cached)
    # and Styler/data_editor cost which we can't time from python.
    print("\nReal render = ticker fetch (cache hit ≈0ms / miss ≈ ticker line above)")
    print("              + compute+merge (above)")
    print("              + Styler.apply + data_editor render (browser-side, not measured)")


if __name__ == "__main__":
    main()
