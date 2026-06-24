"""KR 종목 → 업종(KSIC) 매핑 캐시.

FDR ``KRX-DESC`` 의 ``Industry`` 컬럼(한국표준산업분류, ~161개 업종)을 종목 코드에
붙여 ``data/cache/kr/_sectors.parquet`` 로 저장한다. 트리맵 / 업종별 집계의 입력.

왜 별도 캐시인가:
- ``KRX-DESC`` 호출은 수 초 걸리고 매 대시보드 렌더마다 부르면 느리다.
- live_snapshot 의 ``stockName`` 은 cp949 깨짐이 있어, 깨끗한 한글 종목명도 여기서 받는다.

``Sector`` 컬럼은 업종이 아니라 시장구분(우량기업부/벤처기업부/SPAC 등)이라 쓰지 않는다.

CLI:
    .venv/Scripts/python.exe -m data.sources.kr_sectors          # 캐시 갱신
    .venv/Scripts/python.exe -m data.sources.kr_sectors --show   # 상위 업종 출력
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = _ROOT / "data" / "cache" / "kr" / "_sectors.parquet"

# 산출 컬럼: code(6자리), name(한글), industry(KSIC 업종명)
_COLS = ["code", "name", "industry"]

# KSIC 세부 업종(~161개) → 굵직한 대분류(~22개) 매핑.
# (부분문자열, 대분류) 순서대로 검사 — 먼저 매치되는 규칙이 이김. 순서 중요.
BROAD_RULES = [
    ("반도체", "반도체"),
    # 전기·2차전지 (배터리·전선·전동기) — IT/전자부품보다 먼저
    ("이차전지", "전기·2차전지"), ("일차전지", "전기·2차전지"),
    ("전동기", "전기·2차전지"), ("전기 변환", "전기·2차전지"),
    ("절연선", "전기·2차전지"), ("케이블", "전기·2차전지"),
    ("전기장비", "전기·2차전지"), ("전구", "전기·2차전지"), ("조명", "전기·2차전지"),
    # 자동차 (제조·부품·판매 모두)
    ("자동차", "자동차"),
    # 방산·조선·기타 운송장비
    ("선박", "방산·조선"), ("보트", "방산·조선"),
    ("항공기", "방산·조선"), ("우주선", "방산·조선"),
    ("무기", "방산·조선"), ("총포탄", "방산·조선"),
    ("운송장비 제조", "방산·조선"),
    # 건설·건자재 (공사업/요업/유리 등) — '전기업' 같은 유틸보다 먼저
    ("공사업", "건설·건자재"), ("건설", "건설·건자재"), ("건축", "건설·건자재"),
    ("토목", "건설·건자재"), ("시멘트", "건설·건자재"), ("요업", "건설·건자재"),
    ("유리", "건설·건자재"), ("비금속 광물", "건설·건자재"), ("기반조성", "건설·건자재"),
    # 유통·도소매 (도매/소매/판매/중개) — 자동차 다음
    ("도매", "유통"), ("소매", "유통"), ("판매업", "유통"), ("중개업", "유통"),
    # 제약·바이오
    ("의약", "제약·바이오"), ("의료용", "제약·바이오"), ("연구개발", "제약·바이오"),
    # 화학
    ("화학", "화학"), ("석유 정제", "화학"), ("비료", "화학"), ("농약", "화학"),
    ("고무", "화학"), ("플라스틱", "화학"),
    # 철강·금속
    ("철강", "철강·금속"), ("비철금속", "철강·금속"), ("금속 주조", "철강·금속"),
    ("금속 가공", "철강·금속"), ("구조용 금속", "철강·금속"), ("귀금속", "철강·금속"),
    # 기계
    ("기계", "기계"),
    # 음식료·담배
    ("식품", "음식료·담배"), ("곡물", "음식료·담배"), ("음료", "음식료·담배"),
    ("수산물 가공", "음식료·담배"), ("유지", "음식료·담배"), ("낙농", "음식료·담배"),
    ("도축", "음식료·담배"), ("떡", "음식료·담배"), ("사료", "음식료·담배"),
    ("담배 제조", "음식료·담배"), ("음식점", "음식료·담배"), ("알코올", "음식료·담배"),
    # 섬유·의류
    ("의복", "섬유·의류"), ("직물", "섬유·의류"), ("방적", "섬유·의류"),
    ("가죽", "섬유·의류"), ("가방", "섬유·의류"), ("신발", "섬유·의류"),
    ("편조", "섬유·의류"), ("봉제", "섬유·의류"),
    # 종이·목재·가구
    ("펄프", "종이·목재·가구"), ("종이", "종이·목재·가구"), ("판지", "종이·목재·가구"),
    ("골판지", "종이·목재·가구"), ("가구", "종이·목재·가구"),
    ("나무", "종이·목재·가구"), ("목재", "종이·목재·가구"),
    # 부동산
    ("부동산", "부동산"),
    # 운송·물류
    ("운송", "운송·물류"), ("운수", "운송·물류"), ("여객", "운송·물류"),
    ("화물", "운송·물류"),
    # 미디어·엔터
    ("방송업", "미디어·엔터"), ("영화", "미디어·엔터"), ("비디오", "미디어·엔터"),
    ("광고", "미디어·엔터"), ("출판", "미디어·엔터"), ("오락", "미디어·엔터"),
    ("스포츠", "미디어·엔터"), ("녹음", "미디어·엔터"), ("오디오물", "미디어·엔터"),
    # SW·인터넷
    ("소프트웨어", "SW·인터넷"), ("프로그래밍", "SW·인터넷"), ("자료처리", "SW·인터넷"),
    ("호스팅", "SW·인터넷"), ("포털", "SW·인터넷"), ("정보 서비스", "SW·인터넷"),
    # 통신
    ("전기 통신", "통신"),
    # 유틸리티 (가스·전기·증기)
    ("가스", "유틸리티"), ("전기업", "유틸리티"), ("증기", "유틸리티"), ("냉·온수", "유틸리티"),
    # 금융
    ("금융", "금융"), ("보험", "금융"), ("은행", "금융"), ("저축", "금융"),
    ("신탁", "금융"), ("집합투자", "금융"), ("연금", "금융"),
    # IT·전자부품
    ("전자부품", "IT·전자부품"), ("음향", "IT·전자부품"), ("컴퓨터", "IT·전자부품"),
    ("가정용 기기", "IT·전자부품"), ("가전제품", "IT·전자부품"),
    ("방송 장비", "IT·전자부품"), ("정밀기기", "IT·전자부품"), ("측정", "IT·전자부품"),
    # 지주·서비스
    ("경영 컨설팅", "지주·서비스"), ("본부", "지주·서비스"), ("사업지원", "지주·서비스"),
    ("여행", "지주·서비스"), ("경비", "지주·서비스"), ("교육", "지주·서비스"),
    ("숙박", "지주·서비스"), ("개인 서비스", "지주·서비스"), ("임대", "지주·서비스"),
]

BROAD_ETC = "기타/미분류"


def to_broad_sector(industry: Optional[str]) -> str:
    """KSIC 세부 업종명 → 대분류. 매치 없으면 '기타/미분류'."""
    if not industry or industry == BROAD_ETC:
        return BROAD_ETC
    for kw, label in BROAD_RULES:
        if kw in industry:
            return label
    return BROAD_ETC


def fetch_sector_map() -> pd.DataFrame:
    """FDR KRX-DESC 에서 code→name/industry DataFrame 을 새로 받아 반환."""
    import FinanceDataReader as fdr

    desc = fdr.StockListing("KRX-DESC")
    out = desc.rename(
        columns={"Code": "code", "Name": "name", "Industry": "industry"}
    )[_COLS].copy()
    out["code"] = out["code"].astype(str).str.zfill(6)
    out["industry"] = out["industry"].where(out["industry"].notna(), "기타/미분류")
    return out.reset_index(drop=True)


def refresh() -> pd.DataFrame:
    """업종 맵을 새로 받아 parquet 캐시에 저장하고 반환."""
    df = fetch_sector_map()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE_PATH, index=False)
    return df


def load_sector_map(refresh_if_missing: bool = True) -> Optional[pd.DataFrame]:
    """캐시된 업종 맵을 반환. 없으면(옵션) 1회 fetch.

    Returns None if 캐시도 없고 ``refresh_if_missing=False`` 일 때.
    """
    if CACHE_PATH.exists():
        try:
            return pd.read_parquet(CACHE_PATH)
        except Exception:  # noqa: BLE001 — 손상 시 재fetch
            pass
    if refresh_if_missing:
        return refresh()
    return None


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    show = "--show" in sys.argv
    df = refresh()
    print(f"✅ {len(df)}개 종목 업종 매핑 → {CACHE_PATH}")
    print(f"   업종 수: {df['industry'].nunique()}")
    if show:
        print("\n--- 상위 20 업종 (종목 수) ---")
        print(df["industry"].value_counts().head(20).to_string())


if __name__ == "__main__":
    main()
