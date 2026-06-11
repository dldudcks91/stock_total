# Strategies v2 — 단순화 설계 (확정)

> **상태**: 사용자 합의 완료. PLAN 골격대로 구현 진행.
> 사용자 신조: **"시작 전 무조건 찍고 간다"** — MA 터치 자리만 잡음. 추격은 후순위.

## 0. 배경

기존 5 전략 (`trend_pullback`, `trend_chase`, `quiet_bottom`, `cascading_pullback`, `ma20w_short`) 모두 폐기.
→ **자리 1개 (`ma_touch`)** 로 통합. 자리 2 (`golden_cross`) 는 ma_touch 안정화 뒤 별도 단계.

폐기 이유:
- 전략당 8~17개 가산 항목으로 점수 의미가 흐려짐
- TF 가 일봉 한 차원 — 사용자가 원하는 주봉/월봉/분기봉/년봉 자리 검출 불가
- pullback 과 chase 의 핵심 룰(MA10·20 터치) 겹쳐 점수 분리 약함

## 1. 자리 정의 — `ma_touch` ("정배열 + MA10/20 터치")

5 TF (1D / 1W / 1M / 1Q / 1Y) 각각에서 정배열 차트의 MA10 또는 MA20 터치.

**트레이더 원칙**: 어떤 종목이든 진입 전 MA10 또는 MA20 을 한 번 찍는다. 찍지 않고 가속하는 자리(추격)는 ma_touch 대상 X — 별도 자리(추후 `trend_strong`) 로 분리.

## 2. TF 평가 룰

**모든 TF 동시 평가** — 종목별로 가능한 모든 TF (1D~1Y) 에서 시그널 검사. dominant TF 안 박음. 사용자가 차트 보면서 자기 카테고리(BTC=1M, 삼성=1M, DOGE=1W 등) 직관 적용.

### TF별 평가 종류 자동 분기

| TF | MA20 가능 조건 → **full 평가** | MA10 만 가능 → **partial 평가** | 부가 의미 |
|---|---|---|---|
| **1D** | 일봉 ≥ 20봉 | (1D 는 partial 사실상 X) | 단기 자리 |
| **1W** | 주봉 ≥ 20봉 (~5개월 상장+) | 주봉 10~20 (~2~5개월 상장) | 중기 자리 |
| **1M** | 월봉 ≥ 20봉 (~20개월+) | 월봉 10~20 (~10~20개월) | 큰 흐름 자리 |
| **1Q** | 분기봉 ≥ 20봉 (5년+) | 분기봉 10~20 (2.5~5년) | **매우 강한 자리** |
| **1Y** | 년봉 ≥ 20봉 (20년+, 거의 없음) | 년봉 ≥ 10봉 (10년+) | **압도적 강한 자리** (큰 사이클 시작) |

> **의미**: 1Q / 1Y 의 MA 터치는 5~10년 사이클의 진입 자리 — 매우 강한 기회. 의도적으로 평가에 포함.

## 3. ma_touch FULL 시그널 (MA10 + MA20 둘 다 존재)

> **의미**: 정배열 추세 안에서 MA 터치 = 가장 보편적인 진입 자리.

게이트 (모두 만족):

| # | 조건 | 의미 |
|---|---|---|
| 1 | `close > ma10 > ma20` | 정배열 |
| 2 | `slope_pct_ma10 > 0` AND `slope_pct_ma20 > 0` | 두 선 모두 상승 중 |
| 3 | `\|dist_to_ma10\| < 3%` OR `\|dist_to_ma20\| < 3%` | 어느 한 선에 터치 |

→ 통과 시 `signal_ma_touch_{TF}_full = True`.

부가 (게이트 X, 출력 라벨만):
- `angle_strength_label_{TF}` — MA20 각도 기반
  - `weak` (<15°) / `medium` (15~30°) / `strong` (≥30°)

## 4. ma_touch PARTIAL 시그널 (MA10 만 존재)

> **의미**: 신생주가 큰 TF (월/주/분기/년) MA10 위에서 안 깨고 노는 = 큰 사이클의 **시작점**.

게이트 (모두 만족):

| # | 조건 | 의미 |
|---|---|---|
| 1 | `close > ma10` | MA10 위에 있음 |
| 2 | `slope_pct_ma10 > 0` | MA10 우상향 |
| 3 | `\|dist_to_ma10\| < 3%` | MA10 근접 (full 과 동일 임계) |
| 4 | `close > ma10` 최근 **3봉 연속** 유지 | 한 번 깼다 다시 올라온 케이스 제외 — 강한 흐름 확인 |

