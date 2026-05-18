# retest_confirm_grid

- 생성: 2026-05-18 14:27 KST · 재실행: 2026-05-18 14:55 KST (sweep 10 combos)
- Group: trend_pullback
- Module: `scripts.trend_pullback.retest_confirm_grid`
- Git: 0066b6f (main, **dirty**)

## 목적

[PLAN.md](../../PLAN.md) L1. 1W MA slope>0 게이트 + 1H retest + 확인봉 feature 의 sub-cell 우위 존재 여부를 확인. 이 run 은 **marginal sweep** — `ma_period_weekly / confirm_offset / vol_sma_period / rsi_period` 각각을 default 외 값으로 바꿔 비교.

## 파라미터 스윕

| param | sweep values | default | 의미 |
|---|---|---|---|
| `ma_period_weekly` | [10, 20, 30, 50] | 20 | 게이트 1W MA 길이 |
| `confirm_offset` | [1, 2, 3] | 1 | touch 봉(i) 으로부터 확인봉 거리. entry = i+offset+1 open |
| `vol_sma_period` | [10, 20, 50] | 20 | 확인봉 volume 정규화 분모 길이 (cell 비닝에만 영향) |
| `rsi_period` | [7, 14, 21] | 14 | 확인봉 RSI 길이 (cell 비닝에만 영향) |

Marginal sweep: 한 axis 만 default 와 다르게 두고 나머지는 default 고정. Default 포인트 1 + 비-default 9 = **총 10 combos**.

## 방법

각 combo 마다 553 USDT-M 1H 캐시 순회. 1W close 로 MA(`ma_period_weekly`) 계산, `shift(1)` 으로 prev-week lock. slope_up 상태 + 1H low≤MA_locked≤high 인 주간 첫 봉 = touch 봉(i). 확인봉(i+offset) feature 측정 후 i+offset+1 open 진입. forward returns 1/6/24/72/168/336/672h.

확인봉 feature: `body_ret`, `color_green`, `vol_ratio`, `up_wick_ratio`, `low_wick_ratio`, `rsi`, `touch_depth(=touch 봉 low gap)`.

## 핵심 결과

### Sweep axis ① `ma_period_weekly` (게이트 MA 길이)

| ma_period | n@168h | mean@168h | win@168h | var_adj@168h | n@672h | mean@672h | win@672h | var_adj@672h |
|---|---|---|---|---|---|---|---|---|
| 10w | 4,804 | +0.45% | 43.5% | -0.277 | 4,708 | **+1.06%** | **40.1%** | -0.681 |
| 20w (def) | 2,898 | -0.15% | 43.9% | -0.273 | 2,863 | -3.16% | 32.7% | -0.836 |
| 30w | 1,783 | -1.01% | 41.7% | -0.285 | 1,760 | -4.35% | 32.6% | -0.859 |
| 50w | 1,546 | +0.19% | **45.5%** | -0.256 | 1,537 | -1.01% | **38.6%** | -0.477 |

→ **`ma_period_weekly` 가 가장 큰 효과축**. 50w MA 가 168h win 45.5% 로 최고 (default 20w 보다 +1.6pp), 672h win 38.6% 로 +5.9pp 개선. var_adj 도 50w 가 가장 덜 음수. 10w MA 는 표본 65% 증가하면서 672h win 40.1% — 표본/안정성 trade-off.

### Sweep axis ② `confirm_offset` (확인봉 거리)

| offset | n@168h | mean@168h | win@168h | var_adj@168h | n@672h | mean@672h | win@672h |
|---|---|---|---|---|---|---|---|
| 1 (def) | 2,898 | -0.15% | 43.86% | -0.273 | 2,863 | -3.16% | 32.66% |
| 2 | 2,897 | -0.40% | 43.49% | -0.269 | 2,863 | -3.40% | 32.62% |
| 3 | 2,897 | -0.52% | 43.49% | -0.267 | 2,863 | -3.45% | 32.31% |

→ 확인봉을 멀리 둔다고 개선 X. 1~3 모두 동일 수준 (~43.5%). **이 axis 는 무력**.

### Sweep axis ③ `vol_sma_period` & ④ `rsi_period`

overall summary 는 동일 (이 두 axis 는 events 자체에 영향 X, cell 비닝만 변경). 그래서 sub-cell grid 에서만 의미. 아래 ⑤ 참조.

### Sweep × Top 1D cell @ 168h (`n ≥ 100`)

각 combo 의 최고 win cell:

