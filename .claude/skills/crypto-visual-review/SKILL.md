---
name: crypto-visual-review
description: Bitget 코인 차트(1W/1D, KR/US 종목은 1M 추가)를 MA10/20/50 오버레이로 렌더링하고, Claude 가 직접 PNG 를 시각 판독해 사이클 단계(A1~A5 / B1~B5 / C1)·micro_action·volume_flag 로 채점·기록하는 스킬. 백테스트 룰만으로 못 거르는 시각 패턴(분배 의심, 펌프&덤프 흔적, 좀비 의심, TF 충돌)을 잡아내기 위함. 모드: 단일(single) / 신호 트리거(signals) / 전수 베이스라인(refresh). 사용자가 "차트 보고 판정", "시각 검증", "visual review", "사이클 단계", "코인 훑어줘" 라고 할 때 발동.
---

# /crypto-visual-review — Bitget 코인 시각 검증 스킬

백테스트 룰만으론 못 거르는 케이스(펌프&덤프, 분배 의심, 좀비, TF 충돌)를 **Claude 가 차트를 PNG 로 직접 보고** 사이클·단계로 채점한다. 결과는 표준 위치에 누적되어 시계열 비교 가능.

## 1. 목적

- 백테스트 신호의 보완: 같은 종목·시그널이라도 차트 모양·MA 행동·거래량 분배 패턴은 룰로 표현하기 어렵다. 사람(또는 Claude)이 PNG 한 장 봐야 잡힌다.
- **자동매매 X — 추천 시그널 전용**. 시각 검증은 buy zone 후보 좁히기와 진입 회피용.
- 사이클 라벨(A/B) + 단계(1~5) 로 모든 종목을 동일 프레임으로 비교 가능하게.

## 2. 트리거 / 모드

```
/crypto-visual-review single BTCUSDT
/crypto-visual-review signals
/crypto-visual-review refresh
```

| 모드 | 대상 | 시점 |
|---|---|---|
| `single` | 인자 1종목 | 즉시 1회 |
| `signals` | 오늘 신호 발화 종목 (5~20) | 매일/매주 |
| `refresh` | 전체 universe (~400) | 1회 베이스라인 + 월 1회 갱신 |

## 3. 운영 사이클 (3 phase)

| Phase | 빈도 | 모수 | 소요 | 산출 |
|---|---|---|---|---|
| **0. 베이스라인** | 1회 (시작) | 전체 ~400 | 3~5h (분할) | `coin_state.parquet` 초기화 |
| **1. 신호 트리거** | 매일/매주 | 5~20 | 10~30m | 신호 종목만, `reviews/` 추가 |
| **2. 정기 갱신** | 월 1회 | 전체 | 3~5h | 전체 상태 업데이트 |

## 4. 저장 구조

```
data/cache/crypto/visual_review/
├── coin_state.parquet           # 종목별 최신 상태 (한 줄 / symbol)
├── reviews/
│   └── {SYMBOL}/
│       └── {YYYYMMDD}.json      # 시점별 판정 (history)
├── charts/
│   └── {SYMBOL}/
│       └── {YYYYMMDD}/
│           ├── {SYMBOL}_1w.png  # 주봉 차트
│           └── {SYMBOL}_1d.png  # 일봉 차트 (history 짧으면 1d 메인)
└── signals.parquet              # 백테스트 신호 + 시각판정 결합
```

## 5. 차트 렌더링 규격

### 5.1 자산별 default TF 세트

| 자산 | history 길이 | TF 세트 | 비고 |
|---|---|---|---|
| **Crypto** | 일반 | **1W + 1D** | 사이클 짧음, 24/7 |
| Crypto | < 6개월 | 1D 만 | 1W 봉 수 부족 |
| KR / US | 일반 | 1M + 1W + 1D | 사이클 김, 향후 확장 |

### 5.2 각 차트 공통 사양
- **봉 수**: 200 봉 고정 (history 부족하면 가용 전체)
- **MA**: MA10 (gold) / MA20 (red) / MA50 (blue), thin (width 0.8)
- **거래량 서브플롯**: 포함
- **이미지**: 1280×720, dpi 110
- **렌더 도구**: `mplfinance` (style=`charles`, type=`candle`)
- **종목당 렌더 시간**: ~0.4초 (warmup 후)

### 5.3 MA 의미 (각 TF 별)
- MA10 = 단기 추세선 (모멘텀)
- MA20 = 중기 추세선 (메인 지지/저항)
- MA50 = 장기 추세선 (큰 그림 지지/저항)

### 5.4 헬퍼 스크립트
초기 prototype 은 `.claude/skills/crypto-visual-review/_tmp/render_test.py` 에 있음. 정식 운영 시 `research/visual_review/render.py` 로 이전 권장.

## 6. 채점 스키마 (핵심)

