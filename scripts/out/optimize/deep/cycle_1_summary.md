# Cycle 1 Summary — 진단 + OOS Split + 청산 미세 그리드 (KR)

**일시**: 2026-05-17 17:42 KST 재가동
**런너**: `scripts/optimize/cycle1_oos_micro.py` (캐시 전용, 라이브 fetch 금지)
**원본 로그**: `scripts/out/optimize/deep/cycle1_v2_run.log`

---

## A. MDD = -100% 의미 진단 (결론)

**결론 한 줄**: `optimize_grid.summarize_trades()` 의 MDD 컬럼은 **모든 trade 의 net_ret 을 체결 순으로 단순 누적곱한 single-series equity 의 drawdown** 이다. 따라서 **동시 보유 / 균등 비중 / 자본 분산 모델이 전혀 반영되지 않은 수치이며, 알림 가치 평가용 메트릭으로는 무의미**하다.

### 근거 (코드 분석)

`scripts/optimize_grid.py:128-131`:
```python
rets = df["net_ret"].to_numpy()           # 모든 종목의 trade-level net return 1D 배열
eq = np.cumprod(1.0 + rets)                # 체결 순서로 단순 누적
peak = np.maximum.accumulate(eq)
dd = float((eq / peak - 1.0).min() * 100)  # 누적 곡선의 최대 낙폭
```

문제점:
1. **trade 간 동시성 무시** — n=18,000+ 의 trade 가 6년 안에 진입했다는 것은 일평균 ~10건 동시 보유라는 뜻인데, 위 식은 한 trade 가 끝난 뒤 다음 trade 가 들어가는 것처럼 1xN 직렬 누적
2. **균등 비중 reinvest 가정** — 매 trade 마다 직전 자본 100% 를 다음 trade 에 베팅 (cumprod). 한 번이라도 -100% 가 끼면 그 시점 이후 equity 가 0 으로 고정 → 그 다음 trade 가 모두 무의미
3. **MDD = -100% 가 KR/US 1d 전반에 걸치는 이유**: trade 한 건이라도 -100% 근처 (실제 상장폐지 or 시뮬레이션 종료 케이스) 가 끼면 cumprod 가 0 으로 짜부러져 그 후의 win trade 들이 회복 불가
4. **연환산 Sharpe 도 같은 데이터에서 계산** — Sharpe 는 trade 분포 자체의 평균/표준편차 → 분포 자체는 의미가 있음 (단, **trade 간 독립 가정**)

### 신뢰 가능한 메트릭 (계속 사용해도 좋음)
- `n` (시그널 개수) — 알림 빈도
- `win%` — 양수 net_ret trade 비율
- `mean%` / `median%` — trade-level return 의 중심
- `Sharpe_ann` — trade 분포의 risk-adj return (단, trade 간 독립 가정 시)
- `PF` (profit factor) — gains/losses 비

### 무시해도 좋은 메트릭
- `MDD%` ← **단일 trade 누적의 인공적 수치. 포트폴리오 MDD 가 아니다**
- `total%` ← MDD 와 동일 이유 (cumprod 결과)

### 정정 권장 (Cycle 5 작업)
진짜 **portfolio-level MDD/CAGR** 을 평가하려면:
1. trade 들을 entry_dt 로 정렬
2. 시점별 균등 비중 (예: 자본의 1/N 또는 max N 동시 보유) 할당 시뮬
3. daily equity 시리즈를 만들어 그 위에서 MDD/CAGR/Sharpe 재계산

→ Cycle 5 에서 `scripts/optimize/portfolio_simulator.py` 신규 작성 권장.

---

## B. OOS Split 검증 (train 2020-05-17 ~ 2024-05-16 vs test 2024-05-17 ~ 2026-05-17)

**대상 6 combos** (base SUMMARY.md best 파라미터 고정):

