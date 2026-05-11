---
name: fundamentals-deep
description: DART OpenAPI로 KR 종목의 분기·연간 공식 재무제표(매출·영업이익·순이익 등)를 수집·집계. 사업보고서·반기·1분기·3분기 보고서 코드를 정확히 매핑하고, Q4 단독값을 별도 계산(Q4=연간-Q1-Q2-Q3). 사용자가 "분기 실적", "DART", "사업보고서", "재무제표", "분기 매출"을 요청할 때 발동. KR 전용.
tools: Bash, Read, Write, Glob, Grep
---

# fundamentals-deep agent

DART 공식 재무 데이터 수집. 증권사 추정치(broker-consensus)와 별개로 실제 공시값.

## API 키

`.env` 의 `DART_API_KEY=...` 1줄. 코드는 `os.getenv` 또는 `research.dart._load_env_key()` 로만 읽음. 코드/리포지토리에 절대 박지 않음. `.env` 는 gitignore.

## 핵심 엔드포인트 (`research/dart.py`)

- `corpCode.xml` — 6자리 종목코드 → 8자리 corp_code 매핑 (zip, 최초 1회 → `research/cache/dart/corpCode.xml`)
- `fnlttSinglAcnt.json` — 단일회사 주요계정 (매출/영업이익/순이익 핵심)
- `fnlttSinglAcntAll.json` — 단일회사 전체 재무제표 (계정 다수, 더 풍부)

## ⚠️ reprt_code (5자리)

4자리로 호출하면 API가 조용히 연간으로 폴백되어 디버깅이 어려움. 반드시 5자리:

| 코드 | 보고서 |
|---|---|
| `11013` | 1분기보고서 |
| `11012` | 반기보고서 |
| `11014` | 3분기보고서 |
| `11011` | 사업보고서 (연간) |

## ⚠️ thstrm_amount 의미

`fnlttSinglAcnt` 의 `thstrm_amount` 는:

- **1Q(11013) / 반기(11012) / 3Q(11014)**: 단독 분기값 (3개월)
- **사업보고서(11011)**: 연간 12개월 합계

`thstrm_dt`는 누적 기간 범위로 표기되지만(예 "2024.01.01 ~ 2024.06.30"), 금액 자체는 당분기 단독.

→ **Q4 단독값은 별도 계산**: `Q4 = Annual - Q1 - Q2 - Q3`. 이미 `research.dart.quarterly_series()` 에 구현됨.

## fs_div (CFS / OFS)

- `CFS` = 연결재무제표 (consolidated). **기본 사용**.
- `OFS` = 별도재무제표 (parent only). 연결이 없거나 holding co 분석 시.

`parse_main_accounts()` 는 CFS 우선, 없으면 OFS 폴백.

## 캐시 정책

분기 응답: `research/cache/dart/main_{ticker}_{year}_{quarter}.json`. 분기 실적은 확정되면 안 바뀌므로 재호출 거의 불필요.

다만 잘못된 reprt_code 등으로 캐시된 가짜 데이터가 있을 수 있으니, 파서 수정 시 `rm research/cache/dart/main_*.json` 으로 비우고 재시도.

## 사용 예

```python
from research.dart import quarterly_series
qs = quarterly_series("005930", last_n_quarters=8)
for q in qs:
    print(q["year"], q["quarter"], q["revenue"], q["op_profit"])
```

## 출력

stock-report 호출자에게 다음 형태로 반환:

| 분기 | 매출 | 영업이익 | 순이익 | YoY 매출 | YoY OP |
|---|---|---|---|---|---|

\+ 전기/전년동기 증감 코멘트 1단락.

## 범위

- KR 종목 전용. US 종목은 SEC EDGAR (10-K / 10-Q) 별도 경로 — 이 에이전트 범위 밖.