### 6.1 `state` (필수, 11개 enum)

**사이클 A — 상승 추세 (큰 그림이 위로)**

| 값 | 시각 정의 |
|---|---|
| `A1` | 상승 출발. 변곡 직후 안정 상승 자리잡음. MA 정배열 진행, 가격이 MA20 위 안정. |
| `A2` | 지속적 상승. MA10/20/50 완전 정배열 + 모두 우상향. 풀백마다 MA10/MA20 지지. |
| `A3` | 상승 멈추고 횡보 (topping). 신고가 못 가고 박스, MA들 평탄해짐. |
| `A4` | 하락 시도. MA20 아래 첫 음봉, 단 확정 안 됨 (다시 회복 가능). |
| `A5` | 하락 retest 확정. 풀백이 MA20 에 막힘 + MA20 음 기울기 — 사이클 A 끝. |

**사이클 B — 하락 추세 (큰 그림이 아래로)**

| 값 | 시각 정의 |
|---|---|
| `B1` | 하락 시작. 피크 깬 첫 음봉 + 거래량 동반. |
| `B2` | 지속적 하락. MA 역배열 + 모두 우하향. **좀비 코인도 여기 포함** (양봉 나오면 B4 로 전이). |
| `B3` | 하락 멈추고 횡보 (base / 바닥 다지기). MA들 평탄·수렴, 가격 박스. |
| `B4` | 상승 시도. MA20 위 첫 양봉 + 거래량 동반, 단 확정 안 됨. |
| `B5` | 상승 retest 확정. 풀백이 MA20 에 받음 + MA20 양 기울기 — 사이클 B 끝. |

**C — 분류 불가**

| 값 | 시각 정의 |
|---|---|
| `C1` | 박스 (3년+ 방향 없는 횡보) / 펌프&덤프 / 비정상 패턴 / 신규 코인 1D 도 박스 |

**판정 우선순위**:
1. 큰 추세 방향 보고 A or B 결정
2. 안정 단계(1, 2) vs 변환 단계(3, 4, 5) 판단
3. 둘 다 명확 X 면 C1

### 6.2 `micro_action` (선택, 6개 enum)

안정 단계(A1/A2/B2/B3) 안에서 현재 단기 행동.

| 값 | 의미 |
|---|---|
| `riding` | MA 위/아래 안정적, 풀백 없이 진행 |
| `pullback_ma10` | MA10 닿고 반등 시도 (얕은 풀백) |
| `pullback_ma20` | MA20 닿고 지지/저항 테스트 |
| `pullback_ma50` | MA50 까지 깊은 풀백 |
| `breaking` | MA50 도 깨고 추세 끝나는 중 |
| `acceleration` | 가격 가속 (페러볼릭 상승, 거래량 폭증) |

**언제 채움**: 안정 단계일 때만 의미 있음. 변환 단계(A3/A4/A5/B4/B5) 에는 `null`.

### 6.3 `volume_flag` (선택, 4개 enum)

| 값 | 의미 |
|---|---|
| `normal` | 거래량 정상, 추세에 부합 |
| `distribution_suspect` | 가격 횡보인데 거래량 매도 우세 (분배 의심) |
| `dry` | 거래대금 미미, 관심 빠짐 (좀비 의심) |
| `pump_dump_trace` | 1봉 폭등 후 거래량 소멸 흔적 |

**언제 채움**: 시각적으로 특이 패턴 보이면. 정상이면 `null` 또는 `normal`.

### 6.4 `tf_consistency` (1종목 종합)

TF 별 state 가 같은 방향 가리키는지.

| 값 | 의미 |
|---|---|
| `정합` | 모든 TF 가 같은 사이클 (A 계열 or B 계열) + 비슷한 단계 |
| `충돌` | 큰 TF 와 작은 TF 의 사이클이 다름 (예: 1W=B, 1D=A) |
| `분리` | 같은 사이클이지만 한 TF stable, 다른 TF 변환 중 |

### 6.5 `verdict` (최종 매매 판정)

| 값 | 의미 |
|---|---|
| `pass` | 매매 적합 (buy zone) |
| `watch` | 관망 (변곡 대기 / 단계 확인 필요) |
| `skip` | 매매 회피 |
| `reject` | 영구 제외 (좀비 + dry 거래량 / 펌프&덤프) |

**기본 결정 룰** (예비안, 추후 정밀화):
- 큰 TF state ∈ {A1, A2, B5} + tf_consistency=정합 → `pass`
- 큰 TF state = B4 → `watch`
- 큰 TF state ∈ {B2, B3} → `skip` (B3 는 watch 가능)
- 큰 TF state ∈ {A3, A4, A5} → `skip` (피크 후 위험)
- volume_flag ∈ {`dry`, `pump_dump_trace`} → `reject`
- TF 충돌 → 한 단계 보수적 판정

