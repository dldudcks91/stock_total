# slope_cross_event

- 생성: 2026-05-19 00:07 KST
- Group: trend_pullback
- Module: `scripts.trend_pullback.slope_cross_event`
- Git: 0066b6f (main, **dirty**)

## 목적

[PLAN.md](../../PLAN.md) L0d. **가격 조건 없이** 1W MA20 기울기가 `≤0 → >0` 로 바뀌는 순간만 트리거로 잡고, 그 시점에 진입했을 때 1~7일 + 1~8주 일봉 종가 forward return 분포를 본다. price-action 빼고 순수 "추세 회귀" 게이트 자체에 edge 가 있는지 측정.

## 파라미터 스윕

| param | sweep values | default |
|---|---|---|
| `horizon_days` | [1,2,3,4,5,6,7, 14,21,28,35,42,49,56] | sweep 자체가 핵심 axis |

`ma_period_weekly` 는 20 고정 (사용자 합의).

## 방법

- 553 USDT-M 1H 캐시 → 1D / 1W 리샘플
- 1W close MA(20). `slope[W] = MA[W]-MA[W-1]`
- cross-up event: `slope[W]>0` AND `slope[W-1]≤0` (strict)
- 진입: 주 W 종가 직후 첫 1D 봉 open (lookahead 없음 — W 주가 끝나야 cross 확정)
- fwd_ret_Nd = `close[entry + N - 1] / open[entry] - 1`

## 핵심 결과

(분석 완료 후 채움)

## 산출물

(`/study finalize` 가 자동 채움)

## 재현

`REPRODUCE.md` 참조.