| asset | strategy | interval | score_th | 청산 룰 |
|---|---|---|---|---|
| KR | trend_pullback | 1d | 60 | hold_252d_trail20_TP30 |
| US | trend_pullback | 1d | 70 | hold_252d_trail20_TP30 |
| KR | trend_chase | 1d | 60 | hold_252d_trail20_TP30 |
| US | trend_chase | 1d | 60 | hold_252d_trail20_TP30 |
| KR | quiet_bottom | 1w | binary | hold_52w_trail20_TP30 |
| US | quiet_bottom | 1w | binary | hold_52w_trail20_TP30 |

상세 결과 표: `scripts/out/optimize/deep/grids/cycle1_oos_split.csv`

### 결과 표

| asset | strategy | interval | th | period | n | win% | mean% | Sharpe_ann | PF |
|---|---|---|---|---|---|---|---|---|---|
| KR | trend_pullback | 1d | 60 | train | 10,585 | 46.8 | +7.21 | 14.75 | 1.93 |
| KR | trend_pullback | 1d | 60 | **test** | 7,603 | 54.1 | +10.63 | **24.77** | 2.84 |
| US | trend_pullback | 1d | 70 | train | 12,247 | 50.6 | +8.19 | 18.27 | 2.12 |
| US | trend_pullback | 1d | 70 | **test** | 6,856 | 51.6 | +8.94 | **21.46** | 2.33 |
| KR | trend_chase | 1d | 60 | train | 2,810 | 44.0 | +4.53 | 5.00 | 1.55 |
| KR | trend_chase | 1d | 60 | **test** | 1,203 | 57.2 | +11.71 | **12.44** | 3.18 |
| US | trend_chase | 1d | 60 | train | 1,329 | 48.5 | +6.88 | 5.42 | 2.01 |
| US | trend_chase | 1d | 60 | **test** | 875 | 48.5 | +6.52 | 6.15 | 1.99 |
| KR | quiet_bottom | 1w | binary | train | 374 | 65.8 | +19.09 | 6.68 | 4.66 |
| KR | quiet_bottom | 1w | binary | **test** | 230 | 51.7 | +11.61 | 4.07 | 2.50 |
| US | quiet_bottom | 1w | binary | train | 254 | 57.1 | +13.12 | 3.60 | 2.77 |
| US | quiet_bottom | 1w | binary | **test** | 159 | 56.0 | +18.25 | **5.12** | 3.93 |

### 해석

- **trend_pullback (KR/US 1d)**: train < test (Sharpe, mean% 모두). 과적합 징후 없음. **test 기간에서도 안정**. 기준 파라미터 신뢰 가능.
- **trend_chase (KR 1d)**: train 5.00 → test 12.44 로 향상 (test 시장이 추세 우호적). 과적합 X.
- **trend_chase (US 1d)**: train/test 거의 동일 (Sharpe 5.4/6.2, mean 6.9/6.5). 강건.
- **quiet_bottom (KR 1w)**: train 6.68 → test 4.07 로 **저하**. mean 도 19% → 12% 로 줄어듦. 약간의 과적합 가능성. 단, win% 51.7% / PF 2.5 / mean +11.6% 는 여전히 실용 수준.
- **quiet_bottom (US 1w)**: train < test (3.60 → 5.12). 강건 ↑.

**결론**: 6 combos 모두 **test 기간 메트릭이 train 의 80% 이상 유지** (quiet_bottom KR 만 61%). 알림 시스템 운영에 무리 없음. quiet_bottom KR 만 cycle 2~3 에서 binary trigger 강화 검토 권장.

---

## C. KR Exit Rule Micro Grid (40 combos)

**대상**: `kr / trend_pullback / 1d`, `score_th=60`
- trail_pct ∈ {0.15, 0.18, 0.20, 0.22, 0.25}
- take_profit_pct ∈ {0.20, 0.25, 0.30, 0.35}
- max_hold ∈ {180, 252}

상세 결과: `scripts/out/optimize/deep/grids/cycle1_exit_micro_kr.csv`

