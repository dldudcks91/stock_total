# Granville #1 검출 — 이평선 2차함수 적합

> 기존 골든크로스 대신 **이평선에 2차함수를 직접 적합**해 그랜빌 1법칙(MA 하락 종료 후 반등 시작)을 검출하는 방법을 탐색한 기록.
> 작업 기간 2026-06-15 ~ 2026-06-16. 모든 산출물은 `scripts/out/_probe_granville1_*.csv`/`.png`.

## 1. 왜 2차함수 적합인가

그랜빌 1법칙 정의 = "MA가 하락을 멈추고 평탄·반등하는 자리에서 가격이 MA를 상향 돌파". 즉 핵심은 **MA의 곡률**(2계 도함수가 양으로 전환).

- **골든크로스**: 두 MA 교차 — 1법칙과 직접 대응 X, 진입 시점도 늦음
- **2차함수 적합**: 1법칙 정의에 직접 부합. "하락 끝 + 평탄/반등 시작"을 한 번에 검증

## 2. 적합 방식

윈도우 안의 MA 시리즈에 `y = a·x² + b·x + c` 적합 (x = 0..N−1).

정규화 (TF/가격 무관 비교):

```
a_pct      = a / mean(MA) * 100        % per bar²  (곡률)
b_pct      = b / mean(MA) * 100        % per bar   (평균 기울기)
vertex_pos = (−b/2a) / (N−1)           윈도우 내 vertex 상대 위치
R²                                      적합 신뢰도
```

## 3. 네 가지 케이스 (KR 250종목 × 윈도우 슬라이딩)

| 케이스 | a_pct (median) | b_pct (median) | vertex_pos | R² |
|---|---|---|---|---|
| 상승추세 | −0.006 | +0.41 | (윈도우 밖) | 0.99 |
| 하방추세 | +0.006 | −0.39 | (윈도우 밖) | 0.99 |
| **1법칙 (하방→반등)** | **+0.056** | −1.00 | **+0.60** | 0.97 |
| **4법칙 (상방→반전)** | **−0.061** | +1.08 | **+0.61** | 0.97 |

핵심 관찰:
- `|a_pct|`가 추세(~0.006) vs 반등(~0.056) **10배 차이** → 곡률만으로 추세/전환 분리 가능
- vertex_pos가 결정적 — 반등군은 vertex가 윈도우 끝 ~60% 위치 (최근 5~6봉이 반등 구간)

산출: [scripts/out/_probe_ma_curvature_cases.csv](../scripts/out/_probe_ma_curvature_cases.csv), [_probe_ma_curvature_cases.png](../scripts/out/_probe_ma_curvature_cases.png)

## 4. 검출 룰 (5단계 + 가격 갭)

[scripts/out/probe_granville1_all_tf_today.py](../scripts/out/probe_granville1_all_tf_today.py)

1. **데이터 길이** ≥ `MA_LEN + N_WIN`
2. **R²** ≥ 0.85 (적합 신뢰)
3. **a_pct** ≥ 0.10 (곡률 충분 — U자)
4. **vertex_pos** ∈ [0.30, 0.85] (vertex가 윈도우 중간~중후반)
5. **MA[−1] > MA[−3]** (실측 MA가 위로 돌아섰는지)
6. **|px_vs_ma| ≤ 10%** (가격이 MA 근처)

## 5. 5개 TF/MA 조합 (N=10 통일, a_min=0.10 단일)

| 조합 | 의미 |
|---|---|
| 1d MA20 | 단기 (~3주 사이클) |
| 1w MA10 | 중기 (~2.5개월) |
| 1w MA20 | 중장기 (~3.5개월) |
| 1M MA10 | 장기 (~10개월) |
| 1M MA20 | 매우 장기 (~15개월) |

오늘 시점(2026-06-15) 후보 수 (gap≤10%):

| 자산 | Crypto | KR | US |
|---|---|---|---|
| 1d MA20 | 0 | 3 | 43 |
| 1w MA10 | 7 | 12 | 212 |
| 1w MA20 | 1 | 0 | 18 |
| 1M MA10 | 1 | 12 | 42 |
| 1M MA20 | 0 | 19 | 21 |
| **합계** | **9** | **46** | **336** |
| **멀티 TF (≥2조합)** | 0 | 1 | 11 |

> US가 36배 많음 = 나스닥 강세장. KR은 월봉에 집중 (철강 클러스터: 휴스틸/세아제강/고려제강/황금에스티). Crypto 빈약 (시장 약세).

## 6. False Positive 사례와 보강 룰

### 6.1 BILLUSDT — "감속 중 하락" (룰 5 추가 동기)

