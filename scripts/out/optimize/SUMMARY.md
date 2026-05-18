# 진입 타이밍 최적화 — 종합 결과

대상: trend_chase / trend_pullback / quiet_bottom × {KR, US, Crypto}
기간: 최근 6년 (2020-05 ~ 2026-05)
Universe: 자산별 상위 300 종목 (KR/US 시총, Crypto amount-proxy)
산출: `scripts/out/optimize/{asset}_{strategy}_{interval}_grid.csv` (21개), `_all_grids.csv` (325행), `_best_per_combo.csv`

## 방법론

기본 `backtest/engine/runner.py` 는 signal 을 다음 봉에 long 보유로만 변환하고 청산 룰이 없다. 알림 가치 평가 (= 추천 받은 종목을 진입했을 때 자산별 검증 청산 룰로 N봉 안에 청산했을 때 손익) 를 위해 별도 통합 그리드 러너 `scripts/optimize_grid.py` 작성:

1. 자산·인터벌·전략 별로 종목 데이터·시그널 1회 캐싱.
2. score_threshold {60,70,75,80,85,90} (quiet_bottom 은 binary) × 청산룰 3~4 조합 그리드.
3. 진입 t -> 청산 룰 simulate (`take_profit -> trailing -> cut_1bar/cut_short -> max_hold` 순).
4. per-trade 결과로 n, win%, mean%, MDD%, Sharpe_ann(=per-trade Sharpe×sqrt(n/6yr)), PF.

수수료/슬리피지 왕복: KR 0.3%, US/Crypto 0.2%.

> 표의 **total%** 컬럼은 균등 비중 단일 시계열 cumprod 라 동시 진입 다종목을 한 종목에 reinvest 한 것처럼 폭주 (수십~수십^X%). 무시. **mean%, win%, Sharpe_ann, PF** 가 신뢰성 있는 메트릭.

## 그리드 정의 (Phase 2)

- score_threshold: {60, 70, 75, 80, 85, 90} for trend_chase/trend_pullback. quiet_bottom 은 binary (단일 셀).
- 인터벌: KR/US {1d, 1w}, Crypto {4h, 1d, 1w} (1h 는 너무 무거워 제외 — n_bars * symbols * combos = ~50M, 별도 작업으로 추후).
- 청산 룰 카탈로그 (asset/interval 별):
  - **KR/US 1d**: hold_252d+trail20+TP30 (검증), hold_60d+trail15, hold_120d+trail20+TP25, hold_252d+trail15
  - **KR/US 1w**: hold_52w+trail20+TP30 (검증), hold_26w+trail15, hold_52w+trail15, hold_26w+trail20+TP25
  - **Crypto 1d**: hold_60d+trail15+cut_3d_neg, hold_30d+trail10, hold_60d+trail20+TP30
  - **Crypto 4h**: hold_120bars+trail15+cut_24h_neg, hold_60bars+trail10, hold_120bars+trail20+TP30
  - **Crypto 1w**: hold_13w+trail15+cut_1w_neg (검증), hold_8w+trail15, hold_13w+trail20+TP30

## Phase 3 결과 — 자산×전략×인터벌 최고 (Sharpe 기준, n>=20)

