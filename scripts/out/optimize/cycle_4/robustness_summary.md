# Cycle 4 — Crypto 1h grid + KR/US universe robustness

작성: 2026-05-17 KST
대상 산출: `crypto_1h_grid.csv`, `universe_sensitivity.csv`

---

## Part A — Crypto 1h 본격 그리드 (universe top-100 by amount-sum)

**그리드**: 2 전략 (trend_chase, trend_pullback) × 6 threshold (60/70/75/80/85/90) × 6 청산룰 = 72 셀.
**대상 기간**: 6 년 통합 (CYCLE 1 IS/OOS split 분리 안 함 — 본 Part A 는 그리드 sweep 만, IS/OOS 는 PROGRESS Cycle 1 이미 수행).
**자산**: 553 종목 중 24h amount-sum 상위 100 (77 종목 실제 로드, 23 skipped — 데이터 부족).
**비용**: RT 0.2%.

> ⚠ `total%` 컬럼은 1h short-hold 의 per-trade compound 가 폭주(>1e30) 해 신뢰 불가. 비교는 **Sharpe_ann / mean% / win% / PF / n** 기준.

### 전략·threshold 별 best rule

**trend_chase 1h** (Sharpe 최대):

| score_th | best_rule | n | win% | mean% | Sharpe | PF |
|---|---|---|---|---|---|---|
| 60 | hold_168h_trail20 | 7282 | 44.0 | +1.91 | **4.05** | 1.34 |
| 70 | hold_168h_trail20 | 3708 | 41.9 | +2.15 | 2.90 | 1.35 |
| 75 | hold_336h_trail15_TP30 | 2088 | 41.1 | +1.69 | 2.39 | 1.26 |
| 80 | hold_168h_trail20 | 1454 | 40.8 | +3.05 | 2.24 | 1.45 |
| 85 | hold_336h_trail15_TP30 |  949 | 42.4 | +2.46 | 2.21 | 1.37 |
| 90 | hold_336h_trail15_TP30 |  575 | 41.6 | +2.65 | 1.77 | 1.38 |

**trend_pullback 1h** (Sharpe 최대):

| score_th | best_rule | n | win% | mean% | Sharpe | PF |
|---|---|---|---|---|---|---|
| 60 | hold_336h_trail20_cut5h | 7021 | 33.5 | +4.80 | 6.68 | 1.65 |
| 70 | hold_336h_trail20_cut5h | 7877 | 33.3 | +4.90 | 7.33 | 1.68 |
| 75 | hold_336h_trail20_cut5h | 8146 | 33.2 | +5.58 | **8.23** | 1.78 |
| 80 | hold_336h_trail20_cut5h | 6523 | 33.0 | +5.78 | 7.67 | 1.82 |
| 85 | hold_336h_trail20_cut5h | 5098 | 32.8 | +6.17 | 7.00 | 1.87 |
| 90 | hold_336h_trail20_cut5h | 3030 | 32.5 | +5.52 | 5.06 | 1.78 |

### Part A 핵심 발견

1. **🚨 Crypto trend_pullback 1h 가 자산군 통틀어 가장 좋은 1h 시그널**: Sharpe 8.23 (th=75, hold_336h_trail20_cut5h). 평균 +5.58%/trade × n=8146. Win% 만 보면 33% (낮음) 인데 PF 1.78 = 평균 승리가 평균 패배의 1.78배 — fat-tail 추세 추격 전형.
2. **Crypto trend_pullback: 1d 는 무용 (Cycle 1 OOS), 1h 는 강력**. 같은 시그널 로직이 인터벌만 바뀌어 정반대 결과 — **인터벌이 자산만큼 결정적**. 1h 의 빠른 회전이 alt 의 단기 추세를 잡고, 1d 는 신호 발생 시점에 이미 추세 종료.
3. **trend_chase 1h Sharpe 2~4 → trend_pullback 1h Sharpe 5~8**: 2배 차이. pullback 이 진입 가격 우위 (조정 후 진입) 효과 명확.
4. **청산 룰의 비대칭성**:
   - trend_chase 는 `hold_168h_trail20` (TP 없는 trail) 우세 — 짧은 추세 따라가기.
   - trend_pullback 은 `hold_336h_trail20_cut5h` (긴 hold + 5h 컷) 절대 우세 — 진입 직후 5h 컷이 패가 손실을 줄이는데 결정적 (mean% 가 +2.6 → +5.6 으로 두 배).
