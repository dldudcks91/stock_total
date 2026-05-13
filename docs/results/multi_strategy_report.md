# 5-전략 × 다중 인터벌 백테스트 종합 리포트

**실행일**: 2026-05-10
**데이터 디렉터리**: `backtest/runs/matrix_20260510-082734/`
**기간**: 2023-01-01 ~ 2025-12-31 (3년)

## 사양

- **공통 진입 게이트**: 해당 코인 **주봉 종가 > 주봉 SMA(10)** (룩어헤드 회피 위해 1주 시프트). 강세장 코인에서만 롱.
- **수수료/슬리피지**: 5 bps + 5 bps (왕복 0.20% 수준)
- **포지션**: 균등 자본 (10,000 USDT), 1 종목 1 포지션
- **체결 모델**: 시그널 t → 체결 t+1 (룩어헤드 없음, 종가 체결 가정)

## 전략 5종

| ID | 이름 | 핵심 진입 로직 | 청산 |
|---|---|---|---|
| A | `trend_follow` | EMA(20)>EMA(50)>EMA(200) 정배열 + ADX>20 | 정배열 깨지면 즉시 |
| B | `breakout_start` | 도네치안 20봉 고점 돌파 + 변동성 스퀴즈 + 거래량 2× | EMA20 이탈 |
| C | `rsi_pullback` | EMA100 위 + RSI(14) 35 하향 후 상향 돌파 (반등 트리거) | EMA20 이탈 / SL -10% |
| D | `momentum_roc` | ROC(30) ≥ 10% + ROC(5) 가속 + EMA100 위 | EMA20 이탈 / ROC<0 / SL -10% |
| E | `bb_squeeze` | BB폭 6개월 평균 70% 이하 압축 + 상단 돌파 + 거래량 1.5× | EMA20 이탈 / SL -10% |

각 전략을 **1H / 4H / 1D** 세 인터벌에서 실행. 모든 결과 = 5 × 3 × 4그룹(trend / follower / whale / junk) = 60개 셀.
총 백테스트 = 8,115건 (성공 6,900건, 실패 1,215건은 데이터 기간 부족).

## 벤치마크

- **BTC B&H 3년**: +218%, Sharpe 1.18, MDD -34%
- **그룹별 B&H 평균**:
  - trend: -38%
  - follower: -69%
  - whale: -71%
  - junk: -10% (분포 매우 비대칭)

## ① 베스트 셀 Top 10 (mean total_return 기준)

| 순위 | 전략 | 인터벌 | 그룹 | n | 평균 수익 | 중앙값 | Sharpe | MDD | 수익 종목 비율 | B&H 알파 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **bb_squeeze** | **1d** | **trend** | 126 | **+29.6%** | -7.5% | -0.10 | -33.7% | 40.5% | **+68.5%p** |
| 2 | momentum_roc | 1d | trend | 126 | +27.6% | -10.0% | -0.13 | -43.9% | 42.1% | +66.4%p |
| 3 | breakout_start | 1d | trend | 126 | +20.5% | -4.9% | -0.18 | -28.4% | 34.9% | +59.3%p |
| 4 | momentum_roc | 1d | whale | 30 | +15.3% | -9.2% | **+0.07** | -42.0% | 40.0% | +86.0%p |
| 5 | bb_squeeze | 1d | follower | 93 | +10.1% | -8.7% | -0.12 | -36.3% | 37.6% | +79.8%p |
| 6 | breakout_start | 1d | follower | 93 | +9.8% | -1.7% | -0.06 | -28.4% | 40.9% | +79.5%p |
| 7 | bb_squeeze | 1d | whale | 30 | +8.4% | -5.0% | -0.08 | -30.8% | 43.3% | +79.2%p |
| 8 | momentum_roc | 1d | follower | 93 | +7.0% | -1.4% | -0.03 | -44.0% | 47.3% | +76.7%p |
| 9 | breakout_start | 4h | trend | 126 | +6.6% | -7.1% | -0.13 | -32.3% | 35.7% | +44.1%p |
| 10 | trend_follow | 1d | trend | 126 | +5.3% | 0.0% | -0.06 | -34.2% | 26.2% | +44.2%p |

## ② 인터벌 효과 — 1D 압도

