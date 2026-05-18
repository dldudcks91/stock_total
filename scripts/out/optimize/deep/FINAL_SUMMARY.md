# 진입 타이밍 최적화 — 최종 종합 (Cycle 5)

**작성**: 2026-05-17 21:44 KST
**작성자**: Cycle 5 종합 에이전트
**선행**: `SUMMARY.md` (base 21 combos / 325 rows) + `deep/cycle_1_summary.md` + `deep/grids/cycle2-4_*.csv`

---

## 핵심 3줄

1. **KR/US `trend_pullback` 1d 가 압도적** (Sharpe 18~22). 청산 미세화로 +19% Sharpe 추가 향상 (trail **0.25** / TP **0.30~0.35** 우세). KR best `hold_252d_trail25_TP35` Sharpe 22.04, US best 동일 룰 Sharpe 22.03.
2. **보조 게이트 효과**: 주봉 추세 필터 미미 (Sharpe 변화 ≤ 2.5pt), 거래대금 필터 강제는 표본 **95% 깎고** Sharpe **22 → 5 로 폭락** → **게이트 추가 비추**. 청산 미세화가 훨씬 효과적.
3. **Crypto 1h `trend_chase` Sharpe 0.54** — **알림 무가치 확정**. Crypto 4h 도 동일. Crypto 는 1d (chase th=60) / 1d·1w (pullback) 만 사용 권장.

---

## A. Top 권장 진입 룰 (자산 × 전략 × 인터벌)

| asset | strategy | interval | score_th | 청산 룰 (hold / trail / TP) | n | win% | mean% | Sharpe_ann | PF | 출처 |
|---|---|---|---|---|---|---|---|---|---|---|
| **KR** | **trend_pullback** | **1d** | 60 | **252d / 0.25 / 0.35** | 18,188 | 54.0 | +11.75 | **22.04** | 2.53 | cycle1 KR exit micro |
| **US** | **trend_pullback** | **1d** | 70 | **252d / 0.25 / 0.35** | 19,103 | 54.5 | +11.06 | **22.03** | 2.39 | cycle2 US pullback exit |
| KR | trend_chase | 1d | 60 | 252d / 0.25 / 0.30 | 4,013 | 53.2 | +7.99 | 8.03 | 1.98 | cycle2 KR chase exit |
| US | trend_chase | 1d | 60 | 252d / 0.25 / 0.35 | 2,204 | 52.2 | +8.04 | 5.94 | 2.05 | cycle2 US chase exit |
| KR | quiet_bottom | 1w | binary | 52w / 0.20 / 0.30 | 607 | 60.6 | +16.5 | 5.70 | 3.68 | base SUMMARY |
| US | quiet_bottom | 1w | binary | 52w / 0.20 / 0.30 | 404 | 56.2 | +14.9 | 4.01 | 3.10 | base SUMMARY |
| Crypto | trend_chase | 1d | 60 | 60d / 0.20 / 0.30 | 305 | 57.4 | +10.7 | 2.85 | 2.72 | base SUMMARY |
| Crypto | trend_pullback | 1d | 70 | 60d / 0.15 / cut_3d_neg | 11,230 | 31.2 | +2.2 | 2.81 | 1.28 | base SUMMARY |
| Crypto | trend_pullback | 1w | 60 | 8w / 0.15 | 658 | 44.4 | +10.5 | 2.01 | 1.86 | base SUMMARY |

**가장 큰 발견**: 기존 베이스 (trail 0.20 / TP 0.30) → 신규 (trail **0.25** / TP **0.35**) 전환만으로 **KR pullback Sharpe 18.40 → 22.04 (+19.8%)**, **US pullback Sharpe 19.76 → 22.03 (+11.5%)**. KR/US chase 도 모두 trail 0.25 가 top10 의 9~10개 차지.

---

## B. 알림 무가치 조합 (사용 금지 / dashboards 에서 제거 권장)

