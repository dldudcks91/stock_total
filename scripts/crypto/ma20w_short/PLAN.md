# ma20w_short 연구 계획

> 위치: `scripts/ma20w_short/PLAN.md` (group 루트 · 모든 run 공유)
> 작성: 2026-05-18 KST · 마스터 플랜 (모든 후속 run 의 상위 계약)

## 0. 큰 질문

"**주봉 MA20 의 기울기가 음(-)일 때 숏을 친다**" 라는 큰 게이트 안에서,
**언제(몇 % 반등 후 / 어떤 형태일 때) 진입해야 가장 안전한가?**

> 게이트 정의 (확정 — 2026-05-18):
> - **slope_4w(t) = MA20w[t] / MA20w[t-4] − 1** (정규화 4주 차분, 단위: 비율)
> - 진입: `slope_4w(t) < 0` → t+1 주 시가 숏
> - 청산: `slope_4w(t) ≥ 0` → t+1 주 시가 청산
> - 자산은 숏 가능한 crypto (Bitget USDT-M) 한정

여기서 "안전" 의 조작적 정의 — 다음 모두를 함께 만족:

| # | 기준 | 임계 |
|---|---|---|
| ① | 평균 기대값 | > 0 (숏 수익률 양수) |
| ② | 승률 | ≥ 50% |
| ③ | Payoff (평균이익/평균손실) | ≥ 1.0 |
| ④ | **개별 트레이드 95% VaR / MaxLoss** | 작을수록 좋음 — **핵심 지표** |
| ⑤ | 표본 크기 | ≥ 50 trades, 안 되면 폐기 |

랭킹은 단일 메트릭이 아니라 **VaR-adjusted expectancy** = `mean - 1.65 × std` 로.
"평균은 좋은데 가끔 -50% 맞는 룰" 을 거르기 위해서.

## 1. 4-Layer Run 구조

### Layer 0 — `crypto_baseline` (이 폴더)
- 무필터 진입: `slope_4w(t) < 0` → 다음 주 시가 숏
- 청산: `slope_4w(t) ≥ 0` → 다음 주 시가
- **확인**: 분포 자체가 음수(=숏 우위)인가? 그룹별 차이 있나?
- **판정**: 음수가 안 나오면 가설 폐기. 양호하면 Layer 1.

### Layer 1 — `crypto_entry_grid`
청산은 단순 룰(`close >= MA20w`) 1개로 고정. 진입 조건 그리드.

**A. Rebound magnitude (몇 %)**
- `ret_Nw = close[t] / close[t-N] - 1`, N ∈ {1, 2, 3, 4}, 임계 ∈ {+3, +5, +8, +10, +15, +20, +30}%
- `dist_to_MA20 = close[t] / MA20w[t] - 1`, 임계 ∈ {-10, -5, -3, -1, 0}% — MA20 까지 얼마나 회귀했나

**B. Rebound shape (어떤 형태)**
- 단일 장대양봉: `1w_return ≥ X%` (8/15/20%)
- 연속 양봉: `consec_up_weeks ≥ {2, 3}`
- 거래량 폭증: `volume / vol_MA8 ≥ {2, 3, 5}`
- 주봉 RSI(14): ≥ {55, 60, 65, 70}
- Lower High: `rebound_high < prev_swing_high_8w`

**C. Regime depth (얼마나 깊은 약세)**
- `MA20w slope_4w < 0` 통과만
- `dist_from_MA20 ≥ -30%` 캡 (너무 깊으면 반등 폭 위험)
- `prior_drawdown_12w ≥ -X%` 게이트

→ A·B·C 단일조건 + 이항조합 그리드. 룰별 ①~⑤ 평가 후 VaR-adj. expectancy 랭킹.

### Layer 2 — `crypto_exit_grid`
Layer 1 의 top-K (5개) 룰에 청산만 그리드.
- 고정 보유: {2, 4, 6, 8, 12} 주
- `close >= MA20w` (Layer 1 의 베이스라인)
- Trailing stop: {-5, -10, -15}% (가격이 X% 오르면 컷 — 숏이므로 가격↑ = 손실)
- TP: {-10, -20, -30}% (가격이 그만큼 떨어지면 익절)
- SL: {+5, +10}% (가격이 그만큼 오르면 손절)
- 조합: `close>=MA20w + SL +10%` 등

### Layer 3 — `crypto_oos`
- Split: IS 2020–2023 / OOS 2024–2026
- Layer 1+2 top-K 룰 OOS 검증
- **통과 조건**: IS 대비 Sharpe ≥ 60% 유지

### Layer 4 — `crypto_stability`
- 4-group classification × top 룰 cross-tab
- per-symbol expectancy 분포 — 한두 심볼이 결과 좌우하면 폐기
- junk 에서만 동작하면 실전 위험 (슬리피지·청산 곤란) → 폐기

## 2. 데이터 / 표본 가드

| 항목 | 값 |
|---|---|
| 데이터 범위 | 2020-01 ~ 2026-05 |
| 자산 | crypto 만 (KR/US 숏은 제도적 제약) |
| 심볼 수 | 553 (Bitget USDT-M 전 종목) |
| 인터벌 | 1w (1d 캐시 리샘플) |
| 룩어헤드 | 시그널 t 종가 → 진입 t+1 시가 |
| 수수료/슬리피지 | 라운드트립 15bps (5+5+5) |
| Funding cost | 1주 -0.6% 가정 (추후 실측 funding 데이터로 보강) |
| 최소 표본 | 룰별 ≥ 50 trades |
| 생존편향 | 현재 살아있는 심볼만 — 1차 한계 인지, 폐지 심볼 보강은 별도 |

## 3. 폴더 매핑

```
scripts/ma20w_short/
├── _common.py       # MA20w / rebound / RSI / regime 헬퍼 (모든 run 공유)
├── baseline.py      # Layer 0
├── entry_grid.py    # Layer 1
├── exit_grid.py     # Layer 2
├── oos.py           # Layer 3
└── runs/
    ├── 20260518-2140_crypto_baseline/          ← 이 폴더 (Layer 0)
    ├── *_crypto_entry_grid/                    Layer 1
    ├── *_crypto_exit_grid/                     Layer 2
    ├── *_crypto_oos/                           Layer 3
    └── *_crypto_stability/                     Layer 4
```

## 4. 다음 즉시 액션

1. `scripts/ma20w_short/_common.py` — MA20w / 주봉 리샘플 / RSI / Lower-High 헬퍼
2. `scripts/ma20w_short/baseline.py` — Layer 0 분석 모듈 (config.json 받아 output/ 에 events·summary 저장)
3. 결과 보고 Layer 1 진입. 만약 baseline 의 평균 기대값이 0 이하 → 가설 폐기, 룰 자체를 재정의.

## 5. 폐기 조건 (가설을 버려야 할 때)

- Layer 0: 전체/그룹 모두 평균 기대값 ≤ 0 → MA20w 아래 단순 숏 가설 폐기
- Layer 1: 어떤 조합도 표본 ≥ 50 + VaR-adj. ex > 0 을 충족 못 함 → 진입 조건 축으로 안전성 분리 안 됨, 다른 게이트로 전환
- Layer 3: OOS Sharpe 가 IS 대비 < 30% → 과적합, 폐기