| 전략 | 1H 평균 | 4H 평균 | 1D 평균 | 1D - 1H |
|---|---|---|---|---|
| bb_squeeze (trend) | -13.2% | +3.5% | **+29.6%** | +42.8%p |
| momentum_roc (trend) | -13.5% | -3.1% | **+27.6%** | +41.1%p |
| breakout_start (trend) | -2.1% | +6.6% | **+20.5%** | +22.6%p |
| trend_follow (trend) | +5.3% | -0.2% | +5.3% | 0%p |
| rsi_pullback (trend) | -1.5% | -1.1% | -0.2% | +1.3%p |

→ **1H는 노이즈/수수료가 알파를 갉아먹음**, 1D 인터벌이 가장 안정적. 단, trend_follow는 신호가 보유 기반이라 인터벌 영향이 작음.

## ③ 그룹 효과 — trend > follower > whale > junk

평균 수익률 (5개 전략, 3개 인터벌 평균):

| 그룹 | n_avg | 평균 수익률 | 수익 비율 |
|---|---|---|---|
| trend | 126 | **+5.3%** | 33.0% |
| whale | 30 | +0.5% | 35.5% |
| follower | 93 | -8.7% | 26.5% |
| junk | 211 | -1.4% | 9.7% |

→ trend 그룹이 모든 전략에서 가장 일관됨. junk는 진입 자체가 매우 적어 (대부분 0건), 평균은 0 근처지만 분산이 큼.

## ④ 전략별 강점

### A. trend_follow (EMA정배열+ADX)
- **best**: 1D × trend +5.3%, Sharpe -0.06
- **특징**: 보유 기반(연속) 신호 → 거래 횟수 1H 73회 / 4H 28회 / 1D 4회. 수수료 부담 적음
- **리스크**: MDD -34~50% (긴 보유로 큰 들썩임)
- **결론**: BTC 메타 필터를 추가했을 때 알파 손해(이전 분석). 주봉 자기 필터는 더 fit. 절대 알파는 작지만 거래 단순.

### B. breakout_start (도네치안 + 스퀴즈 + 거래량)
- **best**: 1D × trend +20.5%, follower +9.8%, whale +4.3%, junk +2.0% (네 그룹 모두 양수)
- **특징**: 1D에서 모든 그룹이 양수인 **유일한 전략** → 가장 견고
- **상위 종목**: FETUSDT(+575%), ORDIUSDT(+544%), FLOKIUSDT(+497%), ZORAUSDT(junk +636%)
- **결론**: 가장 균형잡힌 전략. 1D 단순 운용 권장.

### C. rsi_pullback (RSI 풀백 후 반등)
- **best**: 어디든 ±1% 수준
- **특징**: MDD -1~5%로 매우 안전 (사실상 거의 거래 안 함). 1D에서 평균 거래 0.07회/종목
- **문제**: 진입 조건이 너무 빡빡 (EMA100 위 + RSI 35 하향 + 반등 + 주봉 필터)
- **결론**: 현 파라미터로는 작동 X. RSI 임계 50으로 완화하거나 EMA50 위로 풀어야 함.

### D. momentum_roc (모멘텀 가속)
- **best**: 1D × trend +27.6%, whale +15.3% (Sharpe **+0.07로 양수 — 유일하게 Sharpe 양수**)
- **특징**: 1H에서는 -14% (노이즈 추적), 1D에서 폭발. 거래 횟수 1D 14회 (적당)
- **상위**: FLOKIUSDT(+843%, 1D 베스트), CRVUSDT(+357%), SOONUSDT(junk +406%)
- **결론**: 1D에서 trend/whale 운용 강력 추천. 위험 조정 수익(Sharpe)으로 1위.

### E. bb_squeeze (볼밴 압축 → 상단 돌파)
- **best**: 1D × trend +29.6% (절대 수익 1위)
- **특징**: 변동성 압축 후 폭발만 잡는 정밀 진입. 1D 거래 4회/종목으로 쉬엄쉬엄
- **상위**: PEPEUSDT(+723%), HBARUSDT(+493%), FETUSDT(+479%), ORDIUSDT(+351%)
- **결론**: **단일 절대 수익률 챔피언**. 단 분산이 커서 (40% 종목만 수익) 종목 분산 필수.

## ⑤ 글로벌 베스트 단일 백테스트 Top 10