| asset | strategy | interval | 비고 | Sharpe / n |
|---|---|---|---|---|
| Crypto | trend_chase | **1h** | cycle4 probe (top30 by amount, th=70) — 단기 노이즈 우세 | 0.54 / 1762 |
| Crypto | trend_chase | 4h | base — th=60 에서 가장 좋지만 그래도 무용 | 0.62 / 11682 |
| Crypto | trend_pullback | 4h | base — 모든 threshold 에서 Sharpe 음수 | -0.31 / 14576 |
| Crypto | quiet_bottom | 4h | base — 자산 부적합 | -1.14 / 721 |
| Crypto | quiet_bottom | 1d | base — 자산 부적합 | 0.61 / 3534 |
| Crypto | quiet_bottom | 1w | base — 자산 부적합 (n 부족) | 0.27 / 68 |
| US | trend_chase | 1w | base — 표본 부족 | 0.62 / 45 |
| KR | quiet_bottom | 1d | base — 표본 부족 | 0.54 / 76 |

**결론**: Crypto 의 단기 봉 (1h, 4h) 과 모든 인터벌의 `quiet_bottom` 은 사용 금지. KR/US 의 `quiet_bottom` 은 1w 만, `trend_chase` 는 1d 만 유효.

---

## C. `alerts/scan.py` 수정 권장사항

### 현재 코드

```python
DEFAULT_SCORE_THRESHOLD = 80.0

def scan_new(asset, *, score_threshold=DEFAULT_SCORE_THRESHOLD, persist=True):
    ...
```

### 권장 변경 (자산별 dict)

cycle1 OOS test 결과 기준 — KR pullback test Sharpe 24.77, US pullback test Sharpe 21.46, Crypto chase Sharpe 2.85 모두 best 영역의 threshold 가 다름:

```python
DEFAULT_SCORE_THRESHOLD = 80.0  # 하위 호환 (인자 미지정 시 폴백)

# 자산별 권장 컷 (Cycle 5 결정, 2026-05-17)
# 근거: scripts/out/optimize/deep/FINAL_SUMMARY.md (best Sharpe @ threshold)
RECOMMENDED_THRESHOLD = {
    "kr":     60,   # trend_pullback 1d, OOS test Sharpe 24.77 (n=7603, win 54%)
    "us":     70,   # trend_pullback 1d, OOS test Sharpe 21.46 (n=6856, win 51.6%)
    "crypto": 60,   # trend_chase   1d,            Sharpe  2.85 (n=305,  win 57.4%)
}


def scan_new(asset, *, score_threshold=None, persist=True):
    if score_threshold is None:
        score_threshold = RECOMMENDED_THRESHOLD.get(asset, DEFAULT_SCORE_THRESHOLD)
    ...
```

호출 측 (`alerts/run.py` 또는 cron) 에서 자산별로 다른 threshold 를 자동 사용하게 됨. 명시적으로 인자를 주면 그대로 유지.

---

## D. `dashboards/_recommendation.py` 의 `_STRATEGY_SPECS_*` 수정 권장사항

(아래는 변경 의도. 실제 패치는 사용자 검토 후 수행 권장 — 현 코드 구조에 따라 dict/list 형태로 조정.)

**제거 권장 spec**:

```python
# crypto specs — 모두 제거 (1h, 4h, quiet_bottom 전 인터벌)
- ("trend_chase",    "1h")    # Sharpe 0.54 (cycle4 probe)
- ("trend_chase",    "4h")    # Sharpe 0.62
- ("trend_pullback", "4h")    # Sharpe -0.31
- ("quiet_bottom",   "1h")    # 자산 부적합
- ("quiet_bottom",   "4h")    # Sharpe -1.14
- ("quiet_bottom",   "1d")    # Sharpe 0.61
- ("quiet_bottom",   "1w")    # Sharpe 0.27 (n=68)

# us specs
- ("trend_chase",    "1w")    # n=45, Sharpe 0.62

# kr specs
- ("quiet_bottom",   "1d")    # n=76, Sharpe 0.54
```

**유지 권장 spec** (5 자산-전략-인터벌 + Crypto 2개):
- `kr/trend_pullback/{1d, 1w}`, `kr/trend_chase/{1d}`, `kr/trend_chase/1w` (선택 — n=81 적지만 Sharpe 2.42), `kr/quiet_bottom/1w`
- `us/trend_pullback/{1d, 1w}`, `us/trend_chase/1d`, `us/quiet_bottom/{1d, 1w}`
- `crypto/trend_chase/1d`, `crypto/trend_pullback/{1d, 1w}`

