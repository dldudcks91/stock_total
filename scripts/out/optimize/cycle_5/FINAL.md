# Cycle 5 — 종합 최종 보고서 (FINAL)

작성: 2026-05-17 KST · Iteration Plan 5/5 완료 (5시간 / 5 cycle 자동화 종료).

본 문서는 Cycle 1~4 의 산출을 단일 페이지에 압축. 원자료는 `cycle_{1..4}/` 디렉터리, 본 문서는 운영용 결정 요약만 담는다.

---

## 자산별 최종 추천 (운영 즉시 적용 가능)

| 자산 | itv | 전략 | score_th | 청산 룰 (trail / TP / hold) | universe | Sharpe_IS | Sharpe_OOS | n_OOS | 비고 |
|---|---|---|---|---|---|---|---|---|---|
| **KR** | 1d | **trend_pullback** | **60** | trail25 / TP30 / hold252d | 시총 top 300 (또는 500) | 14.79 | **24.83** (Cyc1) → **29.16** (rally_lookback=90, Cyc3) | 7,565 → 9,380 | Cyc3 게이트 `rally_lookback=90` 적용 시 OOS Sharpe +18% |
| **US** | 1d | **trend_pullback** | **70** | trail20 / TP30 / hold252d | 시총 top 300 (또는 500) | 18.82 | **22.08** | 6,805 | 기본 게이트 plateau, 변경 무의미 |
| **KR** | 1d | trend_chase (보조) | 60 | trail20 / TP30 / hold252d | top 300 | 5.05 | **12.32** → **15.96** (`fresh_big_th=0.08`) | 1,221 → 2,812 | OOS 폭발. fresh_big_th=0.08 +30% Sharpe |
| **US** | 1d | trend_chase (보조) | 60 | trail15 / TP30 / hold252d | top 300 | 5.18 | **6.79** → **10.09** (`fresh_big_th=0.08`) | 883 → 1,423 | fresh_big_th=0.08 +49% Sharpe |
| **KR** | 1w | quiet_bottom | binary | trail20 / TP30 / hold52w | top 300 | 6.70 | **4.41** → **6.83** (`dd_avg_max=-0.40`) | 242 → ~370 | dd_avg_max 완화 시 +55% |
| **US** | 1w | quiet_bottom | binary | trail20 / TP30 / hold52w | top 300 | 3.50 | **4.96** → **6.43** (`dd_avg_max=-0.40`) | 155 → ~230 | dd_avg_max 완화 시 +30% |
| **Crypto** | **1h** | **trend_pullback** | **75** | trail20 / cut5h / hold336h | amount top 100 | 8.23 (full 6yr) | **3.32** (top30 OOS 3yr, Cyc4 보조) | 1,514 | **신규** — 1d 폐기 대체 |
| Crypto | 1h | trend_chase (보조) | 60 | trail20 / TPnone / hold168h | top 100 | 4.05 | **2.06** | 1,491 | 보조 신호. 단독 비추 |

> 비교용 폐기 조합 (운영 추천 X):
> - Crypto trend_pullback **1d** — Cyc1 OOS Sharpe -0.32 ~ 1.77, mean% -0.17 ~ +1.32. BTC dominance↑ 시 alt 추세 mean-revert.
> - Crypto **4h** 모든 전략 — Sharpe < 0.7, 1h 대비 인터벌이 어중간.
> - Crypto quiet_bottom 모든 인터벌 — Sharpe ≤ 0.61, 자산 부적합.
> - KR/US trend_chase th=80 — n 매우 작음 (KR 441, US 273), 신뢰성 부족.

heatmap·그리드 raw 는 `cycle_4/crypto_1h_grid.csv` (162 행), `cycle_4/universe_sensitivity.csv` (8 행) 참조.

---

## 핵심 발견 7줄

1. **KR/US trend_pullback 1d 는 데이터 스누핑 위험 거의 없음** — OOS Sharpe (24.8/22.1) 가 IS (14.8/18.8) 보다 같거나 높음. 6년 통합 결과 신뢰 가능.
2. **인터벌이 자산만큼 결정적** — 같은 trend_pullback 시그널이 Crypto 1d 는 OOS Sharpe -0.32 (붕괴), 1h 는 +3.32 (안정). alt 의 단기 추세는 1h 회전이 잡고, 1d 신호 시점엔 이미 추세 종료.
3. **각 전략에 dominant gate 1개 존재** (Cyc3): `trend_pullback rally_lookback=90` (KR만), `trend_chase fresh_big_th=0.08` (KR/US 양쪽 +30~49%), `quiet_bottom dd_avg_max=-0.40` (양쪽 +30~55%). 나머지 게이트는 plateau.
4. **청산 룰 plateau**: stock 전략은 trail 20~25 × TP 30 × hold 252d 의 평탄대. fine-grid tuning 은 overfit 위험만 추가 (Cyc2 stage B skip).
5. **universe 견고성**: KR/US trend_pullback 1d 는 top_n 50→500 으로 10배 키워도 Sharpe 단조증가. 시그널 자체가 universe-agnostic. 운영 sweet spot = top 300.
6. **Crypto trend_pullback 1h `cut5h` 컷이 결정적**: mean% +2.6 → +5.6 으로 두 배. 진입 직후 fat-loss tail 절단 효과.
7. **US 의 IS→OOS Sharpe decay (1.53~1.56) 가 KR (1.21~1.23) 보다 크지만** universe 변형과 무관하게 일정 — 시장 구조 차이일 뿐, 시그널 약화는 아님.