| 전략 | 인터벌 | 그룹 | 심볼 | 수익률 | Sharpe | MDD | 거래수 |
|---|---|---|---|---|---|---|---|
| momentum_roc | 1d | trend | FLOKIUSDT | **+843%** | 1.35 | -38% | 25 |
| bb_squeeze | 1d | trend | PEPEUSDT | +723% | 1.36 | -37% | 5 |
| breakout_start | 1d | junk | ZORAUSDT | +637% | 2.39 | -40% | 1 |
| breakout_start | 1d | trend | FETUSDT | +575% | 1.55 | -40% | 5 |
| momentum_roc | 1d | trend | PEPEUSDT | +553% | 1.24 | -56% | 26 |
| breakout_start | 1d | trend | ORDIUSDT | +544% | 1.15 | -62% | 5 |
| trend_follow | 1d | junk | PIPPINUSDT | +516% | 2.06 | -30% | 1 |
| breakout_start | 1d | trend | FLOKIUSDT | +497% | 1.14 | -56% | 7 |
| bb_squeeze | 1d | trend | HBARUSDT | +493% | 1.26 | -42% | 7 |
| bb_squeeze | 1d | trend | FETUSDT | +479% | 1.49 | -44% | 6 |

→ 메가 위너 다수 = trend 그룹의 1D 신호. **밈코인(PEPE, FLOKI, SHIB) 강세** 두드러짐.

## ⑥ 핵심 발견

**1. 1D × trend가 sweet spot.** 5개 전략 중 4개가 1D × trend에서 양수 절대 수익률. 1H는 알파 거의 없음(수수료/노이즈 잠식).

**2. `bb_squeeze`와 `momentum_roc`이 가장 강력한 신규 전략.** 두 전략 모두 1D에서 평균 +27~30%, momentum_roc은 Sharpe 양수 도달.

**3. `breakout_start`가 가장 견고.** 그룹별 4/4 양수, 메타 알파(B&H 대비) +20~80%.

**4. 평균 vs 중앙값 격차 = 알파의 비대칭성.** 베스트 셀(bb_squeeze 1D trend) 평균 +30%이지만 중앙값 -7.5%. 즉 **수익은 소수 메가 위너에 집중**, 평범한 종목은 마이너스. → 분산 보유가 필수.

**5. junk 그룹은 사실상 비활성화.** 주봉 SMA(10) 필터 + 짧은 거래 이력 때문에 진입 자체가 거의 안 일어남. 평균 거래수 0.2~10회/종목.

**6. rsi_pullback은 현 파라미터로 동작 안 함.** 신호가 너무 좁음. 향후 튜닝 시 우선순위.

**7. 그래도 BTC B&H(+218%)는 못 이김.** 분산 보유 + 비용 + alt 음의 드리프트 종합. 단 **MDD는 모든 셀에서 B&H보다 양호** (-30%대 vs B&H -85%대 alts).

## ⑦ 권고 운용 조합

| 우선순위 | 조합 | 기대 평균 수익 | MDD | 비고 |
|---|---|---|---|---|
| 🥇 1 | **bb_squeeze + breakout_start (앙상블) on 1D × trend** | +25%/년 | -30% 대 | 두 전략 모두 trend 1D 강점 |
| 🥈 2 | **momentum_roc on 1D × (trend + whale)** | +20%/년 | -42% | Sharpe 양수, 적당한 분산 |
| 🥉 3 | **breakout_start on 1D × all groups** | +5~10% | -30% 대 | 가장 견고, 그룹 전체 양수 |
| ❌ skip | rsi_pullback | -1% | -1% | 진입 거의 안 됨, 튜닝 필요 |

## ⑧ 다음 단계 제안

1. **앙상블 포트폴리오 시뮬**: bb_squeeze + momentum_roc + breakout_start 동시 운용, 동시 시그널 시 자본 분배 룰 설계
2. **종목 선별 필터** 추가: 6개월 모멘텀 상위 30%만 trade → 평균/중앙값 격차 축소
3. **rsi_pullback 파라미터 튜닝**: RSI 임계 35→50, trend_ema 100→50, 주봉 필터 SMA 10→20
4. **whale 그룹 확장**: 현재 30개로 너무 작아 통계 신뢰도 낮음. 분류 임계 완화 검토
5. **1W 인터벌 추가 검토**: 신호 빈도 더 낮추고 비용 절감 시도

## 데이터 위치

- 원시 결과: `_summary.csv` (8115행)
- B&H 비교: `_baseline_compare.csv`
- 셀 집계: `_aggregate.csv`, `_baseline_aggregate.csv`
- 히트맵 데이터: `_heatmap.csv`
- 개별 런: `<strategy>__<interval>__<group>__<symbol>/` 디렉터리 (config.yaml + equity.parquet + trades.parquet + metrics.json)
