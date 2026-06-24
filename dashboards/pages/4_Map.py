"""시총맵 — KOSPI 업종별 시가총액 트리맵 (Finviz 스타일 히트맵).

박스 크기 = 시가총액, 색 = 등락률(%). 업종(KSIC) 으로 그룹핑.

데이터는 모두 디스크 캐시에서 읽기만 한다:
  - 시총·등락률 : ``data/cache/kr/_live_snapshot.parquet`` (Naver 스냅샷)
  - 업종·종목명 : ``data/cache/kr/_sectors.parquet``      (FDR KRX-DESC)

스냅샷이 옛 값이면 사이드바/상단의 `라이브 가격 갱신` 으로 먼저 받는다.
빌더/그림 로직은 :mod:`dashboards._treemap`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.sources.naver_kr import SNAPSHOT_PATH  # noqa: E402
from dashboards._lib import render_fetch_log_sidebar  # noqa: E402
from dashboards._treemap import (  # noqa: E402
    LEVEL_SECTOR,
    LEVEL_STOCK,
    LEVELS,
    build_treemap_df,
    clicked_code,
    make_stock_candle_fig,
    make_stock_change_fig,
    make_treemap_fig,
)
from dashboards.live._common import (  # noqa: E402
    python_module_args,
    render_subprocess_launcher,
    render_subprocess_status,
    snapshot_age_caption,
)

_CACHE_DIR = _ROOT / "data" / "cache" / "kr"
_LIVE_LOG = _CACHE_DIR / "_live_fetch.log"
_LISTING_CSV = _CACHE_DIR / "_listing.csv"
_SECTORS_PARQUET = _CACHE_DIR / "_sectors.parquet"


def _load_stock_whitelist() -> Optional[set]:
    """``_listing.csv`` 의 KOSPI 보통주/우선주 코드 — ETF/ETN/REIT 노이즈 제거용."""
    if not _LISTING_CSV.exists():
        return None
    try:
        df = pd.read_csv(_LISTING_CSV, dtype={"Symbol": str}, usecols=["Symbol"])
    except Exception:  # noqa: BLE001
        return None
    return set(df["Symbol"].dropna().astype(str).str.zfill(6))


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="시총맵", page_icon="🗺️", layout="wide")
    render_fetch_log_sidebar(st)

    st.title("🗺️ KOSPI 시총맵")

    # ── 상단 툴바: 스냅샷 시각 + 라이브 갱신 + 업종 캐시 갱신 ──
    bar_cap, bar_live, bar_sec = st.columns([3, 2, 2])
    with bar_cap:
        st.caption(snapshot_age_caption(SNAPSHOT_PATH))
        if _SECTORS_PARQUET.exists():
            mt = pd.Timestamp.fromtimestamp(
                _SECTORS_PARQUET.stat().st_mtime, tz="Asia/Seoul"
            )
            st.caption(f"🏷️ 업종맵 {mt.strftime('%Y-%m-%d %H:%M')}")
        else:
            st.caption("🏷️ 업종맵 미생성 — `업종맵 갱신`")
    with bar_live:
        render_subprocess_launcher(
            st,
            label="라이브 가격 갱신",
            session_prefix="map_live",
            log_path=_LIVE_LOG,
            args=python_module_args("data.sources.naver_kr"),
            cwd=_ROOT,
            button_key="map_live_btn",
            button_help="Naver 비공식 endpoint로 KOSPI 라이브 시세를 받아 스냅샷 갱신. 백그라운드.",
        )
    with bar_sec:
        if st.button("🏷️ 업종맵 갱신", key="map_sec_btn",
                     help="FDR KRX-DESC 에서 업종(KSIC) 매핑을 다시 받아 캐시. 수 초 소요."):
            from data.sources.kr_sectors import refresh as refresh_sectors
            with st.spinner("업종맵 갱신 중…"):
                m = refresh_sectors()
            st.success(f"✅ {len(m)}종목 / {m['industry'].nunique()}업종 갱신")

    render_subprocess_status(
        st,
        label="라이브 fetch",
        session_prefix="map_live",
        log_path=_LIVE_LOG,
        success_msg="✅ 라이브 fetch 완료",
        error_msg="❌ 라이브 fetch 실패",
    )

    # ── 컨트롤 ──
    c1, c2, c3, c4, c5 = st.columns([2, 2, 1.6, 1.6, 2])
    with c1:
        level = st.radio("그룹 단위", LEVELS, horizontal=True, key="map_level")
    with c2:
        clamp = st.slider("색 포화 ±%", min_value=1.0, max_value=15.0,
                          value=5.0, step=0.5, key="map_clamp",
                          help="이 값(±%) 에서 색이 최대 채도. 소수 급등락주가 스케일을 잡아먹지 않게.")
    with c3:
        gran = st.radio("분류", ["대분류", "세부(KSIC)"], horizontal=True, key="map_gran",
                        help="대분류=반도체·2차전지·금융 등 ~22개로 묶음. 세부=KSIC 원본 ~129개.")
        group_col = "broad" if gran == "대분류" else "industry"
        equal_size = st.checkbox("박스 크기 균일", value=True, key="map_equal",
                                 help="끄면 박스 크기 = 시가총액. 켜면 모두 같은 크기 (색만 등락률).")
    with c4:
        top_n = st.number_input("시총 상위 N (0=전체)", min_value=0, max_value=2500,
                                value=0, step=50, key="map_topn")
    with c5:
        stock_only = st.checkbox("일반 종목만 (ETF/ETN/REIT 제외)",
                                 value=True, key="map_stock_only")

    df = build_treemap_df()
    if df is None or df.empty:
        st.info(
            "📡 라이브 스냅샷 없음 — 위 `라이브 가격 갱신` 으로 먼저 받아주세요. "
            "(KOSPI bulk endpoint, ~5초)"
        )
        return

    if stock_only:
        wl = _load_stock_whitelist()
        if wl is not None:
            df = df[df["code"].isin(wl)].reset_index(drop=True)

    fig = make_treemap_fig(df, level=level, clamp=float(clamp), top_n=int(top_n),
                           equal_size=bool(equal_size), group_col=group_col)
    # 맵 구성이 바뀌면 위젯을 remount (선택 상태 초기화). on_select 로 클릭 캡처.
    map_key = f"map_tree::{level}::{group_col}::{equal_size}::{int(top_n)}::{stock_only}"
    event = st.plotly_chart(
        fig, use_container_width=True, theme=None,
        on_select="rerun", selection_mode="points", key=map_key,
    )

    # 클릭된 종목(잎 박스)이면 세션에 저장 — 다른 컨트롤을 만져도 차트 유지.
    code, name = clicked_code(event, df)
    if code:
        st.session_state["map_sel_code"] = code
        st.session_state["map_sel_name"] = name

    if level == LEVEL_STOCK:
        st.caption(
            "💡 **종목 박스를 클릭**하면 아래에 최근 30일 일변동·누적변동 차트가 뜹니다. "
            "박스 크기 = 시가총액, 색 = 등락률 (초록 상승 · 빨강 하락)."
        )
    else:
        st.caption(
            "💡 업종 박스 색 = 구성 종목 **시총가중 평균 등락률**. "
            f"종목별 차트를 보려면 `{LEVEL_STOCK}` 모드로 바꿔 종목 박스를 클릭하세요."
        )

    # ── 선택 종목 30일 변동 차트 ──
    sel_code = st.session_state.get("map_sel_code")
    if sel_code:
        sel_name = st.session_state.get("map_sel_name", sel_code)
        hdr, ctype, btn = st.columns([5, 2, 1])
        with hdr:
            st.subheader(f"📈 {sel_name} ({sel_code})")
        with ctype:
            chart_type = st.radio(
                "차트", ["캔들", "라인(변동)"], horizontal=True,
                key="map_chart_type", label_visibility="collapsed",
            )
        with btn:
            if st.button("✕ 닫기", key="map_chart_close", use_container_width=True):
                st.session_state.pop("map_sel_code", None)
                st.session_state.pop("map_sel_name", None)
                st.rerun()
        if chart_type == "캔들":
            cfig = make_stock_candle_fig(sel_code, sel_name, days=180)
        else:
            cfig = make_stock_change_fig(sel_code, sel_name, days=30)
        if cfig is None:
            st.warning(
                f"`{sel_code}` 일봉 캐시 없음 — `KOSPI 데이터 받기`(Live 탭)로 먼저 받아주세요."
            )
        else:
            st.plotly_chart(cfig, use_container_width=True, theme=None)


main()