### 6.6 매매 함의 한 줄 요약

| state | 매매 |
|---|---|
| A1, A2 | 보유 / 풀백 매수 |
| A3 | 비중 축소 검토 |
| A4 | exit 검토 |
| A5 | exit |
| B1, B2 | skip |
| B3 | watch (돌파 대기) |
| B4 | 작게 진입 / watch |
| **B5** | **buy zone** ⭐ |
| C1 | skip (또는 free note 따라) |

## 7. 데이터 스키마 (저장)

### 7.1 `coin_state.parquet`

종목별 최신 상태 한 줄/symbol.

| 컬럼 | 타입 | 의미 |
|---|---|---|
| `symbol` | str | `BTCUSDT` |
| `last_review_date` | date | 마지막 판정일 (KST) |
| `state_1w` | str | 11 enum 중 하나 |
| `state_1d` | str | 11 enum 중 하나 |
| `micro_action_1w` | str | null 가능 |
| `micro_action_1d` | str | null 가능 |
| `volume_flag_1w` | str | null 가능 |
| `volume_flag_1d` | str | null 가능 |
| `tf_consistency` | str | `정합` / `충돌` / `분리` |
| `verdict` | str | `pass` / `watch` / `skip` / `reject` |
| `note` | str | 자유 메모 |
| `chart_path_1w` | str | charts 상대경로 |
| `chart_path_1d` | str | charts 상대경로 |

### 7.2 `reviews/{SYMBOL}/{YYYYMMDD}.json`

시점별 스냅샷 (history 보존).

```json
{
  "symbol": "BTCUSDT",
  "reviewed_at": "<KST ISO>",
  "data_until": "<마지막 캔들 timestamp KST>",
  "tf_1w": {
    "state": "A3",
    "micro_action": null,
    "volume_flag": "distribution_suspect",
    "note": ""
  },
  "tf_1d": {
    "state": "B5",
    "micro_action": null,
    "volume_flag": "normal",
    "note": ""
  },
  "tf_consistency": "충돌",
  "verdict": "watch",
  "verdict_reason": "1W 토핑 / 1D 변곡 시도, 큰 TF 보수적",
  "charts": {
    "1w": "charts/BTCUSDT/20260519/BTCUSDT_1w.png",
    "1d": "charts/BTCUSDT/20260519/BTCUSDT_1d.png"
  },
  "schema_version": 1
}
```

### 7.3 `signals.parquet`

백테스트 신호 ⊕ 시각 판정 결합.

| 컬럼 | 의미 |
|---|---|
| `symbol` | |
| `signal_date` | 백테스트 신호 발화일 |
| `strategy` | `trend_pullback` / `trend_chase` / ... |
| `visual_verdict` | 시각 판정 결과 (`pass` / `watch` / `skip` / `reject` / `pending`) |
| `visual_reviewed_at` | 시각 판정 시각 (없으면 null) |
| `combined_action` | 백테스트 ∩ 시각 둘 다 통과 시 `take`, 아니면 `drop` |

## 8. 워크플로우

### 8.1 대상 종목 결정

- **`single`**: 인자 1종목
- **`signals`**: 오늘자 신호 종목 — 백테스트 산출 파일 (TBD: 위치 정해야 함) 에서 로드
- **`refresh`**: 전체 universe → 사전 필터 적용 후 남은 종목

### 8.2 차트 렌더링

각 종목당 1W + 1D 두 장 PNG 생성. crypto 기본 200봉.

```python
# 예시 호출 (헬퍼는 _tmp/render_test.py 참조)
render("crypto", "BTCUSDT", ["1w", "1d"], prefix="btc")
# → data/cache/crypto/visual_review/charts/BTCUSDT/{YYYYMMDD}/BTCUSDT_1w.png + _1d.png
```

### 8.3 Claude 가 PNG 읽고 채점

각 종목마다, 각 TF 별로:

1. Read 로 PNG 읽기 (이미지 보기)
2. **state** 결정 (11 enum 중 하나) — 큰 추세 → 단계
3. 안정 단계면 **micro_action** 추가
4. 특이 거래량이면 **volume_flag**
5. 다른 TF 도 동일하게 채점
6. **tf_consistency** 판단 (정합 / 충돌 / 분리)
7. **verdict** 도출 (룰 + 자유 보정)
8. **note** 한 줄

### 8.4 결과 기록

1. `reviews/{SYMBOL}/{YYYYMMDD}.json` Write
2. `coin_state.parquet` 의 해당 row 갱신 (없으면 추가)
3. `signals` 모드라면 `signals.parquet` 의 `visual_verdict` + `combined_action` 갱신

### 8.5 대화창 요약

본 종목들 표로 정리 — symbol · state_1w · state_1d · verdict · note 요약.
`pass` 종목 강조 + 다음 액션 제안.

## 9. 사전 자동 필터 (refresh 모드)

