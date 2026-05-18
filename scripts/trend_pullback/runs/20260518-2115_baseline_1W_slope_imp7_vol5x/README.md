# baseline_1W_slope_imp7_vol5x

- 생성: 2026-05-18 21:15 KST
- Group: trend_pullback
- Module: `scripts.trend_pullback.angle_study`
- Git: d1ff82d (main, **dirty**)

## 목적

`trend_pullback` 분석의 baseline. 1W MA20 slope > 0 게이트 + 7% 1H 임펄스 + 거래량 5× 필터 조합으로 이벤트를 수집해 wick × bars × angle 3축 cross-tab 의 모집단 확보.

이후 `full_grid` 분석이 이 events.parquet 을 입력으로 받아 cell 별 forward returns 계산.

## 방법

- 모든 553개 USDT-M 1H 캐시 종목 순회
- 1W close 로 MA20 계산 (1 week shift 로 lookahead 방지) → slope > 0 인 시점만 임펄스 인정
- 임펄스 조건: `(close − open)/open ≥ 0.07` AND `volume ≥ 5 × rolling(10).mean().shift(1)`
- 각 임펄스에서 MA10 (lookahead 10봉), MA20 (lookahead 20봉) 첫 터치 추적
- 진입 시점 두 종류 기록:
  - `fwd_*_imp`: 임펄스 봉 close 기준 (lookahead bias 가능)
  - `fwd_*_ma{10,20}`: 터치 봉 close 기준 (no lookahead)
  - `fwd_*_cf{10,20}`: 미터치 확정 시점 close 기준 (no lookahead for untouched)

## 핵심 결과

`results_summary` in config.json:
- 임펄스: **1,228**
- MA10 터치 (within 10): **1,099 (89.5%)**
- MA20 터치 (within 20): **1,096 (89.3%)**
- 둘 다 터치 (BOTH): 1,015 (82.7%)
- 둘 다 미터치 (NEITHER): 48 (3.9%)

`output/angle_study_summary.csv` 의 baseline 168h:
- ALL impulses (imp-close): n=1228, win=37%
- MA10 touched (fr touch close): n=1099, win=39%
- bars 4-6 (균형 cell): n=382, win=44% (가장 좋음)

## 산출물

| 파일 | 크기 | 설명 |
|---|---|---|
| `output/events.parquet` | 428 KB | 1,228 임펄스 이벤트 (symbol, ts, impulse_close, touched_ma{10,20}, bars_to_touch, drop_pct, angle, fwd_*) |
| `output/angle_study_summary.csv` | 5 KB | bars × quantile angle cross-tab 요약 표 |

## 재현

`REPRODUCE.md` 참조.
