# Strategies v2 — ma_touch 단일 룰 (운영 중)

> **상태**: 코드 본체 적용 완료 + 3 자산 (KR/Crypto/NASDAQ) `_ma_touch.parquet` 재생성 완료. 다운스트림(대시보드/alerts) 정리 미완.
> **사용자 신조**: **"시작 전 무조건 찍고 간다"** — MA 터치 자리만 잡음. 추격은 후순위.
> **최신 commit**: `06096c5` (origin/main).

## 0. 배경

기존 5 전략 (`trend_pullback`, `trend_chase`, `quiet_bottom`, `cascading_pullback`, `ma20w_short`) 모두 폐기.
→ **자리 1개 (`ma_touch`)** 로 통합. 자리 2 (`golden_cross`) 는 ma_touch 안정화 뒤 별도 단계.

폐기 이유:
- 전략당 8~17개 가산 항목으로 점수 의미가 흐려짐
- TF 가 일봉 한 차원 — 사용자가 원하는 주봉/월봉/분기봉/년봉 자리 검출 불가
- pullback 과 chase 의 핵심 룰(MA10·20 터치) 겹쳐 점수 분리 약함

## 1. ma_touch 룰 (운영 표준)

### 1-1. TF 선정 (자동 분기)

```
if 월봉 봉수 ≥ 10  (≈ 10개월+ 상장):
    평가 TF = [1W, 1M, 1Q, 1Y]    ← 1D 제외 (단기 노이즈 차단)
else:
    평가 TF = [1D, 1W, 1M, 1Q, 1Y]
```

**의미**: 큰 흐름 잡힌 안정 종목은 1D 단기 자리 패스. 신생주만 1D 도 본다.

### 1-2. 정배열 (B 정의)

```
정배열 = MA10 > MA20  AND  close > MA20
```

> **(A) 3선 정배열** (`close > MA10 > MA20`) 보다 풀림. close 가 MA10 아래로 잠시 빠지는 wick 자리 (예: STG 6/6 1W) 도 catch 하기 위함.

### 1-3. 상승 추세

```
slope_pct_MA10 > 0  AND  slope_pct_MA20 > 0
slope_pct = MA.pct_change(5)   (5봉 윈도우)
```

### 1-4. MA 터치 (롱 부등식)

```
임계        = 0.2 × range_7
range_7    = 최근 7봉 (high − low) 평균 (절대값, 그 TF 기준)
today_low  = 일봉 마지막 봉의 low  (모든 TF 평가에 공통 사용)

통과 조건  = (today_low − MA10 ≤ 임계)  OR  (today_low − MA20 ≤ 임계)
```

**핵심 특성**:
1. **롱 부등식** — low 가 MA 아래는 무한 OK (가로지름 인정). 위로는 임계 안만 OK.
2. **today_low 통일** — 1Q/1Y 평가에도 일봉 마지막 봉 low 사용. 큰 TF 봉의 "분기 안 어느 시점의 low" (옛 low) 가 아닌 **현재 시점 매수 자리**.
   - 효과: 추격 자리 자동 cut (예: 삼성전기 6/11 / 1Q MA10 = 34.7만 vs today_low 169.1만 → cut).

### 1-5. PARTIAL 시그널 (신생주, MA10 만 있는 TF)

```
① close > MA10
② slope_MA10 > 0
③ today_low − MA10 ≤ 임계
④ close > MA10 가 최근 3봉 연속 유지
```

## 2. 모듈 구조

```
scripts/_common/
├── mtf_loader.py          ← load_normalized_daily + resample_multi_tf (5 TF dict)
├── tf_selector.py         ← determine_eval_kind (full/partial/skip) + select_eval_tfs
├── mtf_indicators.py      ← compute_mtf_indicators (MA10/20, slope, angle, dist)
├── signals.py             ← signal_ma_touch_full / signal_ma_touch_partial / evaluate_tf
├── recommend_runner.py    ← _row_for_symbol + evaluate_universe + save_recommendations
├── crypto_filters.py      ← is_stock_token + filter_crypto_universe
├── build_recs_table.py    ← /recs 스킬 CLI
└── run_helper.py          ← study skill helper (옛)

scripts/{kr,crypto,nasdaq}/ma_touch/
├── PLAN.md                ← 자산별 비고
├── __init__.py
└── recommend.py           ← runner wrapper

.claude/skills/recs/
└── SKILL.md               ← /recs 트리거
```

## 3. 출력 스키마 (`_ma_touch.parquet`)