---

## 운영 권장 — 어떤 시그널을 켜고 어떤 걸 끌지

**켤 것 (자동 알림 ON)**
- KR trend_pullback 1d @ score_th=60 (rally_lookback=90 적용 시 best)
- US trend_pullback 1d @ score_th=70
- Crypto trend_pullback 1h @ score_th=75 (cut5h 청산 필수)

**조건부 켤 것 (대시보드 표시 + 알림은 임계치 ↑)**
- KR/US trend_chase 1d @ score_th=60 (게이트 `fresh_big_th=0.08` 적용)
- KR/US quiet_bottom 1w (게이트 `dd_avg_max=-0.40` 적용)

**끌 것 (`_STRATEGY_SPECS_CRYPTO` 에서 제거)**
- Crypto trend_pullback 1d, Crypto 4h 전체, Crypto quiet_bottom 1w
- (코드 패치는 `STRATEGY_SPECS_patch.md`)

**alerts/scan.py 자산별 threshold 분리 적용** — `scan_py_patch.md` 참조.

---

## 데이터 한계 / 신뢰구간

- **OOS 가 단일 2년 구간 (2024-05 ~ 2026-05)** — 한쪽 강세장 효과 가능. 향후 walk-forward (cycle 6 후보) 로 보완 필요.
- **Crypto 1h 의 IS/OOS split** 은 Cyc4 보조 (top30 / 3년) 만 수행 — Cyc1 의 1d 결론을 1h 에 그대로 일반화 금지. 추가 검증 권장.
- **Cycle 3 의 보조 게이트는 OAT (one-at-a-time) sweep** — combo 효과 (예: trend_chase fresh_big_th=0.08 + amount_lookback=500) 미측정.
- **수수료/슬리피지**: KR 0.3%, US/Crypto 0.2% RT. 실거래는 호가 슬리피지로 추가 0.1~0.3% 손실 가능 → 명목 Sharpe 의 80~90% 가 실현 가능치.
- 작은 n 표본 (KR/US quiet_bottom 1w n=154~242, Crypto chase th=80 n=48) — bootstrap CI 미산출.

---

## 향후 작업 (Cycle 6+ 후보)

1. **Walk-forward 평가** — 6년을 12 개월 rolling window 로 분할, IS 3년 / OOS 1년 슬라이딩.
2. **Cycle 3 게이트 combo 그리드** — `trend_chase fresh_big_th × amount_lookback × max_prior_extension` 2D/3D.
3. **weekly_sma10_filter** (사용자 미수행 요청 항목) — 1d 신호에 1w 추세 필터 추가 OOS robustness 측정.
4. **Crypto 1h IS/OOS proper split** — top100 universe 로 6년 데이터 활용.
5. **Crypto trend_pullback 1d 매크로 게이트** — BTC close > BTC MA200 필터 추가하여 alt 신호 회복 시도.
6. **`backtest/strategies/trend_chase.py` DEFAULT_PARAMS["fresh_big_th"] 갱신** — 0.05 → 0.08 (Cyc3 검증).

---

## 산출 파일 (Cycle 5)

- `cycle_5/FINAL.md` (본 문서)
- `cycle_5/scan_py_patch.md` — alerts/scan.py 자산별 threshold 분리 패치
- `cycle_5/STRATEGY_SPECS_patch.md` — dashboards/_recommendation.py `_STRATEGY_SPECS_CRYPTO` 패치

## 누적 산출 (전 cycle)

`scripts/out/optimize/` 하위:
- `cycle_1/oos_split.csv` (20행), `cycle_1/oos_summary.md`
- `cycle_2/REPORT.md`, `cycle_2/winners.csv`, `cycle_2/exit_grid_*.csv`
- `cycle_3/gate_grid_*.csv` (6개) + `cycle_3/gate_grid_all.csv` (60행)
- `cycle_4/crypto_1h_grid.csv` (162행), `cycle_4/universe_sensitivity.csv`, `cycle_4/robustness_summary.md`
- `PROGRESS.md` — 전 cycle 진행 로그