→ 통과 시 `signal_ma_touch_{TF}_partial = True`.

> **해석**: partial=True 종목은 MA20 만들지 못한 신생주 — 사용자가 차트 한 번 더 보고 "진짜 추세 시작인지 펌프&덤프인지" 판단. 자동 필터링은 partial 컬럼만 사용.

## 5. 출력 row 스키마

> **의미**: 한 종목 × 한 평가시점에서 모든 TF 의 시그널 + 정량 위치 + 각도 정보가 다 박힘. 사용자가 한눈에 어느 TF 가 잡혔는지 + 큰 흐름 (1M/1Q/1Y angle) 도 같이 확인.

### 기본 컬럼

| 컬럼 (풀네임) | 타입 | 의미 |
|---|---|---|
| `symbol` | str | 종목 코드 (KR 6자리, US 티커, Crypto Bitget 심볼) |
| `asset` | str | "kr" / "us" / "crypto" |
| `close_price` | float | 최신 종가 (원/USD/USDT) |
| `evaluated_at_kst` | str | 평가 시각 KST ISO |

### TF별 컬럼 (5 TF × 8 컬럼 = 40 컬럼)

각 TF ∈ {1D, 1W, 1M, 1Q, 1Y} 에 대해:

| 컬럼 | 타입 | 의미 |
|---|---|---|
| `signal_ma_touch_{TF}_full` | bool / NaN | MA20 가능 + full 룰 통과 |
| `signal_ma_touch_{TF}_partial` | bool / NaN | MA10 만 + partial 룰 통과 |
| `ma10_{TF}_price` | float / NaN | TF MA10 종가 기준 |
| `ma20_{TF}_price` | float / NaN | TF MA20 종가 기준 (1Y 는 NaN 빈도 높음) |
| `dist_to_ma10_{TF}_pct` | float | (close/ma10 − 1) × 100 |
| `dist_to_ma20_{TF}_pct` | float | (close/ma20 − 1) × 100 |
| `angle_ma10_{TF}_degree` | float | `degrees(arctan(slope_ma10 / 5))` — 5봉 윈도우 봉당 기울기 |
| `angle_ma20_{TF}_degree` | float | `degrees(arctan(slope_ma20 / 5))` |
| `angle_strength_label_{TF}` | str | MA20 각도 기반 — weak/medium/strong |

### 파생 라벨 (cross-TF 종합)

| 컬럼 | 타입 | 의미 |
|---|---|---|
| `signal_ma_touch_timeframes_passed` | str | 통과 TF 콤마 조인 (예: `"1W,1M,1Q"`) |
| `count_signal_ma_touch_total` | int | 통과한 TF 수 (full + partial) |
| `count_angle_positive_ma20` | int | MA20 각도 양수인 TF 수 (큰 흐름 정합도) |

## 6. 데이터 흐름

```
[자산별 raw load]              [자산 무관 normalize]
data.loader.load_ohlcv          normalize_columns
   (asset, symbol, "1d")    →   (소문자 close, volume, ...)  →   df_d_norm
                                                                    │
                       ┌────────────┬────────────┬────────────┬─────┴──────┐
                       ▼            ▼            ▼            ▼            ▼
                   resample("W") resample("M") resample("Q") resample("Y") (그대로)
                       │            │            │            │            │
                     df_w         df_m         df_q         df_y         df_d
                       │            │            │            │            │
                       └────────────┴────────────┴────────────┴────────────┘
                                              ▼
                            mtf_indicators.compute(df_each)
                            → MA10/20, slope_pct, angle_deg, dist_to_ma10/20
                                              ▼
                       per TF:  signal_ma_touch(df_tf)
                               → full / partial / None  (데이터 길이 자동 분기)
                                              ▼
                                     row dict 조립 (40+ 컬럼)
```

자산별 차이는 **load 단계** (대소문자 normalize) 에서만 흡수. 그 외 자산 무관 동일 코드.

## 7. 모듈 배치

### 공통 (자산 무관)

```
scripts/_common/
├── mtf_loader.py          # load_ohlcv + normalize + resample(W/M/Q/Y)
├── tf_selector.py         # 데이터 길이 분기 (TF별 full/partial/skip 결정)
├── mtf_indicators.py      # compute(df) → df + ma10/20 + slope_pct + angle_deg + dist
└── signals.py             # signal_ma_touch(df_tf, has_ma20) → (kind, bool)
```

기존 `scripts/_common/indicators.py` (대문자 가정 옛 모듈) 는 새 시스템에서 사용 X — 폐기 후보.