| 컬럼 | 의미 |
|---|---|
| `symbol`, `asset`, `close_price`, `evaluated_at_kst` | 기본 |
| `signal_ma_touch_{TF}_full` (bool/NaN) | TF 별 full 통과 |
| `signal_ma_touch_{TF}_partial` (bool/NaN) | TF 별 partial 통과 |
| `ma10_{TF}_price`, `ma20_{TF}_price` | TF MA |
| `dist_to_ma10_{TF}_pct`, `dist_to_ma20_{TF}_pct` | close 기준 거리 |
| `angle_ma10_{TF}_degree`, `angle_ma20_{TF}_degree` | arctan(slope/5) → degree |
| `angle_strength_label_{TF}` | weak/medium/strong (MA20 기준) |
| `signal_ma_touch_timeframes_passed` | "1W,1M" 같이 통과 TF 콤마 조인 |
| `count_signal_ma_touch_total` | 통과 TF 수 |
| `count_angle_positive_ma20` | MA20 각도 양수인 TF 수 (큰 흐름 정합도) |

TF = `1D, 1W, 1M, 1Q, 1Y` (5 종류).

## 4. /recs 스킬

`data/cache/{asset}/_ma_touch.parquet` → 사용자 표 형식:

```
종목명 | 코드 | 시총(조 or B$) | 거래량(만주 or 코인)
| 현재가 | vs일봉MA10(%) | vs일봉MA20(%) | vs주봉MA10(%) | vs주봉MA20(%) | vs월봉MA10(%) | vs월봉MA20(%)
| 통과TF | 큰흐름정합도
```

호출: `.venv/Scripts/python.exe -m scripts._common.build_recs_table --asset {kr|us|crypto|all} [--tf any|1D|1W|1M|1Q|1Y] [--kind full|partial|both] [--sort marcap|ticker|tf|count_signal] [--top N]`

## 5. 자산별 메타 처리

| 자산 | 종목명 source | 시총 | 거래량 | universe 필터 |
|---|---|---|---|---|
| KR | FDR `StockListing('KRX')` `Name` | `Marcap` (원) → 조 | 만 주 | — |
| US | FDR `StockListing('NASDAQ')` `Name` | (현재 NaN — 컬럼명 fix 필요) | 만 주 | — |
| Crypto | Bitget 심볼 | — (생략) | 코인 수 | **주식/ETF 토큰 자동 제외** (`crypto_filters.STOCK_TOKEN_TICKERS`) |

## 6. 검증 결과 — 현재 시점 (2026-06-11 KST 기준)

| 자산 | universe | 통과 (any TF) | 1D | 1W | 1M | 1Q | 1Y |
|---|---:|---:|---:|---:|---:|---:|---:|
| **KOSPI** | 948 | **323** | 0 | 81 | 214 | 51 | 0 |
| **NASDAQ** | 3729 | (재계산 완료) | 62 | 650 | 427 | 276 | 195 |
| **Crypto** | 578 → 147 (필터) | (재계산 완료) | (신생주) | 다수 | 다수 | 2 | 0 |

KR 시총 TOP 통과: 삼성전기는 today_low 룰로 cut 확인 (이전 옛 룰로는 잘못 통과했음). 현대차 / LG에너지솔루션 / HD현대중공업 / 삼성물산 / 기아 등 대형주 대다수 catch.

## 7. 시각 검증 케이스 (cross-check OK)

- **삼성화재 1D** ✅ (대형주 안정 자리)
- **메리츠금융지주 1Q** ✅ (5년 사이클 진입 — 1Q MA10 가까이)
- **이수페타시스 1M** ✅ (큰 흐름 정상 눌림)
- **삼성전기 1Q** ❌→cut (옛 룰 통과, today_low 룰로 정확히 cut)
- **ALLO 6/2~6/6** ✅ (KR 가도 같은 자리)
- **STG 6/6 1W** ✅ (사용자 지정 자리)
- **VELVET 6/10 1D** ✅ (wick MA10 닿음 — neg 부등식)

## 8. 상수 (signals.py 본체)

```python
K_DIST_THRESHOLD   = 0.2       # 임계 = K × range_7
N_ATR_WINDOW       = 7         # range_7 = 최근 7봉 평균
ANGLE_MEDIUM_DEG   = 15.0      # MA20 각도 라벨 임계
ANGLE_STRONG_DEG   = 30.0
PARTIAL_CONSEC_BARS= 3         # close > MA10 연속 봉 수
MA10_PERIOD        = 10
MA20_PERIOD        = 20
SLOPE_WINDOW       = 5
MIN_BARS_FULL      = 20        # MA20 가능 최소 봉수
MIN_BARS_PARTIAL   = 10        # MA10 가능 최소 봉수 (= "월봉 MA10 가능" 임계와 동일)
```