### Best (Sharpe_ann 기준 top 10)

| rule | hold | trail_pct | TP_pct | n | win% | mean% | Sharpe_ann | PF |
|---|---|---|---|---|---|---|---|---|
| **hold_252d_trail25_TP35** | 252 | **0.25** | **0.35** | 18,188 | 54.0 | **+11.75** | **22.04** | 2.53 |
| hold_252d_trail25_TP30 | 252 | 0.25 | 0.30 | 18,188 | 57.0 | +10.76 | 21.57 | 2.42 |
| hold_180d_trail25_TP35 | 180 | 0.25 | 0.35 | 18,188 | 54.6 | +11.17 | 21.45 | 2.51 |
| hold_180d_trail25_TP30 | 180 | 0.25 | 0.30 | 18,188 | 57.3 | +10.28 | 21.04 | 2.40 |
| hold_252d_trail25_TP25 | 252 | 0.25 | 0.25 | 18,188 | 60.7 | +9.54 | 20.72 | 2.30 |
| hold_252d_trail22_TP35 | 252 | 0.22 | 0.35 | 18,188 | 51.2 | +10.44 | 20.35 | 2.44 |
| hold_180d_trail25_TP25 | 180 | 0.25 | 0.25 | 18,188 | 60.5 | +9.21 | 20.35 | 2.29 |
| hold_252d_trail22_TP30 | 252 | 0.22 | 0.30 | 18,188 | 52.2 | +9.58 | 19.90 | 2.33 |
| hold_252d_trail25_TP20 | 252 | 0.25 | 0.20 | 18,188 | **65.1** | +8.34 | 19.81 | 2.21 |
| hold_180d_trail22_TP35 | 180 | 0.22 | 0.35 | 18,188 | 51.5 | +9.94 | 19.70 | 2.39 |

### 관찰

- **모든 best 가 trail_pct=0.25, TP=0.30~0.35** 에 몰려있음. 기존 베이스 (trail 0.20 / TP 0.30) 보다 **더 넓은 추적폭** 이 유리.
- 기존 베이스 `hold_252d_trail20_TP30`: Sharpe 18.46 / mean +8.64% / win 53.0%
- **신규 베스트 `hold_252d_trail25_TP35`**: Sharpe 22.04 (+19%) / mean +11.75% (+36%) / win 54.0% (≈동일)
- `hold` 180 vs 252 는 거의 동급 — 252 가 미세하게 우위. 둘 다 사용 가능.
- `TP=0.20` 으로 짧게 끊으면 win% 가 65% 까지 올라가지만 mean 이 8.34% 로 떨어짐 — 안전 변형.

### 권장 변경 (KR trend_pullback 1d)

베스트: **`max_hold=252, trailing_pct=0.25, take_profit_pct=0.35`** (Sharpe 22.04, mean +11.75%, win 54.0%, PF 2.53).

---

## Cycle 2 권장 (cron 예정 — 18:42 fire)

**필수 추가**:
1. **US 청산 미세 그리드** (`us / trend_pullback / 1d`, th=70) — KR 과 같은 5×4×2 = 40 combos
2. **KR/US trend_chase 1d 청산 미세 그리드** — KR pullback 에서 trail_pct=0.25 가 우세했으니 chase 도 확인
3. 본 cycle 2 본 작업 (전략 내부 파라미터): trend_pullback 의 rally_lookback {30,45,60,80,100}, depth_lookback {15,25,35}

**관찰 노트**:
- KR pullback 의 OOS test (n=7,603) 가 train 보다 더 좋게 나왔으므로 **현 진입 시그널 자체는 견고**. 추가 게이트(cycle 3) 보다 청산 룰 미세화가 더 큰 효과.
- quiet_bottom KR 1w 의 train→test 저하 (Sharpe 6.68→4.07) 만 주시. cycle 3 에서 score 게이트 강화 (예: avg_dd_104w 임계 -0.50 등) 실험.

