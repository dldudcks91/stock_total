# 조용한 바닥 (quiet_bottom)

> 자동매매가 아닌 **추천 시그널** 전략. 사용자가 매일/매주 후보 종목을 확인하기 위한 룰.

## 1. 사용자 직관

차트에서 본 직감:
- 종목이 한참 흘러내려 **푹 잠긴** 후
- 중간중간 'MA20에 박치기 → 다시 추락' 같은 **가짜 출발이 없이**
- 조용히 횡보·바닥 다지기를 거치고
- **처음으로 부드럽게 올라오는** 패턴

ATOM 2024-11-25 같은 'V-spike 후 슬로프 양 전환' 케이스, CHZ 같은 '박스권 안 박치기 7회' 케이스는 **제외**하고 싶음.

## 2. 진입 조건 — 6개 (1차 구현)

| # | 조건 | 코드 |
|---|---|---|
| 1 | 가격이 20선 위 | `close > MA20` |
| 2 | 두 이평선 기울기 양 | `slope10 > 0 AND slope20 > 0` |
| 3 | 두 이평선 가속도 양 | `accel10 > 0 AND accel20 > 0` |
| 4 | 2년간 깊이 잠겼었음 | `avg_dd_104w ≤ -0.45` |
| 5 | 직선 하락 아님 | `path_R²_52w ≤ 0.50` (log(close) 선형 fit) |
| 6 | V-spike 없음 | `close[t] / close[t-4] - 1 ≤ +0.60` |

## 3. 미구현 — slope 시계열 R² 보강 지표 (다음 단계)

**path_R²(가격 직선 여부) 단독 한계 발견**: CHZ 같은 박스권 안 박치기 7회 종목도 R² 낮아서 통과함. 사용자가 차트로 본 박치기 패턴은 가격 R²로는 잡을 수 없음.

**slope20 시계열 자체에 선형 fit** 으로 보강 (검증 완료, 구현 대기):

```
slope20 = β·t + α   (직전 12주)

조건:
  (1) min(slope20[t-11:t+1]) < 0       12주 안에 음수였음
  (2) slope20[t] > 0                   현재 양 전환 완료
  (3) β > 0                            평균적으로 증가 추세
  (4) R² ≥ 0.70                       매끄러운 증가 (점프 없음)
```

### 검증 결과 (현재 시점 후보 9종 + ATOM 비교)

| 종목 | β_norm | **slope R²** | min | 평가 |
|---|---:|---:|---:|---|
| PENGU | +113.7 | **0.96** | -1151 | 매우 매끄러움 |
| HYPE | +39.9 | 0.92 | -147 | 매끄러움 |
| SUN | +22.4 | 0.92 | -267 | 매끄러움 |
| TRX | +15.0 | 0.88 | -68 | 매우 매끄러움 |
| STG | +32.1 | 0.78 | -37 | 양호 |
| MORPHO | +41.7 | 0.71 | -158 | 양호 |
| BANANAS31 | +26.8 | **0.28** | +95 | ❌ 들락날락 |
| **CHZ** | +11.6 | **0.48** | -22 | ❌ **박치기 패턴 정확히 잡힘** |

→ **slope R² 임계 ≥ 0.70 으로 CHZ/BANANAS31 자동 거름.** 사용자 의도 1:1.

### 추가 후보 — 박치기 횟수 직접 카운트

`cross_up_78w` = 직전 78주 안에 close가 MA20 아래에서 위로 올라온 시점 수 (현재 진입 cross-up 제외).

임계: `≤ 2` (보수) / `≤ 3` (관대). 검증 결과 CHZ 7회, BANANAS31도 거름.

## 4. 백테스트 결과 요약 — 자산별 청산 룰

> 자동매매가 아닌 추천이지만, 시그널의 통계적 가치 검증 위해 simulator로 백테스트 (6년, top300, 수수료 차감).

| 자산 | 청산 룰 | n | win% | mean% | Sharpe | PF | OOS Sharpe |
|---|---|---:|---:|---:|---:|---:|---:|
| **KR** | hold_52w + trail 0.20 + TP 0.30 | 584 | **61.8** | +17.1 | **+5.84** | 3.92 | **+4.29** ★ |
| **US** | hold_52w + trail 0.20 + TP 0.30 | 303 | 56.4 | +15.7 | +3.56 | 3.20 | **+4.88** ★ |
| **Crypto** | hold_13w + trail 0.15 + cut_1w_neg | 31 | 35.5 | +13.9 | +0.69 | 3.08 | — |

