---
name: crypto-fetch
description: Bitget USDT-M 선물 전 종목의 OHLCV (1h/1d, 4h/1w 옵션)를 직접 REST + aiohttp로 다운로드해 granularity별 parquet으로 캐시. 1h/1d는 raw 저장, 4h/1w는 1h/1d에서 즉석 리샘플. 단일/전체·증분/처음부터 모드 지원.
---

# /crypto-fetch

Bitget 선물 과거 데이터 다운로드 워크플로우.

## 전제

- 1h, 1d를 raw로 캐시 (`data/cache/crypto/{1h,1d}/{SYMBOL}.parquet`)
- 4h는 1h에서, 1w는 1d 우선·없으면 1h에서 메모리 리샘플
- 거래소 직접 호출(ccxt 미사용). v2 REST + aiohttp async
- 심볼 포맷은 Bitget 원본: `BTCUSDT`, `ETHUSDT` (슬래시·콜론 없음)
- 캔들 컬럼: `timestamp`(UTC ms), `open`, `high`, `low`, `close`, `volume`(코인 수량), `amount`(거래대금 USDT)

## 사용 예

```bash
# 전 종목 1H, 증분 (각 심볼 캐시의 마지막 시점부터 이어 받음)
python -m data.sources.bitget

# 전 종목 1D
python -m data.sources.bitget --granularity 1d

# 단일 심볼
python -m data.sources.bitget --symbol BTCUSDT --granularity 1d

# 처음부터 다시 (캐시 무시, 지정 일자부터)
python -m data.sources.bitget --granularity 1d --since 2017-01-01
```

## 다운로드 동작

| 항목 | 값 |
|---|---|
| 엔드포인트 | `GET /api/v2/mix/market/history-candles` |
| productType | `usdt-futures` |
| granularity | `1h` / `4h` / `1d` / `1w` (Bitget: `1H`/`4H`/`1Dutc`/`1Wutc`) |
| 페이지당 limit | 200 (Bitget v2 한도) |
| 요청 윈도우 | 1H=200h, 4H=200×4h, 1D=90d, 1W=52w (1D는 200d면 40017 에러) |
| 동시 요청 수 | 5 (CONCURRENCY) |
| 배치 사이 sleep | 0.5초 |
| 기본 시작일 | 1h/4h: 2020-01-01, 1d/1w: 2017-01-01 |
| 캐시 경로 | `data/cache/crypto/{gran}/{SYMBOL}.parquet` |

429 / IP 차단 발생 시 `CONCURRENCY` 또는 `BATCH_SLEEP_SEC`을 조정.

## 리샘플 (data/resample.py)

```python
from data.resample import load
df_1h = load("BTCUSDT", "1h")  # raw 1h 캐시
df_4h = load("BTCUSDT", "4h")  # 1h → 4h 리샘플
df_1d = load("BTCUSDT", "1d")  # raw 1d 캐시 우선, 없으면 1h 리샘플
df_1w = load("BTCUSDT", "1w")  # 1d 우선, 없으면 1h
```

| interval | source | 시작 |
|---|---|---|
| 1h | raw 캐시 | UTC 정시 |
| 4h | 1h 리샘플 (`4h`) | UTC 0/4/8/12/16/20시 |
| 1d | raw 1d (또는 1h 리샘플) | UTC 자정 |
| 1w | 1d 리샘플 (또는 1h, `W-MON`) | 월요일 |

전부 `label='left', closed='left'` — 봉의 시작 시각이 timestamp.

## 호출 절차

1. 첫 실행이면 `--since 2020-01-01` (1h) / `--since 2017-01-01` (1d) 권장
2. 이후엔 인자 없이 (증분), `--granularity` 만 바꿔서 호출
3. 완료 후 `ls data/cache/crypto/1h | wc -l`, `ls data/cache/crypto/1d | wc -l` 로 카운트 확인

## 주의

- 사용자가 **다른 세션에서** 다운로드를 직접 돌릴 가능성이 큼. 이 스킬은 명령줄·캐시 위치·리샘플 규약의 계약서.
- 쓰는 쪽(백테스트, 대시보드)은 **항상 `data.resample.load(...)`** 만 통해 데이터 접근. 캐시 파일을 직접 읽지 말 것.
- `amount`(거래대금)는 ccxt에선 안 주지만 직접 REST에서는 받으므로, 유동성 필터·VWAP 계산에 활용 가능.
