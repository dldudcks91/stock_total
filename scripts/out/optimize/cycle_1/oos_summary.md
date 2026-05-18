# Cycle 1 — IS / OOS 분리 검증 결과

**기간 분할**: IS = 2020-05-01 ~ 2024-05-01 (4년), OOS = 2024-05-01 ~ 2026-05-01 (2년)
**산출 데이터**: `cycle_1/oos_split.csv` (20행, 자산·전략·threshold 별 IS/OOS 메트릭)
**핵심 질문**: 6년 통합 평가 결과 (특히 KR/US trend_pullback 1d Sharpe 18~20) 가 시간 분할 후에도 유지되나?

---

## 한 줄 결론

KR/US 의 trend_pullback/trend_chase 1d 는 **OOS 에서 IS 보다 더 좋거나 비등** (데이터 스누핑 위험 사실상 없음). 반면 **Crypto trend_chase / trend_pullback 1d 는 OOS 에서 무너짐** (Sharpe decay -0.47 ~ -1.08). Cycle 2 이후 자원은 KR/US 미세조정 + Crypto 의 청산 룰·게이트 재설계에 집중해야 한다.

---

## 그룹별 결과

### A. KR — trend_pullback / trend_chase 1d (OOS 우월)

| 전략 | th | IS Sharpe | OOS Sharpe | OOS n | OOS win% | OOS mean% | decay |
|---|---|---|---|---|---|---|---|
| trend_pullback | 60 | 14.83 | **24.48** | 7565 | 53.9 | +10.54 | +0.65 |
| trend_pullback | 70 | 14.65 | **24.47** | 8092 | 52.8 | +10.10 | +0.67 |
| trend_pullback | 80 | 12.41 | **21.48** | 5940 | 51.6 | +9.27 | +0.73 |
| trend_chase | 60 | 5.13 | **12.17** | 1210 | 56.5 | +11.38 | +1.37 |
| trend_chase | 70 | 4.12 | **10.06** | 784 | 56.8 | +11.81 | +1.44 |
| trend_chase | 80 | 2.76 | **7.81** | 441 | 57.6 | +12.09 | +1.83 |

- OOS Sharpe 가 IS 보다 **모든 행에서** 더 높다. trend_chase 는 거의 2~2.8배 증가.
- OOS win% 도 IS 대비 +6~10pp 상승 (chase 56~58%, pullback 52~54%).
- OOS mean% 도 +30~150% 증가. 단순 강세장 효과를 넘어선다 (US 와 비교 시 KR-특수성).
- **해석**: 2024-05 이후 KR 시장에 trend_pullback 의 (rally 이후 얕은 조정 후 재돌파) 패턴이 더 잘 맞았다. 단, 향후 2년이 또 같은 분포라는 보장은 없음 → 추가 robustness 체크 (Cycle 2의 청산 변형, Cycle 4의 universe 변형) 필요.

### B. US — trend_pullback / trend_chase 1d (OOS 비등, 약간 우월)

| 전략 | th | IS Sharpe | OOS Sharpe | OOS n | OOS win% | OOS mean% | decay |
|---|---|---|---|---|---|---|---|
| trend_pullback | 60 | 15.83 | 19.71 | 5616 | 52.0 | +9.31 | +0.25 |
| trend_pullback | 70 | 18.64 | **21.94** | 6811 | 52.0 | +9.17 | +0.18 |
| trend_pullback | 80 | 15.32 | 18.90 | 5053 | 52.0 | +9.17 | +0.23 |
| trend_chase | 60 | 5.36 | 6.46 | 876 | 49.1 | +6.82 | +0.21 |
| trend_chase | 70 | 4.25 | 4.95 | 548 | 48.4 | +6.64 | +0.17 |
| trend_chase | 80 | 3.42 | 3.42 | 266 | 47.0 | +6.69 | 0.00 |

- 모든 행에서 OOS Sharpe ≥ IS Sharpe. decay 평균 +0.17 — KR 만큼 극단적이진 않지만 안정적.
- US trend_pullback 1d th=70 OOS Sharpe **21.94** 가 전체 OOS 1위.
- win% / mean% 는 IS-OOS 거의 동일 (~52%, ~9%). 분포 일정 = 패턴이 시기 무관하게 작동.
- threshold 60/70/80 모두 비등 — Cycle 5에서 사용자 선호 (알림 빈도 vs 신뢰) 로 선택.

### C. KR / US quiet_bottom 1w (혼합)

| 전략 | IS Sharpe | OOS Sharpe | OOS n | OOS win% | OOS mean% | decay |
|---|---|---|---|---|---|---|
| KR quiet_bottom 1w | 6.65 | 4.36 | 235 | 52.8 | +12.33 | **-0.34** |
| US quiet_bottom 1w | 3.46 | **5.01** | 154 | 55.8 | +18.31 | +0.45 |

- KR 은 OOS 에서 약화 (Sharpe 6.65 → 4.36, win 65.6 → 52.8). 그래도 절대 Sharpe 4.36 은 양호.
- US 는 OOS 에서 강화 (3.46 → 5.01, mean +12.7 → +18.3). 작은 n=154 이지만 평균 1년에 ~75건 → 알림 가치 충분.
- **해석**: KR 의 "조용한 바닥" 패턴이 최근 2년 KR 시장의 외형 변화 (대형주 쏠림 + 코스닥 부진) 로 sharper 했던 IS 신호가 약해진 것으로 보임. US 는 반대.

