# 1H_touch_1W_ma20_slope_up

- 생성: 2026-05-18 21:47 KST
- Group: trend_pullback
- Module: `scripts.trend_pullback.ma20_touch_1h_entry`
- Git: d1ff82d (main, **dirty**)

## 목적

직전 run (`20260518-2140_1W_ma20_touch_slope_up`) 은 트리거를 **주봉 단위**로 봤기 때문에 "이번 주 중에 MA20 닿았다가 회복했지만 주봉 close 는 위로 마감"한 케이스를 모두 놓쳤다. 실제 매매는 그 주 안에서 MA20 닿는 순간 매수할 것이므로, 이번 run 에서는 **1시간봉 단위로 인트라위크 터치**를 찾아 진입한 결과를 본다.

## 가설

- 1H 인트라위크 터치는 baseline 보다 표본이 훨씬 많아질 것 (주봉 close 가 MA20 위로 회복한 케이스가 추가됨)
- 그런 케이스는 "즉시 회복" 시그널이라 4w 이후 win 이 직전 weekly close 트리거보다 높을 가능성

## 방법

- 모든 553개 USDT-M 1H 캐시 종목 순회
- 1W close 로 MA20 계산
- **각 주의 lock-in MA20**: 직전 주 close 로 계산한 MA20 값 (`shift(1)` 적용) — lookahead 방지
- **slope_up**: 직전 주 MA20 > 그 전 주 MA20 (둘 다 shift(1) 기준)
- 1H 봉 순회:
  - 그 시각이 속한 주의 `slope_up = True` AND
  - `low_1h ≤ MA20_locked ≤ high_1h` AND
  - **같은 주 안에서 첫 터치만** (중복 방지)
- 진입: 그 1H 봉의 다음 1H 봉 open
- forward return: 1h / 6h / 24h / 72h / 168h(=1w) / 336h(=2w) / 672h(=4w)
- BTC 1W MA20 slope 로 regime 슬라이스 (이전 run 과 호환)

## 핵심 결과

표본 n=3,372 events, 345 종목, 263 unique weeks (553 종목 중 208개는 history 부족으로 스킵).

| horizon | n | mean | median | win | p25 | p75 |
|---|---|---|---|---|---|---|
| 1h | 3372 | -0.03% | +0.01% | **50.3%** | -0.77% | +0.81% |
| 6h | 3372 | +0.28% | +0.05% | **51.0%** | -1.59% | +1.82% |
| 24h | 3367 | +0.16% | -0.10% | 48.0% | -3.35% | +3.03% |
| 72h | 3346 | +0.61% | -0.11% | 48.1% | -5.58% | +5.37% |
| 168h(1w) | 3322 | -0.18% | -1.35% | 43.6% | -8.67% | +6.11% |
| 336h(2w) | 3312 | -0.89% | -3.04% | 40.9% | -12.97% | +6.29% |
| 672h(4w) | 3293 | **-3.43%** | **-8.62%** | **32.5%** | -22.57% | +4.65% |

**핵심 발견 — 가설 부분 기각:**

1. 표본은 예상대로 2.3배 증가 (1,466 → 3,372). "주봉 close 가 MA20 위로 회복한 케이스" 가 추가됨.
2. 그러나 1~6시간 단기에 win 50~51% 로 거의 **동전(noise)**. mean 도 거의 0. "닿자마자 즉시 반등" 시그널은 통계적으로 거의 없음.
3. 24~72h(1~3일) 에서 win 48% 로 동전보다 살짝 약함.
4. 1w 부터는 명확히 음수 영역, 4w 에서 mean -3.43% / win 32.5%.

**Weekly trigger ([20260518-2140 run](../20260518-2115_baseline_1W_slope_imp7_vol5x/)) 대비 4w/24w 비교:**

| | weekly trigger | 1H intraweek |
|---|---|---|
| 4w n | 1,466 | 3,293 (2.2×) |
| 4w mean | -1.52% | **-3.43%** |
| 4w median | -7.85% | -8.62% |
| 4w win | 33.5% | 32.5% |

→ 추가된 1,827건(weekly close 가 MA20 위로 회복한 케이스) 은 4주 win 을 올리지 않음. 오히려 평균을 약간 끌어내림. 즉 "주봉 close 회복" 사실 자체가 단기 노이즈일 뿐 매수 우위 시그널이 아님.

**BTC regime 슬라이스 (672h=4w 기준):**

| btc_regime | n | mean | median | win |
|---|---|---|---|---|
| btc_up | 2911 | -4.04% | -9.17% | 32.1% |
| btc_down | 382 | **+1.23%** | -4.28% | 35.3% |

- weekly trigger 와 같은 방향 (btc_down 이 우위)
- 단 격차는 weekly trigger 보다 줄어듦 (weekly: btc_down 24w mean +22.5%, intraweek 4w +1.2%)

## 시사점

1. **단순 MA20 retest 는 자동매매 불가** — 모든 horizon 에서 우위 없음.
2. 1H 단기 (1~6h) 는 50% 동전, 단타 가설은 통계적 의미 없음.
3. 1H 정밀도로 잡았다고 weekly 보다 좋아지지 않음 — **트리거 자체 결함**이 본질.
4. baseline (1H 임펄스 7% + vol 5×) 의 168h win 37~44% 와 다시 비교: **모멘텀 트리거가 핵심이지 retest 자체는 약함**.

다음 시도 후보:
- retest + 직후 1H 양봉/vol spike 결합 grid
- touch_depth (MA20 대비 low 갭) 별 슬라이스 — 더 깊게 빠진 경우만 우위 있는지
- 1D MA20 retest 와 비교 (간격 좁은 retest 가 noisy 한지)
- "touch + slope 가속(MA20 1차 미분 증가) " 으로 게이트 강화

## 산출물

| 파일 | 크기 | 설명 |
|---|---|---|
| `output/events.parquet` | ~ | 3,372 인트라위크 1H 터치 이벤트 (symbol, ts, ts_entry, week_start, ma20_locked, low/high/close_1h, entry_price, fwd_ret_{1,6,24,72,168,336,672}h, btc_slope_up) |
| `output/summary.csv` | ~ | horizon × {n, mean, median, std, win, p25, p75} |
| `output/btc_slice.csv` | ~ | btc_regime(up/down) × horizon 슬라이스 |

## 재현

`REPRODUCE.md` 참조.