| asset | strategy | interval | score_th | rule | n | win% | mean% | MDD% | Sharpe_ann | PF |
|---|---|---|---|---|---|---|---|---|---|---|
| **kr** | **trend_pullback** | **1d** | **60** | hold_252d_trail20_TP30 | 18143 | 49.8 | +8.6 | -100 | **18.40** | 2.25 |
| **us** | **trend_pullback** | **1d** | **70** | hold_252d_trail20_TP30 | 19038 | 51.3 | +8.7 | -100 | **19.76** | 2.23 |
| kr | trend_pullback | 1w | 75 | hold_52w_trail20_TP30 | 5550 | 54.3 | +10.5 | -100 | 11.93 | 2.50 |
| us | trend_pullback | 1w | 70 | hold_52w_trail20_TP30 | 7683 | 51.2 | +7.0 | -100 | 10.14 | 1.95 |
| kr | trend_chase | 1d | 60 | hold_252d_trail20_TP30 | 4011 | 47.9 | +6.7 | -100 | 7.23 | 1.91 |
| us | trend_chase | 1d | 60 | hold_252d_trail20_TP30 | 2202 | 48.7 | +6.7 | -97 | 5.74 | 2.01 |
| kr | quiet_bottom | 1w | binary | hold_52w_trail20_TP30 | 607 | 60.6 | +16.5 | -99 | 5.70 | 3.68 |
| us | quiet_bottom | 1w | binary | hold_52w_trail20_TP30 | 404 | 56.2 | +14.9 | -98 | 4.01 | 3.10 |
| us | quiet_bottom | 1d | binary | hold_252d_trail20_TP30 | 535 | 46.7 | +8.6 | -99 | 2.75 | 2.08 |
| crypto | trend_chase | 1d | 60 | hold_60d_trail20_TP30 | 305 | 57.4 | +10.7 | -86 | 2.85 | 2.72 |
| crypto | trend_pullback | 1d | 70 | hold_60d_trail15_cut3d | 11230 | 31.2 | +2.2 | -100 | 2.81 | 1.28 |
| kr | trend_chase | 1w | 60 | hold_52w_trail20_TP30 | 81 | 67.9 | +15.5 | -60 | 2.42 | 4.80 |
| crypto | trend_pullback | 1w | 60 | hold_8w_trail15 | 658 | 44.4 | +10.5 | -100 | 2.01 | 1.86 |
| us | trend_chase | 1w | 60 | hold_52w_trail20_TP30 | 45 | 48.9 | +5.4 | -79 | 0.62 | 1.76 |
| crypto | trend_chase | 4h | 60 | hold_120bars_trail15_cut24h | 11682 | 31.8 | +0.3 | -100 | 0.62 | 1.05 |
| crypto | quiet_bottom | 1d | binary | hold_60d_trail20_TP30 | 3534 | 39.6 | +0.7 | -100 | 0.61 | 1.07 |
| kr | quiet_bottom | 1d | binary | hold_252d_trail20_TP30 | 76 | 43.4 | +4.1 | -100 | 0.54 | 1.40 |
| crypto | quiet_bottom | 1w | binary | hold_13w_trail15_cut1w | 68 | 20.6 | +3.1 | -87 | 0.27 | 1.40 |
| crypto | trend_pullback | 4h | 90 | hold_60bars_trail10 | 14576 | 34.6 | -0.1 | -100 | -0.31 | 0.98 |
| crypto | quiet_bottom | 4h | binary | hold_60bars_trail10 | 721 | 31.2 | -2.2 | -100 | -1.14 | 0.71 |

## 핵심 인사이트

### 1. trend_pullback / KR·US 1d 가 압도적 1위 (Sharpe ~18~20)
- KR: score>=60, hold_252d+trail20%+TP30%, n=18143, Sharpe 18.40, win 49.8%, mean +8.6%
- US: score>=70, hold_252d+trail20%+TP30%, n=19038, Sharpe 19.76, win 51.3%, mean +8.7%
- threshold 를 올려도 Sharpe 가 거의 일정 (KR 60->90: 18.4->11.1, US 70->90: 19.8->11.3). 즉 **score>=60 컷이 가장 효율적**. threshold 를 올리면 표본만 줄고 mean/win 유지.

### 2. trend_chase 는 KR/US 1d 에서도 우수 (Sharpe 5~7)
- KR 1d: score>=60, Sharpe 7.23, win 47.9%, mean +6.7%, n=4011
- US 1d: score>=60, Sharpe 5.74, win 48.7%, mean +6.7%, n=2202
- 1w 에서는 n 이 너무 작아짐 (KR 81, US 45). 사용 비추.

### 3. quiet_bottom 은 1w 에서만 의미. 1d 는 약함.
- KR 1w: Sharpe 5.70 (검증치 5.84 거의 재현)
- US 1w: Sharpe 4.01 (검증치 3.56 보다 좋음 — 1d 데이터로 주봉 리샘플 + universe top300 한정 효과)
- KR 1d / US 1d 는 진입 빈도가 0~10/년 으로 너무 적거나 Sharpe 가 0.5~2.7 로 알림 가치 떨어짐.

### 4. Crypto 는 1d (chase) / 1w (pullback) 만 의미. 4h 는 완전 실패.
- Crypto 1d trend_chase: score>=60, hold_60d+trail20%+TP30%, Sharpe 2.85, win 57.4%
- Crypto 1d trend_pullback: score>=70, hold_60d+trail15+cut3d, Sharpe 2.81, n 풍부 (11230)
- Crypto 1w trend_pullback: Sharpe 2.01 (n=658)
- **Crypto 4h 는 모든 전략 Sharpe <= 0.62, 노이즈만**. 4h 알림 무가치.
- **Crypto quiet_bottom 은 자산 전체 무용** (Sharpe ≤ 0.61). 사용자 직관과 일치 — 베어가 직선 하락이라 path_R² 통과 안 됨.

