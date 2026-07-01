"""시총맵 — Crypto / KOSPI / NASDAQ 3자산 시가총액 트리맵.

Live 탭과 같은 3-탭 구조. 박스 크기 = 시가총액, 색 = 등락률(%).

현재 실구현 상태:
  - **KOSPI**  : ✅ 스냅샷 + 업종(KSIC) 매핑 모두 있음. Finviz 스타일 트리맵.
  - **Crypto** : ⏳ 스냅샷 O, 그룹핑용 ``classification.parquet`` 필요 (``/crypto-classify``).
  - **NASDAQ** : ⏳ 스냅샷 O, 섹터(GICS) 매핑 fetcher 미구현.

빌더/그림 로직은 :mod:`dashboards._treemap`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboards._lib import render_fetch_log_sidebar  # noqa: E402
from dashboards._treemap import (  # noqa: E402
    build_treemap_df,
    clicked_code,
    make_stock_candle_fig,
    make_stock_change_fig,
    make_treemap_fig,
)

_KR_CACHE = _ROOT / "data" / "cache" / "kr"
_LISTING_CSV = _KR_CACHE / "_listing.csv"
_KR_SECTORS_PARQUET = _KR_CACHE / "_sectors.parquet"
_KR_SNAPSHOT_PARQUET = _KR_CACHE / "_live_snapshot.parquet"

_US_CACHE = _ROOT / "data" / "cache" / "us"
_US_SNAPSHOT_PARQUET = _US_CACHE / "_live_snapshot.parquet"
_US_SECTORS_PARQUET = _US_CACHE / "_sectors.parquet"

_CRYPTO_CACHE = _ROOT / "data" / "cache" / "crypto"
_CRYPTO_SNAPSHOT_PARQUET = _CRYPTO_CACHE / "_live_snapshot.parquet"
_CRYPTO_CLASSIFICATION_PARQUET = _CRYPTO_CACHE / "classification.parquet"


def _mtime_kst(p: Path) -> Optional[str]:
    if not p.exists():
        return None
    return pd.Timestamp.fromtimestamp(p.stat().st_mtime, tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M")


def _load_stock_whitelist() -> Optional[set]:
    """``_listing.csv`` 의 KOSPI 보통주/우선주 코드 — ETF/ETN/REIT 노이즈 제거용."""
    if not _LISTING_CSV.exists():
        return None
    try:
        df = pd.read_csv(_LISTING_CSV, dtype={"Symbol": str}, usecols=["Symbol"])
    except Exception:  # noqa: BLE001
        return None
    return set(df["Symbol"].dropna().astype(str).str.zfill(6))


def _render_kospi(st) -> None:
    # 스냅샷·업종맵 mtime — 언제 데이터인지 최소 정보만 상단에 얇게 표시.
    snap_mt = _mtime_kst(_KR_SNAPSHOT_PARQUET)
    sec_mt = _mtime_kst(_KR_SECTORS_PARQUET)
    parts = []
    if snap_mt:
        parts.append(f"📡 스냅샷 {snap_mt}")
    else:
        parts.append("📡 스냅샷 없음 — Live 탭에서 갱신")
    if sec_mt:
        parts.append(f"🏷️ 업종맵 {sec_mt}")
    else:
        parts.append("🏷️ 업종맵 미생성 — `python -m data.sources.kr_sectors`")
    st.caption("  ·  ".join(parts))

    # ── 컨트롤 ──
    # 색 포화는 ±5% 로 고정 — 실전상 대부분 종목이 이 범위에 들어와 있고,
    # 소수 급등락주로 스케일이 밀리지 않게 하는 최적점.
    clamp = 5.0
    c1, c2, c3 = st.columns([1.6, 1.8, 2])
    with c1:
        top_n = st.number_input("시총 상위 N (0=전체)", min_value=0, max_value=2500,
                                value=200, step=50, key="map_kr_topn")
    with c2:
        gran = st.radio("분류", ["대분류", "세부(KSIC)"], horizontal=True, key="map_kr_gran",
                        help="대분류=반도체·2차전지·금융 등 ~22개로 묶음. 세부=KSIC 원본 ~129개.")
    with c3:
        stock_only = st.checkbox("일반 종목만 (ETF/ETN/REIT 제외)",
                                 value=True, key="map_kr_stock_only")
        equal_size = st.checkbox("박스 크기 균일", value=True, key="map_kr_equal",
                                 help="끄면 박스 크기 = 시가총액. 켜면 모두 같은 크기 (색만 등락률).")
    group_col = "broad" if gran == "대분류" else "industry"

    df = build_treemap_df()
    if df is None or df.empty:
        st.info(
            "📡 라이브 스냅샷 없음 — **Live 탭 → KOSPI 탭 → `라이브 가격 갱신`** 으로 먼저 받아주세요. "
            "(또는 CLI: `.venv/Scripts/python.exe -m data.sources.naver_kr`)"
        )
        return

    if stock_only:
        wl = _load_stock_whitelist()
        if wl is not None:
            df = df[df["code"].isin(wl)].reset_index(drop=True)

    fig = make_treemap_fig(df, clamp=float(clamp), top_n=int(top_n),
                           equal_size=bool(equal_size), group_col=group_col)
    # 맵 구성이 바뀌면 위젯을 remount (선택 상태 초기화). on_select 로 클릭 캡처.
    map_key = f"map_kr_tree::{group_col}::{equal_size}::{int(top_n)}::{stock_only}"
    event = st.plotly_chart(
        fig, use_container_width=True, theme=None,
        on_select="rerun", selection_mode="points", key=map_key,
    )

    # 클릭된 종목(잎 박스)이면 세션에 저장 — 다른 컨트롤을 만져도 차트 유지.
    code, name = clicked_code(event, df)
    if code:
        st.session_state["map_kr_sel_code"] = code
        st.session_state["map_kr_sel_name"] = name

    st.caption(
        "💡 초기 화면은 **업종 합산** (색 = 구성 종목 시총가중 평균 등락률). "
        "**업종 박스를 클릭**하면 그 안의 종목들로 확장되고, 다시 **종목 박스를 클릭**하면 "
        "아래에 최근 30일 일변동·누적변동 차트가 뜹니다. 상단 breadcrumb 로 뒤로. "
        "박스 크기 = 시가총액, 색 = 등락률 (초록 상승 · 빨강 하락)."
    )

    # ── 선택 종목 30일 변동 차트 ──
    sel_code = st.session_state.get("map_kr_sel_code")
    if sel_code:
        sel_name = st.session_state.get("map_kr_sel_name", sel_code)
        hdr, ctype, btn = st.columns([5, 2, 1])
        with hdr:
            st.subheader(f"📈 {sel_name} ({sel_code})")
        with ctype:
            chart_type = st.radio(
                "차트", ["캔들", "라인(변동)"], horizontal=True,
                key="map_kr_chart_type", label_visibility="collapsed",
            )
        with btn:
            if st.button("✕ 닫기", key="map_kr_chart_close", use_container_width=True):
                st.session_state.pop("map_kr_sel_code", None)
                st.session_state.pop("map_kr_sel_name", None)
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


def _render_crypto(st) -> None:
    snap_mt = _mtime_kst(_CRYPTO_SNAPSHOT_PARQUET)
    cls_mt = _mtime_kst(_CRYPTO_CLASSIFICATION_PARQUET)
    parts = []
    parts.append(f"📡 스냅샷 {snap_mt}" if snap_mt else "📡 스냅샷 없음 — Live 탭에서 갱신")
    parts.append(f"🏷️ 분류 {cls_mt}" if cls_mt else "🏷️ 분류 미생성 — `/crypto-classify`")
    st.caption("  ·  ".join(parts))
    st.info(
        "⏳ **Crypto 시총맵은 아직 구현 전.** 크립토는 '업종' 개념이 없어서 "
        "`data/cache/crypto/classification.parquet` 의 `tier_final` (trend / follower / whale / junk) "
        "로 그룹핑할 예정. 먼저 `/crypto-classify` 를 실행해 분류 파일을 만든 뒤 별도 세션에서 "
        "빌더 구현 예정."
    )


def _render_nasdaq(st) -> None:
    snap_mt = _mtime_kst(_US_SNAPSHOT_PARQUET)
    sec_mt = _mtime_kst(_US_SECTORS_PARQUET)
    parts = []
    parts.append(f"📡 스냅샷 {snap_mt}" if snap_mt else "📡 스냅샷 없음 — Live 탭에서 갱신")
    parts.append(f"🏷️ 섹터맵 {sec_mt}" if sec_mt else "🏷️ 섹터맵(GICS) fetcher 미구현")
    st.caption("  ·  ".join(parts))
    st.info(
        "⏳ **NASDAQ 시총맵은 아직 구현 전.** 라이브 스냅샷은 있지만 티커→GICS 섹터 매핑 "
        "fetcher (`data/sources/us_sectors.py` 같은) 가 없어서 그룹핑 불가. "
        "yfinance / NASDAQ screener CSV 중 어느 소스로 받을지 정해지면 별도 세션에서 구현 예정."
    )


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="시총맵", page_icon="🗺️", layout="wide")
    render_fetch_log_sidebar(st)

    tab_crypto, tab_kospi, tab_nasdaq = st.tabs(["Crypto", "KOSPI", "NASDAQ"])
    with tab_crypto:
        _render_crypto(st)
    with tab_kospi:
        _render_kospi(st)
    with tab_nasdaq:
        _render_nasdaq(st)


main()
