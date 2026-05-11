---
name: crypto-fetch
description: Bitget USDT-M 선물 전 종목의 1시간 봉 OHLCV를 직접 REST + aiohttp로 빠르게 다운로드해 parquet으로 캐시. 4H/1D/1W는 1H에서 즉석 리샘플로 생성. 단일/전체·증분/처음부터 모드 지원.
---

# /crypto-fetch

Bitget 선물 과거 데이터 다운로드 워크플로우.

## 전제

- 1시간 봉만 캐시한다. 4H/1D/1W는 메모리 상에서 리샘플 (저장 안 함)
- 거래소 직접 호출(ccxt 미사용). v2 REST + aiohttp async
- 심볼 포맷은 Bitget 원본: `BTCUSDT`, `ETHUSDT` (슬래시·콜론 없음)
- 캔들 컬럼: `timestamp`(UTC ms), `open`, `high`, `low`, `close`, `volume`(코인 수량), `amount`(거래대금 USDT)

## 사용 예

```bash
# 전 종목, 증분 (각 심볼 캐시의 마지막 시점부터 이어 받음)
python -m data.sources.bitget

# 단일 심볼
python -m data.sources.bitget --symbol BTCUSDT

# 처음부터 다시 (캐시 무시, 지정 일자부터)
python -m data.sources.bitget --since 2020-01-01
```

## 다운로드 동작

| 항목 | 값 |
|---|---|
| 엔드포인트 | `GET /api/v2/mix/market/history-candles` |
| productType | `usdt-futures` |
| granularity | `1H` |
| 페이지당 limit | 200 (Bitget v2 한도) |
| 동시 요청 수 | 18 (IP당 20 req/s 한도 직전) |
| 배치 사이 sleep | 1.0초 |
| 기본 시작일 | 2020-01-01 UTC |
| 캐시 경로 | `data/cache/crypto/bitget_{SYMBOL}_1h.parquet` |

429 / IP 차단 발생 시 `CONCURRENCY` 또는 `BATCH_SLEEP_SEC`을 조정.

## 리샘플 (data/resample.py)

```python
from data.resample import load
df_1h = load("BTCUSDT", "1h")
df_4h = load("BTCUSDT", "4h")
df_1d = load("BTCUSDT", "1d")
df_1w = load("BTCUSDT", "1w")
```

| interval | pandas rule | 시작 |
|---|---|---|
| 1h | (원본) | UTC 정시 |
| 4h | `4h` | UTC 0/4/8/12/16/20시 |
| 1d | `1D` | UTC 자정 |
| 1w | `W-MON` | 월요일 |

전부 `label='left', closed='left'` — 봉의 시작 시각이 timestamp.

## 호출 절차

1. 첫 실행이면 `--since 2020-01-01` 권장, 이후엔 인자 없이 (증분)
2. `python -m data.sources.bitget [...]` 실행
3. 완료 후 `ls data/cache/crypto | wc -l`로 캐시 파일 수 확인

## 주의

- 사용자가 **다른 세션에서** 다운로드를 직접 돌릴 가능성이 큼. 이 스킬은 명령줄·캐시 위치·리샘플 규약의 계약서.
- 쓰는 쪽(백테스트, 대시보드)은 **항상 `data.resample.load(...)`** 만 통해 데이터 접근. 캐시 파일을 직접 읽지 말 것.
- `amount`(거래대금)는 ccxt에선 안 주지만 직접 REST에서는 받으므로, 유동성 필터·VWAP 계산에 활용 가능.
