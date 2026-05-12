---
name: kr-fetch
description: KOSPI 종목의 일봉 OHLCV를 FinanceDataReader로 다운로드해 parquet 캐시(`data/cache/kr/{종목코드}.parquet`)에 저장. 단일 종목 또는 전체 KOSPI 일괄, 증분/refresh 모드 지원. 종목코드는 6자리 문자열(예: '005930'). 주봉/월봉은 일봉에서 즉석 resample.
---

# /kr-fetch

KOSPI 일봉 데이터 다운로드 워크플로우.

## 전제

- **일봉이 single source of truth.** 주봉/월봉은 항상 일봉에서 pandas resample.
- 종목코드는 6자리 문자열 (예: `005930`, `000660`). 앞자리 0 유지 필수.
- 캐시 경로: `data/cache/kr/{종목코드}.parquet`
- 데이터 컬럼: `Open, High, Low, Close, Volume, Change` (FDR 원본 케이스 그대로)
- 인덱스: pandas `DatetimeIndex` (KST 자정, naive)

## 사용 패턴

### 1. 전체 KOSPI 일괄 다운로드 (대량 캐시 빌드)

```bash
.venv/Scripts/python.exe -m data.sources.stocks --market KOSPI                # 증분
.venv/Scripts/python.exe -m data.sources.stocks --market KOSPI --refresh      # 캐시 무시 재다운
.venv/Scripts/python.exe -m data.sources.stocks --market KOSPI --workers 30   # 동시 요청 조정
```

ThreadPoolExecutor 병렬, tqdm 진행률 표시. 출력: `data/cache/kr/_listing.csv`(종목 리스트), `_errors.csv`(실패 종목).

### 2. 단일 종목 (Python에서 직접)

```python
from research.collect import fetch_daily, save_daily, load_daily

# 다운로드 → 저장
df = fetch_daily("005930", start="2020-01-01")
save_daily("005930", df)

# 이후 사용
df = load_daily("005930")
```

### 3. 주봉/월봉 resample

```python
from research.collect import load_daily, to_weekly, to_monthly

df_d = load_daily("005930")
df_w = to_weekly(df_d)   # 금요일 마감 기준 (W-FRI), 한국시장 관행
df_m = to_monthly(df_d)  # 월말 기준 (ME)
```

## 종목 리스트 조회

```python
import FinanceDataReader as fdr
kospi  = fdr.StockListing("KOSPI")   # 코드/종목명/시가총액 등
kosdaq = fdr.StockListing("KOSDAQ")
krx    = fdr.StockListing("KRX")     # 통합
```

## 호출 절차

1. 처음이면 `python -m data.sources.stocks --market KOSPI` 실행 (수 분 소요)
2. 이후 신규 종목/증분 갱신: 같은 명령 (캐시 있으면 skip)
3. 단일 종목 빠른 확인은 `research.collect.fetch_daily(...)`

## 주의

- 미국(NASDAQ) 종목은 `/us-fetch` 사용 (캐시 경로가 `data/cache/us/`)
- 6자리 코드 0 누락 금지: `'005930'` ≠ `5930`
- 일봉만 캐시. 주/월봉은 메모리에서 resample (저장 X)
- FDR 외에 `pykrx` 를 보조로 사용 (시가총액 시계열, 외국인·기관 수급, PER/PBR 시계열)