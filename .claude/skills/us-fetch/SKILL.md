---
name: us-fetch
description: NASDAQ 종목의 일봉 OHLCV를 FinanceDataReader로 다운로드해 parquet 캐시(`data/cache/us/{TICKER}.parquet`)에 저장. 단일 종목 또는 전체 NASDAQ 일괄, 증분/refresh 모드 지원. 데이터 소스는 추후 yfinance / Polygon 등으로 변경 가능 (인터페이스만 유지).
---

# /us-fetch

NASDAQ 일봉 데이터 다운로드 워크플로우. **현재는 FinanceDataReader 기반**, 추후 정확성·코퍼레이트 액션 처리 이슈로 yfinance나 유료 API로 교체 가능.

## 전제

- 일봉이 single source of truth. 주봉/월봉은 메모리 resample.
- 티커는 대문자 알파벳 (예: `AAPL`, `MSFT`, `NVDA`).
- 캐시 경로: `data/cache/us/{TICKER}.parquet`
- 컬럼: `Open, High, Low, Close, Volume, Change`
- 인덱스: pandas `DatetimeIndex` (US/Eastern → naive 변환되어 들어옴, 표시는 KST 변환)

## 사용 패턴

### 전체 NASDAQ 일괄

```bash
python -m data.sources.stocks --market NASDAQ                # 증분
python -m data.sources.stocks --market NASDAQ --refresh      # 캐시 무시 재다운
python -m data.sources.stocks --market ALL                   # KOSPI+NASDAQ
```

### 단일 종목

```python
import FinanceDataReader as fdr
df = fdr.DataReader("AAPL", "2020-01-01")
# 직접 저장하려면:
from pathlib import Path
df.to_parquet(Path("data/cache/us") / "AAPL.parquet")
```

## 데이터 소스 주의

- FDR의 미국 종목은 Yahoo Finance 백엔드 — **분할/배당 미반영** 가능. 정확한 백테스트가 필요하면 corporate actions 보정 필요.
- 정확성이 중요해지면 **소스 교체 검토**:
  - `yfinance` — 무료, 분할/배당 반영 옵션 있음
  - Polygon.io / Alpha Vantage — 유료, 정확도 높음

소스를 바꿔도 캐시 인터페이스는 유지: `data/cache/us/{TICKER}.parquet`, 같은 OHLCV 컬럼.

## 호출 절차

1. `python -m data.sources.stocks --market NASDAQ` (긴 시간 소요)
2. 캐시 카운트 확인: `ls data/cache/us | wc -l`
3. 단일 종목은 `fdr.DataReader(...)` 로 빠르게

## 주의

- KOSPI 종목과 캐시 경로 분리: `data/cache/kr/` vs `data/cache/us/`
- 티커 충돌 가능성 (예: 한국 6자리 vs 미국 영문): 경로로 구분되므로 문제 없음
- 시간대: 표시할 때만 KST 변환, 분석/저장은 그대로