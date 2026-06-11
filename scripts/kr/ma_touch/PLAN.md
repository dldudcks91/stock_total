# KR `ma_touch` — KOSPI 종목 다중 TF MA 터치 시그널

> 공통 설계는 [docs/strategies_v2_design.md](../../../docs/strategies_v2_design.md) 참조. 본 문서는 KR 자산별 차이만 기술.

## Universe

- `data/cache/kr/{6자리코드}.parquet` 의 모든 파일 (KOSPI 전체, 약 948 종목)
- 단, 시그널 평가 제외:
  - 일봉 데이터 < 60일 (신규 상장 60일 미만 — partial 도 평가 X, 데이터 너무 부족)

## 데이터 스키마

- 캐시: `data/cache/kr/{6자리}.parquet`
- 컬럼: `Open, High, Low, Close, Volume, Change` (대문자, FDR 표준)
- 인덱스: `DatetimeIndex` (naive)
- 통화: 원화 (KRW)
- 거래일 기준 (주말/공휴일 제외)

## Normalization (공통 인터페이스 진입 시)

`_common.mtf_loader` 가 처리:
- 컬럼 lowercase (`open`, `high`, `low`, `close`, `volume`)
- 인덱스 그대로 (naive datetime, KST 캘린더)
- `Change` 컬럼은 사용 안 함

## 임계값 — 모두 동일 (공통 설계 8절)

| 파라미터 | 값 |
|---|---|
| `DIST_TH_MA10` | 3% |
| `DIST_TH_MA20` | 3% |
| `ANGLE_MEDIUM_DEG` | 15 |
| `ANGLE_STRONG_DEG` | 30 |
| `PARTIAL_CONSEC_BARS` | 3 |

KR 자산 override 없음.

## 출력

- 파일: `data/cache/kr/_ma_touch.parquet`
- 스키마: 공통 설계 5절의 row 스키마 (40+ 컬럼)
- 1 row / 종목

## 실행

```powershell
.venv/Scripts/python.exe -m scripts.kr.ma_touch.recommend
```

## KR 자산 비고

- 거래 시간 9:00~15:30 KST. 평가 시각은 마지막 일봉 종가 기준 (즉 장 마감 후 한 번 평가가 자연스러움).
- 분기 실적 발표 (3/6/9/12월 말 후 1~2개월) 시 갭 큼 → 1Q MA 평가가 의미 있는 종목 多.
- 5년+ 상장 종목이 KOSPI 전체의 60%+ → 1Q full 평가 비중 상당.
- 10년+ 상장은 30%+ → 1Y partial 가능.