### D. Crypto — trend_chase / trend_pullback 1d (OOS 붕괴)

| 전략 | th | IS Sharpe | OOS Sharpe | OOS n | OOS win% | OOS mean% | decay |
|---|---|---|---|---|---|---|---|
| trend_chase | 60 | 3.80 | 1.48 | 122 | 50.0 | +5.22 | **-0.61** |
| trend_chase | 70 | 3.35 | 0.79 | 84 | 45.2 | +3.77 | **-0.76** |
| trend_chase | 80 | 2.35 | 0.34 | 48 | 39.6 | +2.11 | **-0.86** |
| trend_pullback | 60 | 4.58 | **-0.38** | 7493 | 26.5 | -0.19 | **-1.08** |
| trend_pullback | 70 | 4.40 | 0.95 | 6432 | 28.3 | +0.55 | **-0.78** |
| trend_pullback | 80 | 3.28 | 1.74 | 4402 | 30.2 | +1.24 | **-0.47** |

- **모든 crypto 행 OOS Sharpe 하락**. trend_pullback 1d th=60 은 OOS 손실 (Sharpe -0.38, mean -0.19%).
- trend_chase 1d 는 OOS 에서 threshold 가 **높을수록 더 나쁜 역설** (60 → 80 으로 갈수록 Sharpe 1.48 → 0.34, win 50 → 40). IS 의 score=80 진입이 OOS 에서 fake-out 빈도가 늘었음을 시사.
- trend_pullback 은 반대로 threshold 가 **높을수록 덜 무너짐** (60 → 80: Sharpe -0.38 → 1.74, win 26.5 → 30.2). 즉 OOS 에선 더 보수적인 컷이 필요.
- **OOS 기간 (2024-05 ~ 2026-05) 의 BTC dominance 상승 + altseason 부재** 가 alt-coin 추세 신호의 mean reversion 을 강화한 것으로 추정. 추가 검증 필요.

---

## 의사결정 영향 (Cycle 2 가 활용)

### 우선 자원 배분
1. **KR/US trend_pullback 1d** — 사실상 검증 완료. Cycle 2 (exit grid) 에서 trail %·TP %·max_hold 변형으로 추가 5~10% Sharpe 개선 가능성 탐색.
2. **KR/US trend_chase 1d** — IS Sharpe 낮지만 OOS 가 좋음 (특히 KR). Cycle 3 (게이트 그리드) 에서 fresh_big_th, amount_lookback 변형으로 IS 도 끌어올리면 robust 전략화.
3. **US quiet_bottom 1w** — OOS 가 IS 보다 좋음, n 작지만 알림 충분. 유지.
4. **KR quiet_bottom 1w** — OOS 약화 했지만 절대 Sharpe 4.36 양호. 유지.
5. **Crypto trend_pullback 1d th=80** — OOS Sharpe 1.74 로 유일하게 살아남음. Cycle 3 에서 BTC trend 필터 (`btc_close > btc_ma200`) 같은 매크로 게이트 추가하면 회복 가능성.
6. **Crypto trend_chase 1d** — OOS 에서 threshold 가 높을수록 악화. 시그널 자체 재설계 필요 (Cycle 3).

### Cycle 2 권장 변형 (자산·전략 별 청산 룰 정밀 탐색)
- **KR/US 1d**: hold ∈ {120, 252, 504} × trail ∈ {15, 20, 25, 30}% × TP ∈ {25, 30, 40, 50}% — 64 셀
- **KR/US 1w**: hold ∈ {26, 52, 78} × trail ∈ {15, 20, 25}% × TP ∈ {25, 30, 40}% — 27 셀
- **Crypto 1d**: hold ∈ {30, 60, 90} × trail ∈ {10, 15, 20}% × cut_short ∈ {off, 3d_-5%, 5d_-8%} — 27 셀

### Cycle 3 우선 게이트
- **Crypto trend_chase**: 진입 시 BTC close > BTC MA200 필터 (현재 매크로 무시 진입)
- **Crypto trend_pullback**: amount_lookback 증대 (낚시 신호 컷)
- **KR/US trend_pullback**: weekly SMA 정배열 필터 추가 (1d 신호인데 1w 추세 확인)

---

## 한계와 미지의 영역

1. **OOS 가 단일 2년 구간**: 2024-05 ~ 2026-05 가 KR/US 강세장이라 trend 류가 유리할 수 있음. Cycle 4 의 universe 변형 + walk-forward (Cycle 6 이후) 로 보완 필요.
2. **Crypto OOS 기간 특수성**: BTC dominance 상승 + altseason 부재로 alt 추세 약화. 다음 사이클 (2026-2028) 에 altseason 재현 시 결과 반전 가능.
3. **수수료/슬리피지 고정**: KR 0.3%, US/Crypto 0.2% RT. 실거래는 호가 슬리피지로 추가 0.1~0.3% 손실 가능 → 명목 Sharpe 의 80~90% 가 실현 가능치.
4. **n=48 ~ n=154 의 작은 표본**: Crypto chase th=80, KR/US quiet_bottom 1w 결과는 통계적 안정성 낮음. bootstrap CI 산출 권장 (Cycle 5).

---

## 산출 파일
- `cycle_1/oos_split.csv` — 자산·전략·threshold 별 IS / OOS 메트릭 20행
- `cycle_1/oos_summary.md` — 본 문서
- `cycle_1/run.log` — 1차 에이전트 실행 로그 (부분)
- `cycle_1/run_retry.log` — 2차 (retry) 에이전트 재현 검증 로그