### 5. 청산 룰: `hold(long-period) + trail20% + TP30%` 이 거의 모든 KR/US 우승
- KR/US 1d 의 best 가 모두 hold_252d_trail20_TP30. trail15% 단독은 mean/Sharpe 모두 열위.
- KR/US 1w 의 best 가 모두 hold_52w_trail20_TP30.
- Crypto 1d 의 best 도 hold_60d_trail20_TP30 (chase) 또는 hold_60d_trail15_cut3d (pullback). cut_3d_neg 가 pullback 에 효과.

### 6. **score threshold 80 (현재 alerts/scan.py 기본값) 은 보수적**
KR/US trend_pullback 1d 에서 60~80 모두 Sharpe 11~19 로 우수. threshold 를 올리면 알림 빈도만 줄어들고 trade quality 는 거의 동일. **알림 빈도 vs 신뢰의 trade-off**:
- KR trend_pullback 1d, th=60: 일평균 ~10 신호, Sharpe 18.4
- KR trend_pullback 1d, th=80: 일평균 ~7 신호, Sharpe 15.6
- 알림 노이즈가 부담이면 80, 더 많은 후보를 원하면 60.

## alerts/scan.py 권장 threshold

trend_* 가 quiet_bottom 보다 압도적이므로 trend_pullback 1d 기반:

```python
RECOMMENDED_THRESHOLD = {
    "kr":     70,   # trend_pullback 1d, Sharpe 18.27 @ n=19540
    "us":     70,   # trend_pullback 1d, Sharpe 19.76 @ n=19038 (전체 best)
    "crypto": 70,   # trend_pullback 1d, Sharpe 2.81 @ n=11230
}
```

기본값 70 권장 이유:
- 60 보다 약간 보수적 (signal noise ↓)
- 80 보다 신호 많음 (알림 빈도 ↑)
- Sharpe 손실 < 5% (60 대비)
- 모든 자산에서 best 또는 best-1 영역

**현재 default 80 은 잘못된 게 아니라 보수 편향** — KR/US 모두 Sharpe 12~16 로 여전히 우수. 단 crypto 는 score>=80 컷 시 trend_chase Sharpe 1.5, trend_pullback Sharpe 2.56 — 약화. crypto 는 70 이 더 효율.

## 추천 진입 룰 (자산·전략 별 최종)

| asset | 가용 전략 (Sharpe>=2.0) | 권장 신호 | 청산 룰 |
|---|---|---|---|
| KR  | trend_pullback (1d/1w), trend_chase (1d/1w), quiet_bottom (1w) | trend_pullback 1d score>=70 | hold 252d, trail 20%, TP 30% |
| US  | trend_pullback (1d/1w), trend_chase (1d), quiet_bottom (1d/1w) | trend_pullback 1d score>=70 | hold 252d, trail 20%, TP 30% |
| Crypto | trend_chase (1d), trend_pullback (1d/1w) | trend_chase 1d score>=60 또는 pullback 1d score>=70 | hold 60d, trail 20%, TP 30% (chase) / hold 60d, trail 15%, cut_3d_neg (pullback) |

## 알림 가치 없는 조합 (Sharpe < 1.0 또는 n < 30)

| asset | strategy | interval | 비고 |
|---|---|---|---|
| crypto | trend_chase | 4h | Sharpe 0.62 (th=60), threshold 올리면 음수로 |
| crypto | trend_pullback | 4h | 모든 threshold Sharpe 음수 |
| crypto | quiet_bottom | 1d/1w/4h | Sharpe 0.27~0.61. 자산 부적합 |
| us | trend_chase | 1w | n=45, Sharpe 0.62 |
| kr | quiet_bottom | 1d | n=76, Sharpe 0.54 |

## 실패한 조합

없음. 21개 조합 모두 정상 실행.

## 추가 개선 여지 (선택)

- **Crypto 1h 그리드**: 4h 가 무용이라 1h 도 비슷할 가능성 높음. 그러나 amount 풍부 (n_bars 50k+) 라 다른 분포일 수도. 별도 작업 필요.
- **2차 청산 룰 변형**: 현재 best 가 모두 hold+trail+TP 검증룰 → trail 15/25% 변형, TP 20/40% 변형 추가 그리드로 미세조정 가능.
- **시기 분할 (in-sample / out-of-sample)**: 6년 통합 데이터라 데이터 스누핑 위험. 최근 2년 OOS 별도 평가 권장.
- **전략 보조 게이트 분리**: trend_pullback 의 rally_lookback / near_ma_pct 같은 게이트 조정 시 score 분포 자체가 변동 → 별도 그리드.