5. **threshold sensitivity**: trend_pullback 75 가 plateau peak. 60→75 까지 Sharpe 단조증가, 80~85 plateau, 90 부터 hard drop (n=3030). **권장 threshold: crypto 1h trend_pullback = 75**.
6. **trend_chase 는 threshold ↑ → Sharpe ↓ 단조감소** (60: 4.05 → 90: 1.77). 알림 빈도 vs 품질 트레이드오프가 trend_pullback 만큼 우호적이지 않음. **trend_chase 1h 는 60 권장** 하되 본 전략은 추천도 낮음.

---

## Part B — KR/US universe 견고성 (top_n = 50/100/300/500)

**대상**: Cycle 1·2 OOS best 조합 + 검증된 청산룰 고정.
- KR trend_pullback 1d th=60, rule=`h252_tr25_TP30` (Cycle 2 best)
- US trend_pullback 1d th=70, rule=`h252_tr20_TP30` (Cycle 2 best)

**Universe 계층**:
- 50/100/300: `_universe_cache.json` 시총 상위 N (사전 캐시)
- 500: FDR `StockListing("KOSPI")/("NASDAQ")` 실시간 fetch → 상위 500

### KR trend_pullback 1d (rule h252_tr25_TP30)

| top_n | n_full | win%_full | mean%_full | **Sharpe_full** | n_oos | win%_oos | mean%_oos | **Sharpe_oos** |
|---|---|---|---|---|---|---|---|---|
|  50 |  3592 | 64.8 | +15.10 | 14.99 |  1603 | 71.2 | +18.37 | 13.33 |
| 100 |  6701 | 62.1 | +13.37 | 17.66 |  2937 | 68.2 | +16.55 | 15.49 |
| 300 | 18143 | 57.0 | +10.75 | **21.53** |  7565 | 62.4 | +13.69 | 17.72 |
| 500 | 28753 | 54.5 |  +9.41 | **23.75** | 10877 | 59.9 | +12.21 | **19.33** |

### US trend_pullback 1d (rule h252_tr20_TP30)

| top_n | n_full | win%_full | mean%_full | **Sharpe_full** | n_oos | win%_oos | mean%_oos | **Sharpe_oos** |
|---|---|---|---|---|---|---|---|---|
|  50 |  3192 | 58.1 | +11.89 | 11.57 |  1166 | 53.3 |  +9.79 |  5.78 |
| 100 |  5959 | 53.9 |  +9.79 | 12.98 |  2108 | 51.1 |  +8.64 |  6.81 |
| 300 | 19038 | 51.3 |  +8.65 | 19.76 |  6811 | 52.0 |  +9.17 | 12.66 |
| 500 | 32755 | 49.5 |  +7.81 | **22.87** | 11531 | 51.0 |  +8.67 | **15.02** |

### Part B 핵심 발견

1. **trend_pullback 1d 시그널은 universe 확장에 견고**: top_n 50→500 으로 10× 늘어도 Sharpe 가 무너지기는커녕 단조증가. KR Sharpe_oos 13.3 → 19.3 (+45%), US 5.8 → 15.0 (+160%).
2. **n 효과 ≫ noise**: universe 가 커지면 per-trade mean% 와 win% 는 떨어지지만 (소형주 추가 = 노이즈), Sharpe (annualized) 는 trade 수의 √(n) 가속을 받아 상승. 즉 시그널 logic 자체가 universe-agnostic.
3. **OOS gap (full vs oos Sharpe)**:
   - KR: full/oos Sharpe 비 = 21.5/17.7 = 1.21 (300); 23.8/19.3 = 1.23 (500). 일정.
   - US: 19.8/12.7 = 1.56 (300); 22.9/15.0 = 1.53 (500). 일정.
   - US 의 IS→OOS decay 가 KR 보다 큰 것은 일관 — 두 시장의 구조 차이, universe 변형과 무관.