---

## E. MDD -100% 진단 결과 (cycle 1 요약 — 재확인)

- `scripts/optimize_grid.py:128-131` 의 MDD 컬럼은 **모든 trade 의 net_ret 을 체결 순으로 단순 누적곱한 single-series equity 의 drawdown**. 동시 보유 / 균등 비중 / 자본 분산 모델이 전혀 반영되지 않음.
- 한 trade 라도 -100% 근처에 닿으면 cumprod 가 0 으로 짜부러져 그 후 win trade 들이 회복 불가 → KR/US 1d 전반에 MDD=-100% 가 잡히는 원인.
- **신뢰 가능 메트릭**: `n`, `win%`, `mean%`, `Sharpe_ann`, `PF`. **무시할 메트릭**: `MDD%`, `total%`.
- 진짜 portfolio-level MDD/CAGR 은 별도 시뮬레이터 (cycle 5 권장 사항, 미구현) 필요.

---

## F. OOS 안정성 평가 (cycle 1)

train 2020-05-17 ~ 2024-05-16 (4년) vs test 2024-05-17 ~ 2026-05-17 (2년).

| asset | strategy | interval | train Sharpe | test Sharpe | test/train | 판정 |
|---|---|---|---|---|---|---|
| KR | trend_pullback | 1d | 14.75 | 24.77 | 1.68 | ✓ 견고 (test 개선) |
| US | trend_pullback | 1d | 18.27 | 21.46 | 1.17 | ✓ 견고 |
| KR | trend_chase | 1d | 5.00 | 12.44 | 2.49 | ✓ 견고 (test 우호적) |
| US | trend_chase | 1d | 5.42 | 6.15 | 1.13 | ✓ 견고 |
| KR | quiet_bottom | 1w | 6.68 | 4.07 | **0.61** | ⚠ 약과적합 (실용은 OK) |
| US | quiet_bottom | 1w | 3.60 | 5.12 | 1.42 | ✓ 견고 |

6/6 combos 모두 test 기간에서 실용 가능 (Sharpe ≥ 3, mean% ≥ +6%). **KR quiet_bottom 1w 만** 약과적합 신호 (단, mean +11.6% / PF 2.5 / win 51.7% 는 여전히 사용 가능).

---

## G. 보조 게이트 효과 (cycle 3)

대상: 각 자산의 best (`{asset}/trend_pullback/1d/th=60(KR)·70(US)/hold_252d_trail25_TP35`).
4 variant: `baseline` / `+weekly` (close > weekly SMA10) / `+amount` (amount > 20봉MA × 2.0) / `+weekly+amount`.

### KR pullback

| variant | n | mean% | Sharpe_ann | PF |
|---|---|---|---|---|
| baseline | 18,188 | +11.75 | **22.04** | 2.53 |
| +weekly | 14,716 | +12.02 | 20.00 | 2.57 |
| +amount | 1,622 | +10.46 | **5.95** | 2.25 |
| +weekly+amount | 1,391 | +10.75 | **5.66** | 2.29 |

### US pullback

| variant | n | mean% | Sharpe_ann | PF |
|---|---|---|---|---|
| baseline | 19,103 | +11.06 | **22.03** | 2.39 |
| +weekly | 17,691 | +11.22 | 21.57 | 2.43 |
| +amount | 968 | +11.37 | **5.10** | 2.45 |
| +weekly+amount | 891 | +11.28 | **4.86** | 2.44 |

**결론**:
- **주봉 추세 필터**: KR -2.0pt, US -0.5pt. 신호 수 18% 감소. **무효 (skip)**.
- **거래대금 필터 (amount > 20봉MA × 2.0)**: 표본 **91% (KR) / 95% (US) 감소**, Sharpe **22→5 로 폭락**. mean/win/PF 는 거의 유지지만 자유도 손실이 치명적. **사용 금지**.
- 현 진입 시그널 자체가 견고하므로 게이트 추가는 비추. 청산 미세화 (trail 0.25, TP 0.30~0.35) 가 훨씬 효과적.

---

## H. Crypto 1h 활용 가능성 (cycle 4)

