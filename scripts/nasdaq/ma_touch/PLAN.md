# NASDAQ `ma_touch` — NASDAQ 종목 다중 TF MA 터치 시그널

> 공통 설계는 [docs/strategies_v2_design.md](../../../docs/strategies_v2_design.md) 참조. 본 문서는 NASDAQ 자산별 차이만 기술.

## Universe

- `data/cache/us/{TICKER}.parquet` 의 모든 파일 (NASDAQ 전체, 수천 종목)
- 단, 시그널 평가 제외:
  - 일봉 데이터 < 60일

## 데이터 스키마

- 캐시: `data/cache/us/{TICKER}.parquet`
- 컬럼: `Open, High, Low, Close, Volume, Change` (대문자, FDR 표준)
- 인덱스: `DatetimeIndex` (naive)
- 통화: USD
- 거래일 기준 (NYSE 캘린더)

## Normalization (공통 인터페이스 진입 시)

`_common.mtf_loader` 가 처리:
- 컬럼 lowercase
- 인덱스 그대로 (naive datetime, NY 캘린더)
- `Change` 컬럼은 사용 안 함

KR/US 둘 다 FDR 동일 스키마라 normalization 코드 공유.

## 임계값 — 모두 동일 (공통 설계 8절)

KR/Crypto 와 동일.

## 출력

- 파일: `data/cache/us/_ma_touch.parquet`
- 스키마: 공통 설계 5절 row 스키마

## 실행

```powershell
.venv/Scripts/python.exe -m scripts.nasdaq.ma_touch.recommend
```

## NASDAQ 자산 비고

- 종목 수가 KR (~948) / Crypto (~400) 대비 압도적 — 측정 시간 가장 길 가능성. precompute 압력 가장 큼.
- AAPL/MSFT/GOOG 같은 20년+ 종목 = 1Y partial/full 평가 가능.
- 최근 IPO (1년 미만) 종목 다수 → 1W partial 시그널 본질.
- 옵션/실적 발표 갭 큼 → 1D dist 임계값 3% 가 살짝 좁을 수 있음. 운영 보면서 튜닝.
