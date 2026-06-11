# Crypto `ma_touch` — Bitget USDT-M 다중 TF MA 터치 시그널

> 공통 설계는 [docs/strategies_v2_design.md](../../../docs/strategies_v2_design.md) 참조. 본 문서는 Crypto 자산별 차이만 기술.

## Universe

- `data/cache/crypto/1d/{SYMBOL}.parquet` 의 모든 파일 (Bitget USDT-M 전체, 약 400 종목)
- 단, 시그널 평가 제외:
  - 일봉 데이터 < 60일

분류(`classification.parquet`) 필터는 적용 X — `ma_touch` 는 룰 자체로 정배열 + slope up 게이트가 있어 junk 가 자연스럽게 걸러짐. 필요 시 다운스트림에서 join 필터.

## 데이터 스키마

- 캐시: `data/cache/crypto/1d/{SYMBOL}.parquet`
- 컬럼: `timestamp, open, high, low, close, volume, amount` (이미 소문자)
- `timestamp`: UTC ms (int64)
- 통화: USDT
- 24/7 (휴일 없음) — 봉 빠짐 없음

## Normalization (공통 인터페이스 진입 시)

`_common.mtf_loader` 가 처리:
- `timestamp` → `pd.to_datetime(unit='ms', utc=True)` → 인덱스 설정
- 컬럼 그대로 (`open, high, low, close, volume`)
- `amount` 컬럼은 사용 안 함 (거래대금 필터 필요 시 별도)

## 임계값 — 모두 동일 (공통 설계 8절)

KR/US 와 동일. crypto 변동성 큼에도 사용자 결정 "자산별 룰 동일" — `DIST_TH_MA10/20 = 3%`.

## 출력

- 파일: `data/cache/crypto/_ma_touch.parquet`
- 스키마: 공통 설계 5절 row 스키마

## 실행

```powershell
.venv/Scripts/python.exe -m scripts.crypto.ma_touch.recommend
```

## Crypto 자산 비고

- Bitget 1H 캐시 (`data/cache/crypto/1h/`) 도 있으나 본 자리는 1D 기반. 1H 는 추후 `trend_strong` (추격) 자리에서 활용 검토.
- BTC/ETH 같은 5년+ 이력 종목은 1Q MA20 가능. 다만 7년 이상 종목은 BTC 정도만 있음 → 1Y 평가는 사실상 BTCUSDT 한정.
- 신생 코인 (상장 1~2개월) 다수 → 1W partial 시그널 비중 상당.
- 1D 시그널 잡힌 종목 중 1M/1Q angle 음수면 "데드캣 바운스" 가능성 — 차트 확인 필수.