| asset | strategy | interval | rule | n | win% | mean% | Sharpe_ann | PF |
|---|---|---|---|---|---|---|---|---|
| Crypto | trend_chase | **1h** | hold_240bars / trail 0.15 / cut_24h_neg, th=70, top30 by amount | 1,762 | 31.7 | +0.62 | **0.54** | 1.12 |

- Crypto 4h (`trend_chase` Sharpe 0.62, `trend_pullback` Sharpe -0.31) 와 일관 — 모두 단기 노이즈 우세, 진입 알림 무가치.
- **결론**: Crypto 알림은 **1d** (chase th=60, pullback th=70) **만** 사용. 1h/4h 알림 spec 은 dashboards 에서 제거.

---

## I. 향후 작업 (cycle 5 한계 + 권장)

1. **Portfolio MDD 시뮬레이터** (`scripts/optimize/portfolio_simulator.py`) — entry_dt 정렬 → 시점별 균등 비중 (또는 max N 동시 보유) → daily equity → portfolio MDD/CAGR/Sharpe 재계산. 현재 single-series cumprod MDD 는 알림 가치 평가에는 무의미하지만, 자본 운용 의사결정에는 필요.
2. **전략 내부 파라미터 그리드** — cycle2 본작업으로 계획했던 `trend_pullback` 의 `rally_lookback`, `depth_lookback`, `react_volume_ma` 및 `trend_chase` 의 `ret_th`, `vol_mul`, `amount_lookback` 그리드는 cycle 2 압축으로 인해 미실행. 청산 미세화가 +19% Sharpe 를 가져왔으므로 우선순위는 낮지만, 추가 향상 여지 가능.
3. **KR `quiet_bottom` 1w 약과적합 보강** — train→test Sharpe 0.61 비율. binary trigger 강화 (예: `avg_dd_104w` 임계 -0.50, `path_R²_52w` 임계 ≤ 0.40) 또는 score 게이트 추가 실험.
4. **Crypto 1h `trend_pullback`** — cycle4 에서 1h chase 만 probe. pullback 도 1h 에서 알림 가치 확인 권장 (대량 데이터로 인해 별도 budget 필요).
5. **자산별 임계 dynamic tuning** — 현재는 6년 통합 best 의 단일 threshold. 시기별 (1y / 6mo) rolling re-optimize 로 regime change 대응 가능.

---

## J. 실행 시간 / 자원 / 데이터 범위

- **데이터 범위**: 2020-05-17 ~ 2026-05-17 (6년), KR/US top300 (시총), Crypto top300 (amount proxy) + cycle4 top30 by amount-sum.
- **총 combos**: base 325 + cycle1 (12 + 40) + cycle2 (40 + 40 + 40) + cycle3 (4 + 4) + cycle4 (1) = **506 combos**.
- **실작업 시간**: cycle 1 재가동 ~21분, cycle 2 압축 실행 ~25분, cycle 3~4 백그라운드 동시 진행. cycle 5 종합 ~5분.
- **수수료/슬리피지 가정**: KR 0.3% 왕복, US/Crypto 0.2% 왕복.
- **신뢰 가능 메트릭**: n / win% / mean% / Sharpe_ann / PF.

---

## 사용자 액션 체크리스트 (도착 시 1분 안에 결정)

1. [ ] `alerts/scan.py` 의 `DEFAULT_SCORE_THRESHOLD = 80.0` 를 자산별 dict 로 변경 (C 섹션 코드 그대로 복사 사용 가능).
2. [ ] `dashboards/_recommendation.py` 의 `_STRATEGY_SPECS_*` 에서 D 섹션의 "제거 권장 spec" 8개 삭제 (Crypto 1h/4h/quiet 6개 + US chase 1w + KR quiet 1d).
3. [ ] `backtest/strategies/trend_pullback.py` 의 기본 청산 룰을 `trail 0.20 / TP 0.30` → **`trail 0.25 / TP 0.35`** 로 변경 검토 (KR/US 모두 best).
4. [ ] 거래대금 필터 추가 요청 들어오면 거절 또는 매우 큰 임계 (예: amount > 5봉MA × 1.2) 로 약하게만. cycle 3 결과 인용.
5. [ ] (선택) cycle5 권장 작업 중 portfolio MDD 시뮬레이터를 다음 cycle 우선순위로.
