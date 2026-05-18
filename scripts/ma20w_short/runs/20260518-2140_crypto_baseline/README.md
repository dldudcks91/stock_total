# crypto_baseline

- 생성: 2026-05-18 21:40 KST
- Group: ma20w_short
- Module: —
- Git: d1ff82d (main, **dirty**)

## 목적
주봉 MA20 아래에 있을 때 숏(short)을 진입하는 전략의 베이스라인 성과를 확인한다.
- 가설: 주봉 추세 약세(close < MA20w) 구간이 통계적으로 음의 수익률 (즉 숏 우위)을 보인다면, 단순 close-below-MA20 룰만으로도 양의 기대값.
- 자산은 **숏 가능한 crypto (Bitget USDT-M)** 한정. KR/US 주식은 숏이 제도적으로 제한이라 1차 범위에서 제외.

## 방법
1. 데이터: `data/cache/crypto/1d/*.parquet` → 1w 리샘플 (data.resample.load 사용)
2. 진입: 주 종가 기준 `close[t] < MA20[t]` 이면 다음 주 시가에 숏 진입 (룩어헤드 금지)
3. 청산 후보 (베이스라인 → 추가 그리드는 다음 run):
   - A) `close[t] >= MA20[t]` 발생 시 다음 주 시가 청산
   - B) 고정 보유 N주 (4/8/12 등)
   - C) 트레일링 스탑·TP/SL (별도 run)
4. 수수료/슬리피지: Bitget 선물 기준 — 진입 5bps + 청산 5bps + 슬리피지 5bps 가정 (params 확정 시 갱신)
5. 그룹 성과: 4그룹 분류 (`data/cache/crypto/classification.parquet`) 별 분해 — trend / follower / whale / junk 에서 숏 우위가 어디서 가장 강한지 확인

## 핵심 결과
(분석 완료 후 채움)

## 산출물
(`/study finalize` 가 자동 채움)

## 재현
`REPRODUCE.md` 참조.
