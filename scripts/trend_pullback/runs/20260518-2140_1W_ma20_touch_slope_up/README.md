# 1W_ma20_touch_slope_up

- 생성: 2026-05-18 21:40 KST
- Group: trend_pullback
- Module: `scripts.trend_pullback.ma20_touch_entry`
- Git: d1ff82d (main, **dirty**)

## 목적

추세 게이트(1W MA20 slope > 0) 상태에서 **주봉 종가가 MA20 에 닿는 순간 롱 진입**하면 어떤 결과가 나오는지 확인. 기존 `baseline_1W_slope_imp7_vol5x` 는 1H 임펄스+볼륨 5× 라는 강한 트리거를 요구했지만, 이번엔 트리거를 **단순 MA20 retest** 한 가지로만 정의해서 baseline 대비 절대 표본 수·승률·forward return 분포를 비교한다.

## 가설

- 추세 (slope>0) 동안 MA20 까지의 풀백은 평균적으로 매수 우위 구간이다
- 단, baseline 의 강한 모멘텀 트리거를 빼면 표본은 늘되 평균 수익률은 낮아질 가능성이 높음 (희석)

## 방법

- 모든 553개 USDT-M 1H 캐시 → 1W resample (`data.resample.load(symbol, "1w")`)
- 1W close 의 MA20 계산
- slope: `MA20[t] - MA20[t-1] > 0` 인 주봉만 후보
- **터치 정의**: `low[t] <= MA20[t] <= high[t]` (주봉 막대가 MA20 을 가로지름)
- 직전 주봉도 같은 조건이면 같은 터치 시리즈 — **연속 터치 중첩 방지**를 위해 첫 봉만 이벤트로 인정 (직전 봉이 untouched 였던 경우만 진입)
- 진입: 터치 봉의 **다음 주봉 open** (no lookahead)
- forward return: 진입가 대비 +1w/2w/4w/8w/24w close 의 수익률
- 횟수 충분하면 BTC 자체 regime 별로도 한 번 더 슬라이스 (BTC trend filter 적용·비적용 비교)

## 핵심 결과

**가설 기각.** 1W MA20 slope>0 게이트 하에서 "주봉 종가가 MA20 닿는 순간 진입" 단순 룰은 매수 우위 X.

| horizon | n | mean | median | win |
|---|---|---|---|---|
| 1w | 1466 | +0.76% | -0.48% | 47.6% |
| 2w | 1455 | +1.42% | -1.17% | 46.8% |
| 4w | 1446 | **-1.52%** | **-7.85%** | **33.5%** |
| 8w | 1415 | **-3.73%** | **-18.75%** | 28.5% |
| 24w | 1351 | **-9.05%** | **-36.80%** | 23.9% |

- 1~2주 단기는 거의 동전(win ≈ 47%, mean 약양수). 4주 이후 명확한 마이너스.
- 모든 horizon 에서 median 이 mean 보다 훨씬 낮음 → 대다수 손실 + 소수 대박의 long-tail 분포.
- baseline (1H 임펄스 7% + vol 5×) 의 168h win 37~44% 와 비교하면 **단순 retest 는 모멘텀 트리거를 빼는 만큼 신호가 죽는다**.

**BTC regime 슬라이스 (반직관):**

| btc_regime | horizon | n | mean | median | win |
|---|---|---|---|---|---|
| btc_up | 4w | 1249 | -3.03% | -8.23% | 31.9% |
| btc_up | 24w | 1249 | -11.6% | -38.7% | 22.9% |
| btc_down | 4w | 197 | **+8.09%** | -2.85% | **43.1%** |
| btc_down | 24w | 102 | **+22.5%** | -8.59% | 36.3% |

- BTC 상승장 1249건 중 retest 는 모멘텀 상실 신호. BTC 약세장 217건은 깊은 풀백 후 반등이 일부 섞여 우위 (단 표본 ↓).
- 즉 "BTC trend up + alt MA20 retest" 조합은 오히려 회피해야 할 setup.

## 시사점

1. 단순 retest 룰은 그대로 자동매매 X — 모멘텀/볼륨 컨디션을 더해야 baseline 수준 복귀.
2. BTC regime 을 게이트로 쓸 거면 "btc_down + alt slope_up" 가 의외의 후보. 단 표본·생존 편향 검증 필요.
3. 다음 단계 후보:
   - retest 후 추가 트리거(다음봉 상승전환, vol spike, RSI 반등) 결합 grid
   - touch_pad 도입해 "근접" 정의 완화 (low ≤ MA20×(1+pad))
   - 4w 분포의 right-tail 만 잡는 룰 (TP/SL 동반 백테스트)

## 산출물

| 파일 | 크기 | 설명 |
|---|---|---|
| `output/events.parquet` | 159 KB | 1,466 터치 이벤트 (symbol, ts, ts_entry, ma20, high/low/close, entry_price, ma_slope_pct, fwd_ret_{1,2,4,8,24}w, btc_slope_up) |
| `output/summary.csv` | 1 KB | horizon × {n, mean, median, std, win, p25, p75} 표 |
| `output/btc_slice.csv` | 1 KB | btc_regime(up/down) × horizon 슬라이스 |

## 재현

`REPRODUCE.md` 참조.