### 검증 (Walk-forward + Outlier + 종목 분할)

| 항목 | KR | US |
|---|---|---|
| Train (2020-23) Sharpe | 7.11 | 2.10 |
| **Test (2024-26) Sharpe** | **4.29** | **4.88** |
| Top 5% outlier 제거 후 Sharpe | 5.13 | 3.02 |
| 종목 분할 (홀짝) Sharpe | 4.26 / 4.00 | 2.93 / 2.19 |

- **KR**: in-sample 부풀림 있음, OOS Sharpe 4.29 — 여전히 강함
- **US**: OOS가 Train보다 더 좋음, 매우 robust
- **Crypto**: 본 조건과 안 맞음 (직선 하락 패턴이라 path_R² 통과 안 됨)
  - 일봉으로도 시도 → 모두 망함

## 5. 추천 자산

| 자산 | 추천 여부 | 이유 |
|---|---|---|
| **KR (KOSPI top 300)** | ✅ 권장 | Sharpe 4~6, win% 60%+, n 충분 |
| **US (NASDAQ top 200)** | ✅ 권장 | OOS robust, Sharpe 4 후반 |
| **Crypto** | ❌ 본 룰로는 부적합 | 별도 룰 필요 (모멘텀/돌파 등) |

## 6. 현재 시점 시그널 출력 — 어떻게 쓰나

```python
import pandas as pd
from backtest.strategies import quiet_bottom
from data.loader import load_ohlcv

df_w = load_ohlcv("kr", "005930", "1w")     # 자산/심볼/1w
sig = quiet_bottom.signal(df_w.reset_index(drop=True), {})
sig.index = df_w.index

# 현재 신호 ON ?
print(sig.iloc[-1])           # 1 = 매수 후보, 0 = 비대상

# 이번 주 신규 진입?
new_entry = (sig.diff() == 1).iloc[-1]
```

## 7. 대시보드 분류 — 향후 구현 예정

```
🟢 진입 시그널 (NEW)     이번 봉에 sig 0 → 1 전환
🟡 진입 임박            6 조건 중 4~5 만족 (slope 또는 path_R² 임박)
🔵 보유 적합            진입 후 청산 조건 미충족
🔴 청산 임박            peak 트레일링 임계 근접
```

Streamlit 페이지로 띄우면 매주 자동 업데이트되는 추천 리스트가 됨.

## 8. 관련 파일

| 파일 | 용도 |
|---|---|
| [backtest/strategies/quiet_bottom.py](quiet_bottom.py) | 전략 본체 (signal 함수) |
| [scripts/quiet_bottom/exit_rule_grid.py](../../scripts/quiet_bottom/exit_rule_grid.py) | 청산룰 그리드 (simulator) |
| [scripts/quiet_bottom/validate_quiet_bottom.py](../../scripts/quiet_bottom/validate_quiet_bottom.py) | KR/US 검증 (시기별/Outlier/종목분할/IS-OOS) |
| [scripts/quiet_bottom/plot_signal_check.py](../../scripts/quiet_bottom/plot_signal_check.py) | 종목별 차트 + 박치기 카운트 |
| [scripts/quiet_bottom/plot_r2_intuition.py](../../scripts/quiet_bottom/plot_r2_intuition.py) | R² 의미 시각화 |
| scripts/out/quiet_bottom_signals_crypto.csv | 크립토 현 시점 시그널 리스트 |

## 9. 다음 작업 (재시작 시 컨텍스트)

- [ ] slope 시계열 R² (β + R² + min + current 묶음) 을 `quiet_bottom.signal` 에 추가 옵션화
- [ ] 박치기 카운트 (`cross_up_78w`) 추가
- [ ] KR/US 전체 백테스트에 새 지표 통합 → Sharpe 재측정
- [ ] 대시보드 페이지 (`dashboards/pages/quiet_bottom.py`) — 매주 자동 시그널 리스트
- [ ] Crypto 별도 룰 — 직선 하락 패턴이 정상이므로 정반대 조건 (예: 모멘텀 돌파)
