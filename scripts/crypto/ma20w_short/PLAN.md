# ma20w_short 연구 계획

> 위치: `scripts/crypto/ma20w_short/PLAN.md`
> 작성: 2026-05-28 KST · 마스터 플랜
> 이전 계획 (slope<0 무필터 baseline) 폐기 — 진입 룰을 "MA20w 터치" 로 구체화

## 0. 큰 질문

"**다운트렌드 코인이 주봉 MA20 까지 반등했다가 거기서 막혀 다시 떨어진다**" 라는
가설이 통계적으로 사실인가? 그리고 **어디서 들어가서 어디서 나와야 가장 안전한가?**

진입은 단일 룰로 고정하고, **exit 조합을 그리드로 풀어** 최적 청산을 찾는 게 1차 목표.

### 게이트 (확정)
- `close_1w(t) < MA20w(t)` — 현재 주봉이 MA20 아래
- `slope_4w(t) = MA20w[t] / MA20w[t-4] − 1 < 0` — 4주 정규화 기울기 음수

### 진입 (확정)
- 게이트 만족 상태에서 **일봉 high ≥ MA20w(직전 완성 주봉 기준)** 인 첫 일봉에 진입
- 진입가 = **MA20w 지정가** (intraday touch 시 그 가격으로 체결)
- 같은 종목 포지션은 1개, 청산 후 **4주 쿨다운**
- 룩어헤드 방지: MA20w 값은 **진입 일봉 시점의 직전 완성 주봉** 의 MA20w 를 사용 (진행 중 주봉의 MA20w 갱신값 사용 금지)

## 1. Run 구조 (Layer)

- **Layer 0 — `baseline`**: 진입 룰 + 단일 청산 (`close_1d ≥ MA20w`) sanity check. 그룹별 평균 expectancy 부호 확인. 음수면 가설 폐기.
- **Layer 1 — `exit_grid`** (메인): Layer 0 진입 룰 고정 + **640 exit 조합 풀 스윕**. 그룹 × 640 매트릭스.
- **Layer 2 — `oos`**: Layer 1 top-K (그룹별 5개) IS/OOS 분할 검증. Split: IS 2021–2023 / OOS 2024–2026.
- **Layer 3 — `stability`**: per-symbol expectancy 분포 + 연도별 성능. 소수 심볼 의존성 / 특정 시기 의존성 점검.

## 2. 파라미터 스윕 매트릭스 (필수)

| Layer | param | sweep values | default | 의미 |
|---|---|---|---|---|
| L1 | `stop_pct` | [0.00, 0.03, 0.05, None] | None | MA20w 위 X% 일봉 종가 회복 시 손절 (가격이 MA20w·(1+x) 이상이면 컷). None = 손절 없음 |
| L1 | `tp_pct` | [−0.15, −0.25, −0.40, None] | None | 진입가 대비 X 도달 시 익절. None = 익절 없음 |
| L1 | `trail` | [0, 0.15, 0.20, 0.25] | 0 | 최저가(=최대수익) 대비 X 반등 시 청산. 0 = trail 없음 |
| L1 | `hold_weeks` | [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] | 4 | 최대 보유 (1d 단위 환산: 1w=7d). 도달 시 강제 청산 |
| L0 | (exit 고정) | `close_1d ≥ MA20w` | — | baseline 은 단일 청산 룰 — sanity check 용 (스윕 X) |

- L1 전 조합 = 4×4×4×10 = **640** 조합. 그룹 4개 = 2560 백테스트.
- 단일 조합 (stop=None, tp=None, trail=0, hold=10w) = hold-only 청산.
- 결과 테이블 (wide): `output/sweep_<param>.csv` — 행=sweep value, 열=핵심 메트릭 (n / mean / win_rate / payoff / var_adj_ex / mdd / sharpe). 다축이므로 다른 param 은 default 고정한 marginal table.
- 전체 long format: `output/sweep_grid.csv` — 640 행 × (group × 메트릭).

## 3. 평가 지표

| # | 지표 | 의미 |
|---|---|---|
| ① | mean expectancy | 평균 트레이드 수익률 (> 0 필요) |
| ② | 승률 | ≥ 45% 권장 |
| ③ | payoff (평균이익/평균손실) | ≥ 1.0 |
| ④ | **VaR-adjusted ex** = mean − 1.65×std | **랭킹 메트릭** — squeeze 위험 페널티 |
| ⑤ | trade 수 | ≥ 50 (그룹별), 미만은 폐기 |
| ⑥ | MDD (equity 기준) | 참고 |
| ⑦ | Sharpe (연환산) | 참고 |

## 4. 그룹별 평가

`data/cache/crypto/classification.parquet` 의 4그룹 (trend / follower / whale / junk) 을
**동일 파라미터로 각각 백테스트**. 메인 결과 테이블은 `group × exit_combo` 매트릭스.

> trend 에서만 동작 → 실전 가치 高
> junk 에서만 → 슬리피지/청산 곤란으로 폐기 검토

## 5. 데이터 / 표본 가드

| 항목 | 값 |
|---|---|
| 데이터 범위 | 2021-01-01 ~ 2026-05-28 |
| 자산 | crypto (Bitget USDT-M) |
| 인터벌 | 시그널 1w (MA20w 게이트), 진입/청산 1d |
| Universe | 4그룹 분리, classification.parquet 기준 |
| 룩어헤드 방지 | 진입 일봉 시점의 **직전 완성 주봉** MA20w fix |
| 수수료 | 진입 5bps + 청산 5bps = 10bps |
| 슬리피지 | 5bps (지정가지만 보수적) |
| Funding cost | **제외** (스킵, 추후 옵션화 가능) |
| 최소 표본 | 그룹별·룰별 ≥ 50 trades |
| 생존편향 | 현재 상장 심볼만 (한계 인지) |

## 6. 폴더 매핑

```
scripts/crypto/ma20w_short/
├── PLAN.md                                # 이 파일
├── _common.py                             # MA20w 주봉 리샘플, 게이트, touch 감지, 그룹 universe
├── baseline.py                            # Layer 0
├── exit_grid.py                           # Layer 1 (메인)
├── oos.py                                 # Layer 2
├── stability.py                           # Layer 3
└── runs/
    ├── {ts}_baseline/
    ├── {ts}_exit_grid/
    ├── {ts}_oos/
    └── {ts}_stability/
```

## 7. 폐기 조건

- Layer 0: **모든 그룹** 평균 expectancy ≤ 0 → 가설 폐기
- Layer 1: **어떤 그룹도** trades≥50 + var_adj_ex>0 룰 0개 → 룰 자체 무력, 게이트 재설계
- Layer 2: OOS var_adj_ex 가 IS 대비 < 30% → 과적합, 폐기
- Layer 3: 상위 3 심볼이 PnL 의 80% 이상 차지 → 일반화 실패, 폐기

## 8. 다음 즉시 액션

1. `_common.py` 작성 — 주봉 MA20 계산, slope_4w, 직전 완성 주봉 fix, intraday touch 감지, 4그룹 universe 로드
2. `baseline.py` 작성 — Layer 0 단일청산 (`close_1d ≥ MA20w`) 백테스트
3. `/study init crypto/ma20w_short baseline` → 첫 run 폴더
4. baseline 결과 검토 → 그룹별 expectancy 부호 확인 → Layer 1 진입 or 가설 폐기
