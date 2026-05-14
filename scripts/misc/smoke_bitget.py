"""Quick import-test for the Bitget page (streamlit stubbed)."""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")


class _Any:
    def __getattr__(self, n):
        return _Any()

    def __call__(self, *a, **k):
        return _Any()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def main() -> None:
    # Use real streamlit (st_aggrid needs streamlit.components.v1.declare_component);
    # only mock the streamlit-lightweight-charts dependency if missing.
    try:
        import streamlit_lightweight_charts  # noqa: F401
    except ImportError:
        sys.modules["streamlit_lightweight_charts"] = _Any()
    import streamlit as st  # noqa: F401  (just need it loaded)

    src = (ROOT / "dashboards" / "pages" / "3_Bitget.py").read_text(encoding="utf-8")
    src = src.replace("\nmain()\n", "\n")
    ns: dict = {"__name__": "smoke", "__file__": str(ROOT / "dashboards/pages/3_Bitget.py")}
    try:
        exec(compile(src, "3_Bitget.py", "exec"), ns)
        print("IMPORT OK")
        # Quick test: build_grid_options works with a small synthetic df
        import pandas as pd
        df = pd.DataFrame({
            "symbol": ["BTCUSDT", "ETHUSDT"],
            "markPrice": [60000.0, 3000.0],
            "quoteVolume": [1.2e9, 8e8],
            "fundingRate": [0.0001, -0.0002],
            "change24h": [0.025, -0.012],
            "pct_1h": [0.001, 0.002],
            "pct_4h": [-0.005, 0.003],
            "pct_3d": [0.05, -0.02],
            "pct_7d": [0.1, 0.05],
            "pct_14d": [0.2, -0.1],
            "pct_28d": [0.5, 0.3],
            "pct_ma10__24h": [0.01, -0.005],
            "pct_ma20__24h": [0.02, -0.01],
            "pct_off_high__24h": [-0.05, -0.1],
            "pct_off_low__24h": [0.03, 0.08],
            "note": ["", "test note"],
        })
        df_grid, opts = ns["build_grid_options"](df, "24h", "BTCUSDT")
        col_defs = opts.get("columnDefs", [])
        print(f"build_grid_options OK: {len(col_defs)} columnDefs, df_grid={len(df_grid.columns)} cols")
        # Print visible column headers in display order
        visible = [c for c in col_defs if not c.get("hide")]
        print("visible:", [c.get("headerName") for c in visible])
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
