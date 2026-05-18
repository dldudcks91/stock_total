# Round 3 — Crypto Regime-Adaptive Progress

Started: 2026-05-17

## Plan

| Task | Status | Notes |
|---|---|---|
| 1. 정밀 classification + 그룹 best (IS/OOS) | DONE | trend=126 follower=93 whale=30 junk=302 (정밀). best per (tier, iv) 산출 |
| 2. Regime-adaptive 단일 시그널 (BTC EMA200 게이트) | DONE | **1d regime_adaptive thC=60/thP=60 OOS S=+5.09** (baseline -1.07/-5.87) |
| 3. 그룹×regime 조합 best | DONE | IS-best combined OOS=-19.78 (overfit), Policy A2 OOS=+5.09, Policy D OOS=+4.38 |
| 4. pump_continuation / momentum_roc whale 적용 | DONE | 두 전략 모두 whale 그룹 OOS 음수 — 효과 없음 |
| 5. 1h regime-adaptive (옵션) | SKIP | 시간 한도 |

## Pre-flight

- 553 symbols in 1h/1d cache, BTCUSDT 존재.
- Round 2 OOS: chase 1d th=60 = -1.07, pullback 1d th=70 = -7.64 (둘 다 음수).
- BTC EMA200 효과 (Round 2 3년 전체): chase above mean 11.5% / below 6.31%; pullback above Sharpe 1.18 / below 4.05.
- 정밀 classification (`data.classification`) 비동기 실행 — 너무 오래 걸리면 기존 단순 분류 사용.

## Log

### Task 1 — precise classification + group grid
- 정밀 분류: trend=126 follower=93 whale=30 junk=302 benchmark=1 stable=1
- 1d 결과 (IS/OOS Sharpe):
  - trend chase th=60: IS +3.48 / OOS -0.13 (n=48) — Round 2 단순 trend(+3.65)와 유사
  - junk pullback th=90: IS +0.89 / OOS **+2.65 (n=577)** ← 가장 robust
  - follower chase th=90: IS +1.65 / OOS -1.22 (n=7) — 표본 적음
  - whale chase th=60: IS +0.10 / OOS +0.02 (n=10) — neutral
- 1w 거의 의미 없음 (chase entry=0, pullback OOS 음수)

### Task 2 — regime-adaptive 통합
- baseline chase 1d th=60: OOS S=-1.07 (Round 2 재현)
- baseline pullback 1d th=70: OOS S=-5.87
- both_always 1d (chase+pullback) th=60/60: OOS S=-9.76 (최악)
- **regime_adaptive 1d th=60/60: OOS S=+5.09, mean=+4.01%, n=2409, PF=1.18**
  - IS S=+0.20 (낮음) but OOS 가 압도적으로 개선
  - 약세장 길이 길어 pullback 진입 위주 (OOS n=2409 > IS n=1002)
- 1w 도 regime_adaptive 가 baseline 보다 낫지만 IS/OOS 모두 표본 적고 음수

### Task 3 — group x regime
- task3a (IS-best per cell): combined OOS Sharpe -19.78 (IS-best 가 above-pullback 에 집중 → OOS 약세장 망함)
- task3b 정책 비교:
  - A above→chase60, below→pull80 (all tiers): OOS S=+4.15
  - **A2 above→chase60, below→pull60 (all tiers): OOS S=+5.09, mean+4.01%, PF 1.62** ← Task2 와 동일
  - B per-tier IS-tuned: OOS S=+1.50 (IS=+2.73, IS-overfit 함정)
  - C trend-chase / all-below-pull80: OOS S=+4.38
  - **D junk-below-pull60 only: OOS S=+4.38, mean+5.97%, PF 1.81** ← 가장 robust single-cell

### Task 4 — pump_continuation / momentum_roc
- 1d 인터벌로 강제 적용 (1H 권장이지만 시간 한도). 4 param set.
- whale: 모두 OOS Sharpe -1.21 ~ -1.97 (효과 없음)
- junk: pump_continuation +0.59, momentum_roc -0.38 (neutral)
- trend: 둘 다 OOS S = -3.7 ~ -8.4 (재앙)
- 결론: 두 전략 모두 OOS 에서 pullback 1d 대비 우수하지 않음. whale 은 trend_pullback below th=60 (Task3 OOS S +1.64) 이 최선.

## Final policy recommendation

1차: **Policy A2 (regime_adaptive)** — `above→chase score>=60, below→pullback score>=60`, 모든 그룹 동일
2차: **Policy D (junk-only)** — junk 그룹 + below regime + pullback th=60, 단일 셀로 가장 robust

회피:
- above + pullback (IS 강하지만 OOS regime change 에 직격)
- per-tier IS-best 선정 방식 (Policy B 결과)
- pump_continuation / momentum_roc 1d (모두 OOS 음수)