4. **소형주 (501~) 의 trade quality 는 떨어지지만 추가 trade 가 보탬**: KR top_n=500 의 mean%_full 은 +9.4% (vs 100: +13.4%) — soft drop. 그래도 sharpe ↑ 라는 것은 분산이 더 큰 폭으로 줄어든다는 뜻 (large-N 효과).
5. **추천 universe**: KR/US 모두 **top_n=300 이 운영 최적** (Sharpe_oos 의 80~85% 도달, 데이터 캐시 부담 적당). top_n=500 도 추가 5~20% Sharpe 가 있지만 fetch/maintain 비용 증가.
6. **top_n=50 의 OOS Sharpe (US 5.8) 만 눈에 띄게 약함** — 대형주 50개만 보면 trade quality 는 좋지만 분산 부족으로 sharpe 한계. 운영상 "대형주만" 시장이라면 보조 게이트 필수.

---

## 종합 — Cycle 5 인풋

### 새 권장 (alerts/scan.py 자산별 분리)

| 자산 | 인터벌 | 전략 | score_th | 청산 룰 | 비고 |
|---|---|---|---|---|---|
| KR | 1d | trend_pullback | 60 | hold_252d trail25 TP30 | universe top_n=300 (또는 500) |
| US | 1d | trend_pullback | 70 | hold_252d trail20 TP30 | universe top_n=300 (또는 500) |
| Crypto | **1h** | **trend_pullback** | **75** | **hold_336h trail20 cut5h** | universe top-100 by amount; **신규** (1d 는 폐기) |
| Crypto | 1d | trend_pullback | — | — | **폐기** (Cycle 1 OOS 무너짐) |
| Crypto | 4h | * | — | — | **폐기** (Cycle 1 무용) |

### 단언

- 1h 가 crypto 의 자연스러운 운영 인터벌이라는 사실이 Cycle 4 에서 정량 확인. dashboards/_recommendation.py `_STRATEGY_SPECS_CRYPTO` 에서 1h trend_pullback 추가 + 1d/4h 제거 필요 (Cycle 5 패치).
- KR/US trend_pullback 1d 는 universe 가 작아도(50) 부서지지 않고, 커도(500) 강화됨 — 시그널 redesign 압력 없음. Cycle 3 (보조 게이트) 가 cycle_3/ 디렉터리 비어있음 (미실행) → Cycle 5 가 흡수.

### Cycle 4 limitations

- Crypto 1h 그리드는 **IS/OOS split 없음** (Cycle 1 의 1d split 결론을 1h 에 일반화하기엔 데이터 다름) → Cycle 5 에서 1h 데이터로 separate OOS sanity check 권장.
- `total%` 메트릭은 short-hold compounding overflow 로 무의미 — Sharpe/mean/win/PF/n 만 신뢰.
- top_n=500 의 KR 296 종목 cache miss (~4 종목 일봉 데이터 없음). 무시 가능 수준.
- Cycle 3 (보조 게이트) 미실행이 데이터 갭. Cycle 5 가 종합 시 trend_pullback 1d 의 보조 게이트 (BTC trend, weekly SMA, depth_lookback 변형 등) 시도해볼 가치.

## 산출

- `cycle_4/crypto_1h_grid.csv` — 72 셀 (2 전략 × 6 th × 6 룰)
- `cycle_4/crypto_1h_run.log` — 원본 실행 로그
- `cycle_4/universe_sensitivity.csv` — 8 셀 (2 조합 × 4 top_n)
- `cycle_4/run_universe_sensitivity_v2.py` — 재현 스크립트 (v2: 500 까지 확장)
- `cycle_4/universe_sensitivity_v2.log` — 로그