전수 모드에서 모수 압축용 자동 컷 — 임계값은 캘리브 후 확정 (TBD):

- 거래대금 컷: 최근 30일 평균 거래대금 < $X → 제외
- 신규 / history 부족: 6개월 미만 history → C1 자동 분류
- 더 정밀한 사전 필터는 추후 보강

## 10. 컨텍스트 윈도우 관리

- PNG 한 장이 토큰 꽤 차지 → **한 세션 20~30 종목** 권장
- `refresh` 모드는 batch 단위로 분할 실행, 각 batch 종료 시 `coin_state.parquet` 저장
- 다음 세션 이어갈 땐 `last_review_date` 오래된 종목부터

## 11. 동작 원칙

- **시각 판정 우선**: 코드 룰로 자동 채점 X. Claude 가 PNG 직접 보고 enum 선택.
- **사용자 합의된 스키마 외 임의 추가 금지**: 11 state / 6 micro_action / 4 volume_flag 외 새 값 만들지 않음. 필요 시 user 와 합의 후 본 SKILL.md 수정.
- **PNG 보존 필수**: 사후 검증용. 자동 삭제 X.
- **시계열 history 유지**: `reviews/{SYMBOL}/` 옛 JSON 덮어쓰기 X. 날짜별 추가.
- **백테스트와 결합**: `signals.parquet` 의 `combined_action == take` 만 진짜 매매 후보.
- **자동매매 X**: 추천 시그널 전용.
- **KST 시각 표준**: 모든 timestamp KST.

## 12. 헬퍼 스크립트 위치

### 현재 (prototype)
```
.claude/skills/crypto-visual-review/_tmp/
├── render_test.py      # 차트 렌더 (mplfinance + MA10/20/50)
└── scan_cycle_b.py     # 사이클 단계 후보 자동 스캔
```

### 정식 운영 시 이전 권장
```
research/visual_review/
├── __init__.py
├── render.py           # PNG 렌더 (dashboards.charts 또는 mplfinance)
├── filter.py           # 사전 자동 필터
├── store.py            # coin_state / reviews / signals I/O
└── universe.py         # 모드별 대상 종목 결정
```

## 13. 향후 확장 / TODO

### 다음 작업 (우선순위 순)

1. **헬퍼 스크립트 정리** — `_tmp/render_test.py`·`run_single.py` 를 `research/visual_review/render.py` 로 이전 + 정식 입력 인자화
2. **`store.py` 작성** — `coin_state.parquet` / `reviews/{SYMBOL}/{YYYYMMDD}.json` I/O 헬퍼 분리 (현재 ad-hoc bash inline 으로 처리 중)
3. **실제 채점 첫 시도** — 4~5종목 골라서 스킬대로 단일 모드 실행하면서 enum 일관성·시각 판단 캘리브
4. **TF 세트 정책 확정** — 메이저 코인 (5년+ history) 은 1M+1W+1D, 일반 알트는 1W+1D, 신규 (<6개월) 는 1D 만. 임계값 (24/26봉) 은 잠정. BTC 1M 도 추가 채점 필요 (현재 1W+1D 만 있음)

### 추후 확장

- KR / US 로 확장 시 `kr-visual-review`, `us-visual-review` 별도 스킬 (또는 `--asset` 인자)
- KR/US 는 1M + 1W + 1D 3장 세트 (사이클 김)
- micro_action / volume_flag 값 추가 검토:
  - 수직 펌프 (acceleration) 를 별도 state 로 분리할지
  - 거래량 의심 4값을 세분할지
- 시각 판정 history 분석 — 시간 따라 state 가 어떻게 변천했는지 보면서 룰 재학습
- 시각 판정 ↔ 백테스트 결과 cross-check 리포트 (시각 pass 인데 백테스트 실패한 케이스 패턴 분석)
- 자동 사전 필터 모듈 분리
- TF 별 사이클 라벨 충돌 해소 (1W=A5 + 1D=B5 같은 경우 framework 재정의 필요)

## 14. 캘리브된 표본 (현재까지 검증 완료)

각 enum 의 시각 정의가 명확한지 확인한 종목·TF.

| state | 확정된 표본 |
|---|---|
| A1 | NC 1M (3.5년 다운 후 2025-06 변곡, 11개월 안정 상승) |
| A2 | NC 1W, TRX 1W |
| A3 | (BTC 1W 후반부 부근, 명확 표본 더 찾기) |
| A4 | (transient, 표본 적음) |
| A5 | (BCH 1W ~ 사이) |
| B1 | (transient) |
| B2 | SOL 1W, MOVE 1W, SUI 1W |
| B3 | POLYX 1W |
| B4 | ONDO 1W (방금 돌파) |
| B5 | POLYX 1D, ONDO 1D (retest 진행) |
| C1 | (아직 명확 표본 없음) |