a=+0.250, vertex_pos=0.91, R²=0.989로 통과했지만 실제 MA20은 단조 하락. vertex가 윈도우 끝(0.91)에 있어서 곡선은 "감속 중 하락"인데 룰이 "반등 시작"으로 오인.

**해결**: `MA[−1] > MA[−3]` 실측 회복 조건 + `vertex_pos ≤ 0.85`로 제한.

### 6.2 JBIO — Ticker swap / Reverse merger (보강 필요)

a=+4.34로 극단 강곡률 통과. 차트 확인 결과:
- 2024-06-14 → 06-17: $861 → $58 (−93%, 거래량 70배 증가) = 명확한 ticker swap
- 2025-04-28 → 04-29: $93 → $10 (−89%) = 두 번째 ticker swap
- 한 티커에 3개 회사 데이터 누적 → MA10이 옛 큰 값을 "잊는 과정"의 인위적 곡선

**미적용 보강 후보**:
```python
# 윈도우 + MA 형성 구간 내 close 점프 감지
max_jump = recent_close.pct_change().abs().max()
if max_jump > 0.5: verdict = "ticker_jump"

# MA range 정규화 변동성 캡
if (ma.max() - ma.min()) / ma.mean() > 0.5: verdict = "ma_range_wide"
```

### 6.3 비대칭 U자 (미적용)

수학적으로 `a > 0`이라도:
- 케이스 A: 진짜 U자 `\___/`
- 케이스 B: 비대칭 U자 `\____/` (큰 하락 + 작은 반등)
- 케이스 C: 단조 감속 `\___`
- 케이스 D: 단조 가속 `‾\__`

JBIO는 케이스 B (좌단 rise +292% vs 우단 rise +46%, **6.3배 비대칭**).

**미적용 보강 후보**:
```python
left_rise  = ma[0]  / y_vertex - 1
right_rise = ma[-1] / y_vertex - 1
if right_rise < 0.05: verdict = "no_real_rise"
if max(left_rise, right_rise) / max(min(left_rise, right_rise), 1e-9) > 5:
    verdict = "asymmetric_u"
```

## 7. Funnel — 어디서 짤리나

총 평가 (자산×조합):

| 단계 | Crypto | KR | US |
|---|---|---|---|
| 전체 평가 | 1,877 | 4,581 | 17,025 |
| **low_a** (곡률 < 0.10) | **67%** | **75%** | **62%** |
| vertex_out | 22% | 13% | 21% |
| low_r2 | 8% | 9% | 10% |
| ma_not_rising | 1% | 1% | 1% |
| pass | 2.0% | 2.4% | 5.8% |
| pass + gap≤10% | 9 | 46 | 336 |
| **멀티 TF** | **0%** | **0.11%** | **0.29%** |

- `low_a`가 압도적 차단 사유 — 시장 대부분이 단순 추세 (1법칙은 본질적으로 드문 자리)
- 멀티 TF가 ~0.3% = 단일 TF 통과율(5~8%)의 제곱 → 거의 독립 이벤트 (정상)

## 8. 신규 상장 별도 분석

상장 < 250일(약 1년) 종목만 일봉 단독 평가 ([probe_granville1_newlisting.py](../scripts/out/probe_granville1_newlisting.py)):

| 자산 | 평가 | pass | gap≤25% |
|---|---|---|---|
| KR | 4 | 1 | 1 (케이뱅크) |
| US | 458 | 5 | 4 (DLXY 유일 깨끗) |
| Crypto | 137 | 0 | 0 |

본질적 한계:
- 1법칙 = "한 사이클 끝나고 반등" → 6~9개월 데이터 필요
- 신규 상장 평균 봉수 = 139일 → 사이클이 막 완성됐을 시점
- 통과율 1.1% (전체 종목 2.2%의 절반)

## 9. 현재 운영 상태

- **본체 적용 X** — 탐색 단계. `scripts/_common/signals.py`의 ma_touch 룰이 운영용
- **산출물 경로**: `scripts/out/_probe_granville1_*.csv` (자산별), `_probe_*_check.png` (개별 종목 검증)
- **종목명 매핑**: `data/cache/kr/_names.csv` + `_names_kosdaq.csv` (FDR `StockListing` 캐시)

## 10. 다음 단계 후보

1. 비대칭 U자 / ticker swap 필터 추가 (§6.2, §6.3)
2. 멀티 TF 통과 종목 fwd-return 백테스트 (20/60일)
3. 골든크로스 시점 vs 2차 적합 시점 alpha/lead-time 비교
4. 신규 상장 전용 룰 (사이클 짧은 자리)
5. 본체(`scripts/_common/signals.py`)에 정식 룰로 편입 여부 결정