## 9. 다운스트림 (정리 미완 — 깨진 상태)

| 대상 | 상태 |
|---|---|
| `dashboards/_precompute.py` | **삭제됨** |
| `dashboards/_recommendation.py` | **삭제됨** |
| `dashboards/live/{bitget, kospi, nasdaq}.py` | import 깨짐 (옛 `_recs.parquet` 의존) |
| `dashboards/_stock_grid.py` | 옛 컬럼 가정 |
| `dashboards/pages/{3_Live, 6_Mobile}.py` | 옛 표 구조 |
| `alerts/{scan, state, __init__}.py` | `_recs.parquet` 의존 — 깨짐 |
| `data/cache/{kr,us,crypto}/_recs.parquet` | 삭제됨 |
| `data/cache/{kr,us,crypto}/_refs.parquet` | 삭제됨 |
| `data/cache/{kr,us,crypto}/_ma_touch.parquet` | **신규** (새 룰 결과) |
| `CLAUDE.md` "현재 전략 목록" 표 | 옛 정보 (5 전략) — 갱신 필요 |

## 10. Open Questions (다음 세션 결정)

### 핵심 결정
1. **추격 보조 게이트** — KR 1M 통과 14개 (close > MA20 × 1.5) 가 추격 가까움. `close ≤ MA20 × {1.5 / 1.3 / 1.2}` 추가?
   - 1.3x 적용 시 KR 통과 323 → ~290 정도
   - 1.2x 적용 시 ~250
2. **K 값** — 현재 0.2 휴리스틱. 백테스트 인프라 재구축 후 객관 결정?
3. **NASDAQ 시총 컬럼 NaN** — FDR `StockListing('NASDAQ')` 컬럼명 확인 + fix (10분 작업)
4. **NASDAQ 시총 컬럼 NaN** — FDR `StockListing('NASDAQ')` 컬럼명 확인 + fix (10분 작업)

### 후순위
5. **`golden_cross` 자리 본격 추가** — 첫 사용자 정의 자리 2 (하락추세→상승추세 전환). ALLO 5/27 같은 자리.
6. **추격 자리 (`trend_strong`)** — 사용자 명시 후순위. 별도 자리.
7. **대시보드 재구성** — 새 스키마 (`signal_ma_touch_{TF}_full/partial` + 40 컬럼) UI 노출
8. **alerts 재구성** — `_ma_touch.parquet` 기반 신규 진입 알림
9. **백테스트 인프라 재구축** — 옛 `backtest_runner` 폐기. 새 ma_touch 기반.
10. **partial 룰 검증** — 신생주 catch 동작 명시 검증 (현재 12 코인 시뮬에서 1~67 통과 확인됨)

## 11. 합의 이력 (요약)

| 결정 | 합의 시점 |
|---|---|
| 5 전략 폐기, ma_touch 1개 | 회의 초기 |
| 5 TF 평가, dominant 안 박음 | 회의 중 |
| 자산별 룰 동일 (임계값 모두 동일) | 회의 중 |
| 각도(degree) 출력 컬럼에 포함 | 회의 중 |
| 정배열 B (close > MA20, MA10 free) | STG 6/6 사례 후 변경 |
| 롱 부등식 (low ≤ MA + 임계) | VELVET 6/10 사례 후 변경 |
| 임계 = 0.2 × range_7 | ALLO 6/2 사례 후 변경 |
| today_low 모든 TF 공통 | 삼성전기 1Q 사례 후 변경 |
| 월봉 MA10 가능 시 1D 제외 | 사용자 명시 룰 |
| 주식/ETF 토큰 자동 제외 (Crypto) | crypto_filters 영구화 |

## 12. 사용자 메모리 (`MEMORY.md`) 연동

다음 세션 시작 시 자동 로드되는 메모:
- `project_ma_touch.md` — 현재 진행 상태 (TODO)
- `feedback_user_preferences.md` — 자산별 룰 분리 선호, 시각 검증 선호
- `feedback_kr_recommend_format.md` — KR 추천 분리 출력 (옛 표현, 갱신 필요)
- `feedback_column_naming.md` — 풀네임 컬럼
- `feedback_table_presentation.md` — 표 의미·의도·해석 필수
