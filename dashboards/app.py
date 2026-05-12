"""Multi-page Streamlit dashboard entry point.

Run with:
    streamlit run dashboards/app.py

Pages live in `dashboards/pages/` and are auto-discovered by Streamlit. The
home page just shows a quick run inventory and routes the user to the relevant
page from the sidebar.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root (parent of `dashboards/`) is on sys.path so
# `from dashboards._lib import ...` works under `streamlit run`.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboards._lib import (
    list_runs,
    load_config,
    load_metrics,
    fmt_metric,
)


def main() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="Crypto Dashboards",
        page_icon="📊",
        layout="wide",
    )
    st.title("Crypto Dashboards")
    st.caption(
        "왼쪽 사이드바에서 페이지를 선택하세요 — Backtest / Compare / Realtime."
    )

    runs = list_runs()
    st.markdown("### 런 인벤토리")

    col_a, col_b = st.columns([1, 3])
    col_a.metric("# of runs", len(runs))

    if not runs:
        st.warning("아직 백테스트 런이 없습니다.")
        st.code(
            "python -m backtest.engine.runner "
            "--strategy <name> --symbol BTCUSDT --interval 1h "
            "--start 2023-01-01 --end 2024-01-01",
            language="bash",
        )
        return

    rows = []
    for p in runs[:10]:
        cfg = load_config(p)
        m = load_metrics(p)
        rows.append({
            "run": p.name,
            "strategy": cfg.get("strategy", "—"),
            "symbol": cfg.get("symbol", "—"),
            "interval": cfg.get("interval", "—"),
            "total_return": fmt_metric("total_return", m.get("total_return")),
            "sharpe": fmt_metric("sharpe", m.get("sharpe")),
            "mdd": fmt_metric("mdd", m.get("mdd")),
            "n_trades": fmt_metric("n_trades", m.get("n_trades")),
        })

    import pandas as pd
    st.markdown("**최근 10개 런**")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown(
        "- **Backtest** — 단일 런 상세 뷰어\n"
        "- **Compare** — 여러 런을 골라 메트릭/equity 비교\n"
        "- **Bitget** — Bitget USDT-M 전 종목 라이브 표 (REST 직접 폴링)\n"
        "- **KOSPI** — 시총 상위 KOSPI 종목 라이브 표 (Naver 비공식)\n"
        "- **NASDAQ** — 캐시된 NASDAQ 심볼 라이브 표 (Naver 비공식)\n"
        "- **Mobile** — 모바일 친화 카드 리스트 (Bitget 앱 스타일)\n"
        "- **Chart** — 임의 심볼 캔들 차트 (crypto/KR/US)\n"
        "- **Realtime** — 실시간 수집기 DB (Coming soon)"
    )


if __name__ == "__main__":
    main()
