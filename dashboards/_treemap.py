"""KR 업종별 시가총액 트리맵 (Finviz 스타일 히트맵).

박스 크기 = 시가총액, 색 = 등락률(%). 업종(KSIC) 으로 그룹핑한다.

데이터 흐름 (읽기 전용):
  - 시총·등락률  : ``data/cache/kr/_live_snapshot.parquet`` (Naver 스냅샷)
  - 업종·종목명  : ``data/cache/kr/_sectors.parquet``      (FDR KRX-DESC, kr_sectors.py)

색 규칙: 빨강(하락) ~ 회색(보합) ~ 초록(상승) 발산형. 등락률은 ``clamp`` % 로
포화(기본 ±3%) — 소수 급등락주가 전체 스케일을 잡아먹지 않게.
업종 박스 색은 구성 종목의 **시총가중 평균 등락률**.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from data.sources.kr_sectors import load_sector_map, to_broad_sector, BROAD_ETC
from data.sources.naver_kr import load_snapshot

# Finviz 식 발산 색 스케일 (빨강 → 어두운 회색 → 초록)
_COLORSCALE = [
    [0.0, "#d6433b"],   # 강한 하락
    [0.25, "#8f3531"],
    [0.5, "#3a3f4b"],   # 보합 (0%)
    [0.75, "#2f7a44"],
    [1.0, "#2ecc71"],   # 강한 상승
]

LEVEL_SECTOR = "업종 합산"
LEVEL_STOCK = "업종 › 종목"
LEVELS = [LEVEL_STOCK, LEVEL_SECTOR]


def build_treemap_df() -> Optional[pd.DataFrame]:
    """스냅샷 + 업종맵 머지 → [code, name, industry, broad, mcap, change_pct].

    ``industry`` = KSIC 세부 업종(~161), ``broad`` = 굵직한 대분류(~22).
    우선주(끝자리≠0)는 KSIC 가 비어 있어, 모회사(끝자리 0) 업종을 상속한다.

    Returns None if 스냅샷이 없을 때. 업종맵이 없으면 업종을 '기타/미분류'로.
    """
    snap = load_snapshot()
    if snap is None or snap.empty:
        return None

    df = snap[["itemCode", "marketValue", "fluctuationsRatio"]].copy()
    df = df.rename(
        columns={
            "itemCode": "code",
            "marketValue": "mcap",
            "fluctuationsRatio": "change_pct",
        }
    )
    df["code"] = df["code"].astype(str).str.zfill(6)
    # fluctuationsRatio 는 분수(-0.1231 = -12.31%). 분포(min -0.26 / max +0.55,
    # mean -0.037)로 검증 — % 단위라면 하루 변동 ±0.5%로 비현실적. → ×100 해서 % 로.
    df["change_pct"] = pd.to_numeric(df["change_pct"], errors="coerce") * 100.0
    df["mcap"] = pd.to_numeric(df["mcap"], errors="coerce")
    df = df[(df["mcap"] > 0) & df["change_pct"].notna()]

    smap = load_sector_map()
    if smap is not None and not smap.empty:
        df = df.merge(smap[["code", "name", "industry"]], on="code", how="left")
    else:
        df["name"] = df["code"]
        df["industry"] = "기타/미분류"
    df["name"] = df["name"].fillna(df["code"])
    df["industry"] = df["industry"].fillna(BROAD_ETC)

    # 우선주(끝자리≠0) 는 KSIC 가 비어 '기타/미분류' 가 된다 — 모회사(끝자리 0)
    # 업종을 상속시켜 큰 '기타' 박스를 줄인다. (005935 삼성전자우 → 005930 삼성전자)
    code_to_ind = dict(zip(df["code"], df["industry"]))

    def _resolve(code: str, ind: str) -> str:
        if ind and ind != BROAD_ETC:
            return ind
        parent = code[:5] + "0"
        pind = code_to_ind.get(parent)
        if pind and pind != BROAD_ETC:
            return pind
        return ind or BROAD_ETC

    df["industry"] = [_resolve(c, i) for c, i in zip(df["code"], df["industry"])]
    df["broad"] = df["industry"].map(to_broad_sector)
    return df.reset_index(drop=True)


def _weighted_change(g: pd.DataFrame) -> float:
    """시총가중 평균 등락률."""
    w = g["mcap"].sum()
    if w <= 0:
        return float(g["change_pct"].mean())
    return float((g["change_pct"] * g["mcap"]).sum() / w)


def _fmt_won(v: float) -> str:
    """원 단위 시총을 조/억으로 컴팩트 표기."""
    if v >= 1e12:
        return f"{v / 1e12:,.1f}조"
    if v >= 1e8:
        return f"{v / 1e8:,.0f}억"
    return f"{v:,.0f}"


def make_treemap_fig(
    df: pd.DataFrame,
    level: str = LEVEL_STOCK,
    clamp: float = 3.0,
    min_mcap_eok: float = 0.0,
    top_n: int = 0,
    equal_size: bool = False,
    group_col: str = "broad",
):
    """Plotly Treemap Figure 생성.

    Args:
        df: build_treemap_df() 결과
        level: LEVEL_SECTOR(업종만) / LEVEL_STOCK(업종>종목)
        clamp: 색 포화 한계 % (±clamp 로 색 스케일 고정)
        min_mcap_eok: 이 시총(억원) 미만 종목 제외
        top_n: 0이면 전체, >0이면 시총 상위 N 종목만
        equal_size: True면 박스 크기를 시총과 무관하게 균일하게 (색만 등락률)
        group_col: 그룹핑 컬럼 — 'broad'(대분류 ~22) / 'industry'(KSIC 세부 ~161)
    """
    import plotly.graph_objects as go

    if group_col not in df.columns:
        group_col = "industry"

    work = df.copy()
    if min_mcap_eok > 0:
        work = work[work["mcap"] >= min_mcap_eok * 1e8]
    if top_n and top_n > 0:
        work = work.sort_values("mcap", ascending=False).head(int(top_n))
    if work.empty:
        return go.Figure()

    total_mcap = work["mcap"].sum()
    n_stocks = len(work)
    size_note = "크기 균일" if equal_size else "크기=시총"
    title = (
        f"KOSPI 업종별 시총 히트맵 · {n_stocks}종목 · "
        f"시총합 {total_mcap / 1e12:,.0f}조 · {size_note} · 색=등락률(±{clamp:g}% 포화)"
    )

    node_text = None  # stock 레벨에서만 per-node 텍스트 사용
    if level == LEVEL_SECTOR:
        agg = (
            work.groupby(group_col)
            .apply(lambda g: pd.Series({
                "mcap": g["mcap"].sum(),
                "change_pct": _weighted_change(g),
                "n": len(g),
                "n_up": int((g["change_pct"] > 0).sum()),
                "n_down": int((g["change_pct"] < 0).sum()),
            }))
            .reset_index()
        )
        for c in ("n", "n_up", "n_down"):
            agg[c] = agg[c].astype(int)
        labels = agg[group_col].tolist()
        parents = [""] * len(agg)
        values = [1.0] * len(agg) if equal_size else agg["mcap"].tolist()
        colors = agg["change_pct"].clip(-clamp, clamp).tolist()
        # customdata: [등락률, 시총합(원), 시총합 문자열, 종목수, 상승, 하락]
        custom = [
            [cp, mc, _fmt_won(mc), n, nu, nd]
            for cp, mc, n, nu, nd in zip(
                agg["change_pct"], agg["mcap"], agg["n"], agg["n_up"], agg["n_down"]
            )
        ]
        texttemplate = (
            "%{label}<br>%{customdata[2]} · %{customdata[3]}종목<br>"
            "▲%{customdata[4]} ▼%{customdata[5]} · %{customdata[0]:.1f}%"
        )
        hovertemplate = (
            "<b>%{label}</b><br>시총합 %{customdata[2]}<br>"
            "종목수 %{customdata[3]} (상승 %{customdata[4]} · 하락 %{customdata[5]})<br>"
            "가중 등락률 %{customdata[0]:.1f}%<extra></extra>"
        )
        ids = None
    else:
        # 업종(부모) + 종목(잎) 2단계.
        sec = (
            work.groupby(group_col)
            .apply(lambda g: pd.Series({
                "mcap": g["mcap"].sum(),
                "change_pct": _weighted_change(g),
                "n": len(g),
                "n_up": int((g["change_pct"] > 0).sum()),
                "n_down": int((g["change_pct"] < 0).sum()),
            }))
            .reset_index()
        )
        for c in ("n", "n_up", "n_down"):
            sec[c] = sec[c].astype(int)
        # 부모(업종) 노드 — branchvalues=remainder: 부모값 0 → 자식합으로 채움
        p_ids = ["sec::" + s for s in sec[group_col]]
        p_labels = sec[group_col].tolist()
        p_parents = [""] * len(sec)
        p_values = [0.0] * len(sec)
        p_colors = sec["change_pct"].clip(-clamp, clamp).tolist()
        # customdata 끝에 code 를 둬 클릭 식별에 사용 (부모=업종은 빈 문자열)
        p_custom = [
            [cp, mc, _fmt_won(mc), n, ""]
            for cp, mc, n in zip(sec["change_pct"], sec["mcap"], sec["n"])
        ]
        # 부모(업종) 박스 텍스트: 업종 · 시총 · N종목 · ▲상승 ▼하락 · 등락률
        p_text = [
            f"{lbl}<br>{_fmt_won(mc)} · {n}종목<br>▲{nu} ▼{nd} · {cp:.1f}%"
            for lbl, mc, n, nu, nd, cp in zip(
                sec[group_col], sec["mcap"], sec["n"],
                sec["n_up"], sec["n_down"], sec["change_pct"]
            )
        ]

        # 잎(종목) 노드 — id 충돌 방지로 code 사용
        c_ids = ["stk::" + c for c in work["code"]]
        c_labels = work["name"].tolist()
        c_parents = ["sec::" + s for s in work[group_col]]
        c_values = [1.0] * len(work) if equal_size else work["mcap"].tolist()
        c_colors = work["change_pct"].clip(-clamp, clamp).tolist()
        c_custom = [
            [cp, mc, _fmt_won(mc), 1, code]
            for cp, mc, code in zip(work["change_pct"], work["mcap"], work["code"])
        ]
        # 잎(종목) 박스 텍스트: 종목명 · 시총 · 등락률
        c_text = [
            f"{nm}<br>{_fmt_won(mc)}<br>{cp:.1f}%"
            for nm, mc, cp in zip(work["name"], work["mcap"], work["change_pct"])
        ]

        ids = p_ids + c_ids
        labels = p_labels + c_labels
        parents = p_parents + c_parents
        values = p_values + c_values
        colors = p_colors + c_colors
        custom = p_custom + c_custom
        node_text = p_text + c_text
        # 부모/잎 라벨 내용이 달라 per-node text 로 직접 구성 (template 공유 불가).
        texttemplate = "%{text}"
        hovertemplate = (
            "<b>%{label}</b><br>시총 %{customdata[2]}<br>"
            "등락률 %{customdata[0]:.1f}%<extra></extra>"
        )

    fig = go.Figure(
        go.Treemap(
            ids=ids,
            labels=labels,
            parents=parents,
            values=values,
            text=node_text,
            customdata=custom,
            branchvalues="remainder",
            texttemplate=texttemplate,
            hovertemplate=hovertemplate,
            marker=dict(
                colors=colors,
                colorscale=_COLORSCALE,
                cmid=0,
                cmin=-clamp,
                cmax=clamp,
                colorbar=dict(title="등락률 %", ticksuffix="%"),
                line=dict(width=1, color="#11141a"),
            ),
            tiling=dict(pad=2),
            textposition="middle center",
            textfont=dict(size=13),
            sort=True,
        )
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=15)),
        margin=dict(t=46, l=4, r=4, b=4),
        paper_bgcolor="#0e1117",
        font=dict(color="#e6e6e6"),
        height=760,
    )
    return fig


def clicked_code(event, df: pd.DataFrame):
    """st.plotly_chart(on_select=...) 이벤트에서 클릭된 종목 (code, name) 추출.

    종목(잎) 박스를 눌렀을 때만 코드를 반환. 업종(부모) 박스/빈 클릭이면 (None, None).
    식별 우선순위: customdata 끝 code → node id('stk::CODE') → 종목명 매칭.
    """
    if not event:
        return None, None
    sel = event.get("selection") if isinstance(event, dict) else getattr(event, "selection", None)
    points = (sel or {}).get("points") or []
    if not points:
        return None, None
    p = points[-1]
    code = None
    cd = p.get("customdata")
    if isinstance(cd, (list, tuple)) and cd:
        cand = str(cd[-1])
        if cand.isdigit() and len(cand) == 6:
            code = cand
    if not code:
        pid = p.get("id") or ""
        if isinstance(pid, str) and pid.startswith("stk::"):
            code = pid[5:]
    if not code:
        lbl = p.get("label")
        if lbl is not None:
            m = df[df["name"] == lbl]
            if len(m) == 1:
                code = str(m.iloc[0]["code"])
    if not code:
        return None, None
    row = df[df["code"] == code]
    name = str(row.iloc[0]["name"]) if len(row) else code
    return code, name


def make_stock_candle_fig(code: str, name: str, days: int = 180):
    """선택 종목의 일반 주식차트 (캔들 + 이평선 + 거래량).

    프로젝트 공용 캔들 빌더 :func:`dashboards.charts.plot_ohlcv` 재사용
    (KR 대문자 컬럼·주말 갭 자동 처리). 데이터 없으면 None.
    """
    from dashboards.charts import plot_ohlcv
    from data.loader import load_ohlcv

    try:
        d = load_ohlcv("kr", code, "1d")
    except Exception:  # noqa: BLE001
        return None
    if d is None or d.empty:
        return None
    d = d.tail(int(days))
    fig = plot_ohlcv(
        d,
        title=f"{name} ({code}) · 일봉 {len(d)}일",
        ma_periods=(10, 20, 60),
        vwma_periods=(),
        show_volume=True,
        height=480,
        skip_weekends=True,
    )
    fig.update_layout(margin=dict(t=40, l=4, r=4, b=4))
    return fig


def make_stock_change_fig(code: str, name: str, days: int = 30):
    """선택 종목의 최근 N거래일 일변동·누적변동 라인차트.

    - 일변동(%)   : 전일 대비 종가 변동률 (보조 y축)
    - 누적변동(%) : 구간 첫날 대비 누적 변동률 (주 y축, 0%에서 시작)

    데이터 없으면 None.
    """
    from plotly.subplots import make_subplots
    import plotly.graph_objects as go

    from data.loader import load_ohlcv

    try:
        d = load_ohlcv("kr", code, "1d")
    except Exception:  # noqa: BLE001
        return None
    if d is None or d.empty:
        return None
    d = d.tail(int(days))
    if len(d) < 2:
        return None

    close = d["Close"].astype(float)
    daily = close.pct_change().fillna(0.0) * 100.0
    cum = (close / close.iloc[0] - 1.0) * 100.0
    x = d.index

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=x, y=cum, name="누적변동 %", mode="lines",
            line=dict(color="#2ecc71", width=2.4),
            fill="tozeroy", fillcolor="rgba(46,204,113,0.10)",
            hovertemplate="%{x|%m/%d}<br>누적 %{y:+.1f}%<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=daily, name="일변동 %", mode="lines+markers",
            line=dict(color="#f1c40f", width=1.4),
            marker=dict(size=4),
            hovertemplate="%{x|%m/%d}<br>일변동 %{y:+.1f}%<extra></extra>",
        ),
        secondary_y=True,
    )
    fig.add_hline(y=0, line=dict(color="#555", width=1), secondary_y=False)

    total = float(cum.iloc[-1])
    fig.update_layout(
        title=dict(text=f"{name} ({code}) · 최근 {len(d)}거래일 · 누적 {total:+.1f}%",
                   font=dict(size=14)),
        margin=dict(t=40, l=4, r=4, b=4),
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        font=dict(color="#e6e6e6"),
        height=340,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="누적변동 %", ticksuffix="%", gridcolor="#222",
                     zeroline=False, secondary_y=False)
    fig.update_yaxes(title_text="일변동 %", ticksuffix="%", showgrid=False,
                     zeroline=False, secondary_y=True)
    fig.update_xaxes(gridcolor="#222")
    return fig