### 자산별 (3 폴더)

```
scripts/{kr,crypto,nasdaq}/ma_touch/
├── PLAN.md             # 자산별 universe 정의 / 비고
└── recommend.py        # 전체 universe 스캔 → 결과 list[dict]
```

자산별 `recommend.py` 는 wrapper:
- universe 로드 (KR: kospi 코드 / US: nasdaq 티커 / Crypto: USDT-M 심볼)
- 종목마다 `_common.mtf_loader.load_and_resample` + `signals.signal_ma_touch` 호출
- 결과 dict 리스트 → parquet 또는 stdout

자산별 차이는 universe 와 그 정도. 룰은 동일.

## 8. 자산별 임계값 (모두 동일)

| 파라미터 | 값 | 비고 |
|---|---|---|
| `DIST_TH_MA10` | 3% | full + partial 동일 |
| `DIST_TH_MA20` | 3% | full only |
| `ANGLE_MEDIUM_DEG` | 15 | medium 라벨 임계 |
| `ANGLE_STRONG_DEG` | 30 | strong 라벨 임계 |
| `PARTIAL_CONSEC_BARS` | 3 | close > ma10 연속 봉 수 |
| `MA10_PERIOD` | 10 | MA10 봉 수 |
| `MA20_PERIOD` | 20 | MA20 봉 수 |
| `SLOPE_WINDOW` | 5 | slope_pct 계산 윈도우 (봉 수) |

> **사용자 결정**: "자산별 룰 차이 없음 — 모두 동일". 백테스트/시각 검증 후 자산별 튜닝 필요 시 자산별 PLAN.md 에 override 박음.

## 9. 측정 계획 (D2 — on-demand 최종 결정)

> **목적**: 5 TF × 전체 universe 의 indicator 계산 시간 측정. 충분히 빠르면 on-demand. 느리면 `_refs.parquet` 확장.

스크립트: `scripts/_common/mtf_loader_bench.py` (임시).

측정 항목:
1. 전체 universe 1회 wall time (KR ~948 / NASDAQ ~수천 / Crypto ~400)
2. 항목별 breakdown — load / resample / indicator / signal
3. 기준선: 추천 1회 호출 latency **5초 이내** OK / **30초+** 면 precompute 필요

## 10. 다운스트림 정리 (별도 단계)

| 대상 | 작업 |
|---|---|
| `dashboards/_precompute.py` | 5 전략 import 삭제 → 새 `ma_touch` recommend 호출 |
| `dashboards/_recommendation.py` | 5 전략 import 제거 |
| `dashboards/pages/{4_KOSPI, 5_NASDAQ, 3_Bitget}.py` | 표 컬럼이 옛 5 전략 점수 — 새 스키마 (40+ 컬럼 중 핵심 노출) 로 교체 |
| `data/cache/{kr,us}/_recs.parquet` | 옛 스키마 stale — 새 전략 1회 돌려 재생성 |
| `data/cache/crypto/_recs.parquet` | 없음 — 새로 생성 |
| `CLAUDE.md` | "현재 전략 목록" / "현재 Skill 목록" 표 업데이트. backtest/strategies/ 표 폐기 |

## 11. golden_cross (자리 2) — 후순위

ma_touch 안정화 후 별도 단계로 추가. 본질: "하락 후 전환 + 첫 추세 자리" 잡기. ma_touch 의 정배열 게이트가 잘라내는 자리 보완.

룰 후보 (확정 X):
- 직전 N봉 안에 `ma10 × ma20` 상향 cross 발생
- 현재 `close > ma10` 유지
- `ma10_slope > 0` 전환 확인

## 12. 합의 / 미합의 / Open Question

### ✅ 합의 (사용자 확정)
- 5 전략 폐기, ma_touch 1개로 통합 (golden_cross 후순위)
- 5 TF (1D~1Y) 전부 평가, dominant 안 박음
- full + partial 시그널 둘 다 (신생주 catch)
- 1Q/1Y 평가 포함 = 매우 강한 자리
- 자산별 룰 동일 (임계값 모두 동일)
- dist 임계값 3%, slope 윈도우 5봉
- 신조: "시작 전 무조건 찍고 간다" — 추격은 후순위

### 🔜 다음 단계
1. **자산별 PLAN.md 3개** (kr/crypto/nasdaq × ma_touch)
2. **공통 모듈 4개** (`mtf_loader`, `tf_selector`, `mtf_indicators`, `signals`)
3. **자산별 `recommend.py` 3개**
4. **on-demand 측정** → precompute 여부 결정
5. **다운스트림 정리**