| combo | feature | quantile | n | mean | win | var_adj |
|---|---|---|---|---|---|---|
| ma=10 | rsi | (1.3, 27.1] | 960 | +2.73% | **50.10%** | -0.302 |
| ma=20, offset=1, rsi=14 (def) | rsi | (0.6, 25.6] | 579 | +1.15% | **50.78%** | -0.286 |
| ma=20, rsi=7 | rsi | (26.9, 40.9] | 577 | +0.52% | 48.87% | -0.237 |
| ma=20, rsi=21 | touch_depth | (0.74%, 1.39%] | 580 | -0.50% | 47.93% | -0.236 |
| ma=20, vol_sma=10 | rsi | (0.6, 25.6] | 579 | +1.15% | **50.78%** | -0.286 |
| ma=20, vol_sma=50 | rsi | (0.6, 25.6] | 579 | +1.15% | **50.78%** | -0.286 |
| ma=20, offset=2 | up_wick_ratio | (-0, 0.062] | 580 | +0.28% | 49.83% | -0.221 |
| ma=20, offset=3 | up_wick_ratio | (0.065, 0.167] | 576 | +1.56% | **50.17%** | -0.279 |
| ma=30 | body_ret | (-40.7%, -1.09%] | 357 | +3.41% | 49.02% | -0.367 |
| **ma=50** | **up_wick_ratio** | **(0.054, 0.149]** | **310** | **+1.17%** | **🏆 54.52%** | **-0.217** |

→ **ma=50 + up_wick (작은 윗꼬리)** 가 모든 sweep 통틀어 **win 54.5%** 최고. mean +1.17%, n=310 으로 ④(n≥100) 통과, ②(win≥50%) 통과, ⑤(baseline 43.9% +5pp 이상) 통과. 그러나 var_adj -0.217 로 ③(VaR-adj>0) 실패.

### 종합 판정

| 기준 | 통과 cell |
|---|---|
| ① mean@168h > 0 | 많음 (ma=10 default cell, ma=50 up_wick, ma=20 rsi 등) |
| ② win@168h ≥ 50% | **ma=50 + up_wick (54.5%)**, ma=10 rsi (50.1%), ma=20 rsi (50.8%), ma=20 offset=3 up_wick (50.2%) |
| ③ var_adj@168h > 0 | **0개** ❌ |
| ④ n ≥ 100 | 위 4 cell 모두 통과 |
| ⑤ baseline +5pp | ma=50 + up_wick: 54.5% − 43.9% = +10.6pp ✅ |

→ **③ VaR-adj 통과 cell 없음**. PLAN.md L1 폐기 조건 발동 (엄격 해석).

단 **ma=50 + 작은 윗꼬리** cell 은 ①②④⑤ 4/5 통과 — 분산 컨트롤 (예: TP/SL) 만 추가하면 ③ 도 끌어올릴 가능성 있음.

## 시사점

1. **`ma_period_weekly` 가 가장 강한 sweep axis**. 50w MA 게이트가 20w default 보다 168h/672h 모두 win 우수. **다음 run (L2 이상) 에서는 50w 기준으로 진행해야 함**.
2. `confirm_offset` 은 0 효과. 1로 고정.
3. 50w MA + 윗꼬리 작은 양봉 (≈ "확인봉이 강한 양봉으로 마감, 위 저항 없음") 이 유일한 후보 cell. n=310, win 54.5%.
4. 단순 sweep 으로는 ③(VaR-adj) 통과 못함 → **L2 에서 exit 룰 (TP/SL/trailing) 그리드 결합** 필수.
5. `vol_sma_period`, `rsi_period` 는 events 자체에 영향 없음 — 다음 sweep 에서는 빼고 다른 knob (예: touch_pad 허용치, slope_threshold) 으로 교체 권장.

## 산출물

| 파일 | 크기 | 설명 |
|---|---|---|
| `output/events_all.parquet` | 2.8 MB | 모든 combo 의 events (param 컬럼 포함) |
| `output/sweep_overall.csv` | 8.5 KB | combo × horizon 전체 long 표 |
| `output/sweep_ma_period_weekly.csv` | 0.8 KB | ma_period_weekly marginal (wide) |
| `output/sweep_confirm_offset.csv` | 0.7 KB | confirm_offset marginal (wide) |
| `output/sweep_vol_sma_period.csv` | 0.7 KB | vol_sma_period marginal (wide) |
| `output/sweep_rsi_period.csv` | 0.7 KB | rsi_period marginal (wide) |
| `output/sweep_grid1d.csv` | 327 KB | combo × feature × quintile × horizon (long) |
| `output/sweep_top_cells.csv` | 7.5 KB | combo × top-5 1D cells @ 168h |

## 재현

`REPRODUCE.md` 참조.
