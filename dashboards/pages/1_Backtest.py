"""Single-run backtest viewer.

Sidebar lets you pick one run; the body shows metric cards, equity + drawdown,
position distribution, and the last 100 trades. Same logic as the original
`backtest_app.py` — moved into a multipage Streamlit page.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboards._lib import (
    list_runs,
    compute_drawdown,
    to_utc_datetime,
    to_kst,
    position_distribution,
    annotate_trades,
    fmt_pct,
    fmt_float,
    fmt_int,
)
from dashboards._cache import load_config, load_metrics, load_equity, load_trades


def render_metric_cards(st, metrics: dict[str, Any]) -> None:
    row1 = st.columns(5)
    row1[0].metric("Total Return", fmt_pct(metrics.get("total_return")))
    row1[1].metric("CAGR", fmt_pct(metrics.get("cagr")))
    row1[2].metric("Sharpe", fmt_float(metrics.get("sharpe"), 3))
    row1[3].metric("MDD", fmt_pct(metrics.get("mdd")))
    row1[4].metric("# Trades", fmt_int(metrics.get("n_trades")))

    row2 = st.columns(4)
    row2[0].metric("Win Rate", fmt_pct(metrics.get("win_rate")))
    row2[1].metric("Avg PnL %", fmt_pct(metrics.get("avg_pnl_pct")))
    row2[2].metric("Avg Hold (bars)", fmt_float(metrics.get("avg_holding_bars"), 2))
    row2[3].metric("# Bars", fmt_int(metrics.get("n_bars")))


def render_equity_chart(st, equity: pd.DataFrame, use_kst: bool) -> None:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    if equity.empty:
        st.info("equity.parquet 비어있음")
        return

    eq = equity.copy()
    dt_utc = to_utc_datetime(eq["timestamp"])
    eq["dt"] = to_kst(dt_utc) if use_kst else dt_utc
    eq["dd"] = compute_drawdown(eq["equity"])

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.7, 0.3], vertical_spacing=0.05,
        subplot_titles=("Equity", "Drawdown"),
    )
    fig.add_trace(
        go.Scatter(x=eq["dt"], y=eq["equity"], name="equity",
                   line=dict(color="#2E86AB", width=2)),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(x=eq["dt"], y=eq["dd"], name="drawdown",
                   fill="tozeroy", line=dict(color="#E63946", width=1),
                   fillcolor="rgba(230,57,70,0.25)"),
        row=2, col=1,
    )
    fig.update_yaxes(title_text="Equity", row=1, col=1)
    fig.update_yaxes(title_text="DD", tickformat=".1%", row=2, col=1)
    fig.update_layout(
        height=520, hovermode="x unified",
        showlegend=False, margin=dict(t=40, b=30, l=40, r=20),
    )
    tz_label = "KST" if use_kst else "UTC"
    fig.update_xaxes(title_text=f"time ({tz_label})", row=2, col=1)
    st.plotly_chart(fig, use_container_width=True)


def render_position_distribution(st, equity: pd.DataFrame) -> None:
    import plotly.express as px

    if equity.empty or "position" not in equity.columns:
        st.info("position 컬럼 없음")
        return
    dist = position_distribution(equity["position"])
    fig = px.bar(
        dist, x="position", y="fraction", text="fraction",
        color="position",
        color_discrete_map={
            "-1 (short)": "#E63946",
            "0 (flat)": "#888888",
            "+1 (long)": "#2A9D8F",
        },
    )
    fig.update_traces(texttemplate="%{text:.1%}", textposition="outside")
    fig.update_yaxes(tickformat=".0%", range=[0, 1])
    fig.update_layout(
        height=320, showlegend=False,
        margin=dict(t=20, b=30, l=40, r=20),
        title="Position time distribution",
    )
    st.plotly_chart(fig, use_container_width=True)


def render_trades_table(st, trades: pd.DataFrame, use_kst: bool) -> None:
    if trades.empty:
        st.info("No trades.")
        return
    df = annotate_trades(trades)
    if use_kst:
        for col in ("entry_ts_dt", "exit_ts_dt"):
            if col in df.columns:
                df[col] = to_kst(df[col])

    display_cols = []
    for c in ("side", "entry_ts_dt", "exit_ts_dt",
              "entry_price", "exit_price", "bars",
              "pnl_pct", "cum_pnl_pct"):
        if c in df.columns:
            display_cols.append(c)
    view = df[display_cols].copy()

    def _row_style(row: pd.Series) -> list[str]:
        if "pnl_pct" not in row.index:
            return [""] * len(row)
        v = row["pnl_pct"]
        try:
            v = float(v)
        except (TypeError, ValueError):
            return [""] * len(row)
        color = "background-color: rgba(42,157,143,0.18)" if v > 0 else (
                "background-color: rgba(230,57,70,0.18)" if v < 0 else "")
        return [color] * len(row)

    fmt: dict[str, Any] = {}
    if "entry_price" in view.columns:
        fmt["entry_price"] = "{:,.4f}"
    if "exit_price" in view.columns:
        fmt["exit_price"] = "{:,.4f}"
    if "pnl_pct" in view.columns:
        fmt["pnl_pct"] = "{:+.2%}"
    if "cum_pnl_pct" in view.columns:
        fmt["cum_pnl_pct"] = "{:+.2%}"

    styled = view.style.apply(_row_style, axis=1).format(fmt)
    st.dataframe(styled, use_container_width=True, height=420)


def render_config(st, run_dir: Path, cfg: dict[str, Any]) -> None:
    st.markdown(f"**Run:** `{run_dir.name}`")
    if not cfg:
        st.caption("config.yaml 없음 또는 비어있음")
        return
    summary_keys = [
        "strategy", "symbol", "interval", "start", "end",
        "fee_bps", "slippage_bps", "init_capital",
    ]
    for k in summary_keys:
        if k in cfg:
            st.write(f"- **{k}**: `{cfg[k]}`")
    if "params" in cfg:
        with st.expander("params"):
            st.json(cfg["params"])


def render_empty_state(st) -> None:
    st.warning("No runs yet.")
    st.code(
        "python -m backtest.engine.runner "
        "--strategy <name> --symbol BTCUSDT --interval 1h "
        "--start 2023-01-01 --end 2024-01-01",
        language="bash",
    )


def main() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="Backtest — Crypto",
        page_icon="📈",
        layout="wide",
    )
    st.title("Backtest 단일 런 뷰어")

    runs = list_runs()
    if not runs:
        render_empty_state(st)
        return

    with st.sidebar:
        st.header("Runs")
        labels = [p.name for p in runs]
        choice = st.selectbox("Select run (newest first)", labels, index=0)
        selected = runs[labels.index(choice)]

        cfg = load_config(selected)
        st.markdown("---")
        render_config(st, selected, cfg)

        st.markdown("---")
        use_kst = st.toggle("X축 KST 표시", value=True, help="OFF 시 UTC로 표시")

    metrics = load_metrics(selected)
    equity = load_equity(selected)
    trades = load_trades(selected)

    st.subheader("Metrics")
    render_metric_cards(st, metrics)

    st.markdown("---")
    st.subheader("Equity & Drawdown")
    render_equity_chart(st, equity, use_kst)

    col_l, col_r = st.columns([1, 2])
    with col_l:
        st.subheader("Position Distribution")
        render_position_distribution(st, equity)
    with col_r:
        st.subheader("Trades (last 100)")
        render_trades_table(st, trades, use_kst)


main()
