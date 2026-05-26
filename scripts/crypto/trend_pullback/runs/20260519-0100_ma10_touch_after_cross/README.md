# ma10_touch_after_cross

- 생성: 2026-05-19 01:00 KST
- Group: trend_pullback
- Module: `scripts.trend_pullback.ma10_touch_after_cross`
- Git: 0066b6f (main, **dirty**)

## 목적

[PLAN.md](../../PLAN.md) L0e. 주봉 MA20 기울기가 ≤0 → >0 로 바뀐 직후, 첫 주봉 MA10 터치 시점에 롱 진입했을 때 forward 수익률 분포 측정.

## 파라미터 스윕

| param | sweep values | default |
|---|---|---|
| `ma_short_period` | [5, 10, 15] | 10 |
| `gate_strict` | [True, False] | True |

## 방법

- 553 USDT-M 1D 캐시 (방금 업데이트, 2026-05-17 까지)
- 주봉 MA20 (locked from prev week) + MA10 (locked from prev week)
- 게이트: `gate_strict=True` → MA20 slope cross-up (strict). `False` → slope_up 유지 중 (이전 주에는 ≤0 조건 없이) 어디든
- 트리거: 게이트 충족 시점 (= 주 W 종가) 직후, 첫 1D 봉 중 `low ≤ MA10_locked ≤ high` 인 첫 봉
- 진입: 그 1D 봉의 다음 1D open
- forward: 1,2,3,4,5,6,7d, 14,21,28,35,42,49,56d

## 핵심 결과

(분석 완료 후 채움)

## 산출물

(`/study finalize` 가 자동 채움)

## 재현

`REPRODUCE.md` 참조.
