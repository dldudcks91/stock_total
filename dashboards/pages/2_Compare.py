"""Multi-run comparison page.

Pick 2 or more run directories from the sidebar and the body shows:
    - mismatch warnings (strategy/symbol/interval differ)
    - metrics table (rows=runs, cols=METRIC_KEYS)
    - equity overlay (one curve per run, optional normalize-to-1.0)
    - drawdown overlay
    - config diff table (only keys whose values differ across runs)
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
    config_diff_table,
    metrics_table,
    detect_mismatches,
    fmt_metric,
    METRIC_KEYS,
    PCT_METRICS,
    INT_METRICS,
)
from dashboards._cache import load_config, load_metrics, load_equity


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_metrics_section(st, runs_metrics: dict[str, dict[str, Any]]) -> None:
    raw = metrics_table(runs_metrics)
    if raw.empty:
        st.info("선택된 런에 metrics.json 데이터가 없습니다.")
        return

    # Display version: format each cell per metric type.
    display = raw.copy()
    for col in display.columns:
        display[col] = display[col].apply(lambda v, c=col: fmt_metric(c, v))

    st.dataframe(display, use_container_width=True)

    # Delta vs first row, only for numeric metrics.
    if len(raw) >= 2:
        baseline_label = raw.index[0]
        delta_rows: dict[str, dict[str, Any]] = {}
        for label in raw.index[1:]:
            row: dict[str, Any] = {}
            for col in raw.columns:
                a = raw.loc[baseline_label, col]
                b = raw.loc[label, col]
                try:
                    d = float(b) - float(a)
                except (TypeError, ValueError):
                    row[col] = "—"
                    continue
                if col in PCT_METRICS:
                    sign = "+" if d >= 0 else ""
                    row[col] = f"{sign}{d * 100:.2f} pp"
                elif col in INT_METRICS:
                    sign = "+" if d >= 0 else ""
                    row[col] = f"{sign}{int(d):,}"
                else:
                    sign = "+" if d >= 0 else ""
                    row[col] = f"{sign}{d:.3f}"
            delta_rows[f"Δ ({label} − {baseline_label})"] = row
        delta_df = pd.DataFrame.from_dict(delta_rows, orient="index", columns=raw.columns)
        st.markdown(f"**Delta vs `{baseline_label}` (baseline)**")
        st.caption("pp = percentage point. 단위 비교는 메트릭 종류에 따라 다름.")
        st.dataframe(delta_df, use_container_width=True)


def _prepare_runs(
    runs_equity: dict[str, pd.DataFrame], use_kst: bool,
) -> list[tuple[str, pd.Series, pd.Series, pd.Series]]:
    """One-pass conversion: returns (label, x, equity, drawdown) per non-empty run."""
    out = []
    for label, eq in runs_equity.items():
        if eq.empty:
            continue
        dt_utc = to_utc_datetime(eq["timestamp"])
        x = to_kst(dt_utc) if use_kst else dt_utc
        equity = eq["equity"].astype(float)
        dd = compute_drawdown(equity)
        out.append((label, x, equity, dd))
    return out


def render_equity_overlay(
    st,
    prepared: list[tuple[str, pd.Series, pd.Series, pd.Series]],
    use_kst: bool,
    normalize: bool,
) -> None:
    import plotly.graph_objects as go

    if not prepared:
        st.info("equity 데이터가 없습니다.")
        return

    fig = go.Figure()
    palette = ["#2E86AB", "#E63946", "#2A9D8F", "#F4A261", "#8338EC", "#264653"]
    for i, (label, x, equity, _dd) in enumerate(prepared):
        y = equity
        if normalize and len(y) > 0 and float(y.iloc[0]) != 0:
            y = y / float(y.iloc[0])
        fig.add_trace(go.Scatter(
            x=x, y=y, name=label, mode="lines",
            line=dict(width=1.8, color=palette[i % len(palette)]),
            hovertemplate=f"<b>{label}</b><br>%{{x}}<br>%{{y:.4f}}<extra></extra>",
        ))

    y_title = "Equity (normalized, start=1)" if normalize else "Equity"
    fig.update_layout(
        height=480,
        hovermode="x unified",
        margin=dict(t=30, b=30, l=40, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_yaxes(title_text=y_title)
    tz_label = "KST" if use_kst else "UTC"
    fig.update_xaxes(title_text=f"time ({tz_label})")
    st.plotly_chart(fig, use_container_width=True)


def render_drawdown_overlay(
    st,
    prepared: list[tuple[str, pd.Series, pd.Series, pd.Series]],
    use_kst: bool,
) -> None:
    import plotly.graph_objects as go

    if not prepared:
        return

    fig = go.Figure()
    palette = ["#2E86AB", "#E63946", "#2A9D8F", "#F4A261", "#8338EC", "#264653"]
    for i, (label, x, _equity, dd) in enumerate(prepared):
        fig.add_trace(go.Scatter(
            x=x, y=dd, name=label, mode="lines",
            line=dict(width=1.4, color=palette[i % len(palette)]),
            hovertemplate=f"<b>{label}</b><br>%{{x}}<br>%{{y:.2%}}<extra></extra>",
        ))

    fig.update_layout(
        height=320,
        hovermode="x unified",
        margin=dict(t=30, b=30, l=40, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_yaxes(title_text="Drawdown", tickformat=".1%")
    tz_label = "KST" if use_kst else "UTC"
    fig.update_xaxes(title_text=f"time ({tz_label})")
    st.plotly_chart(fig, use_container_width=True)


def render_config_diff(st, configs: dict[str, dict[str, Any]]) -> None:
    diff = config_diff_table(configs)
    if diff.empty:
        st.success("Config 가 모든 런에서 동일합니다 (diff 없음).")
        return
    st.dataframe(diff, use_container_width=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="Compare — Crypto Backtest",
        page_icon="🔀",
        layout="wide",
    )
    st.title("멀티 런 비교")

    runs = list_runs()
    if not runs:
        st.warning("No runs yet. 먼저 백테스트를 실행하세요.")
        return

    name_to_path: dict[str, Path] = {p.name: p for p in runs}
    all_names = list(name_to_path.keys())

    with st.sidebar:
        st.header("Runs")
        default = all_names[: min(2, len(all_names))]
        chosen = st.multiselect(
            "비교할 런 선택 (2개 이상)",
            options=all_names,
            default=default,
            help="첫 번째로 선택한 런이 delta 의 baseline 입니다.",
        )
        st.markdown("---")
        use_kst = st.toggle("X축 KST 표시", value=True, help="OFF 시 UTC")
        normalize = st.toggle(
            "Equity 정규화 (start=1.0)",
            value=True,
            help="init_capital 이나 심볼이 달라도 비교 가능하도록 시작값을 1.0 으로 맞춤",
        )

    if len(chosen) < 2:
        st.info("런을 2개 이상 선택해주세요.")
        return

    selected_paths = {name: name_to_path[name] for name in chosen}
    configs = {name: load_config(p) for name, p in selected_paths.items()}
    runs_metrics = {name: load_metrics(p) for name, p in selected_paths.items()}
    runs_equity = {name: load_equity(p) for name, p in selected_paths.items()}

    warnings = detect_mismatches(configs)
    if warnings:
        for w in warnings:
            st.warning(w)
        st.caption("의도된 비교가 맞는지 확인하세요. 같은 심볼/전략/인터벌끼리 비교하면 더 의미 있습니다.")

    st.markdown("---")
    st.subheader("Metrics")
    render_metrics_section(st, runs_metrics)

    prepared = _prepare_runs(runs_equity, use_kst)

    st.markdown("---")
    st.subheader("Equity Overlay")
    render_equity_overlay(st, prepared, use_kst, normalize)

    st.markdown("---")
    st.subheader("Drawdown Overlay")
    render_drawdown_overlay(st, prepared, use_kst)

    st.markdown("---")
    st.subheader("Config Diff (다른 키만)")
    render_config_diff(st, configs)


main()
