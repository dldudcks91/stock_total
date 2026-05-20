---
name: crypto-visual-review
description: 크립토·KR·US 차트(1M/1W/1D)를 MA10/20/50 오버레이로 렌더링하고, Claude 가 직접 PNG 를 시각 판독해 사이클 단계(A1~A5/B1~B5/C1)·micro_action(9 enum, bounce 포함)·volume_flag(5 enum, accumulation 포함)·risk_flags 로 채점·기록하는 스킬. schema v2.1. facts.json 으로 객관 사실 자동 추출 + Claude 시각 판정 결합. 매집/분배/펌프&덤프/좀비/TF 충돌 시각 패턴 모두 잡음. 모드: 단일(single)/신호(signals)/전수(refresh). 사용자가 "차트 보고 판정", "시각 검증", "visual review", "사이클 단계", "매집봉", "코인 훑어줘" 라고 할 때 발동.
---

# /crypto-visual-review — 시각 검증 스킬 (schema v2.1)

백테스트 룰만으론 못 잡는 패턴(매집/분배/펌프&덤프/좀비/TF 충돌)을 **Claude 가 차트 PNG 를 직접 보고** 사이클·단계로 채점한다. 객관적 사실은 facts.json 으로 자동 추출하고 Claude 는 그것을 기반으로 시각 정성 판단을 보강한다. 결과는 표준 위치에 누적되어 시계열 비교 가능.

## 1. 목적

- 백테스트 신호의 보완: 룰로 표현 어려운 시각 패턴(매집봉, 분배, 페러볼릭)을 잡음.
- **자동매매 X — 추천 시그널 전용**.
- 사이클 라벨(A/B) + 단계(1~5) + 보조 enum 으로 모든 종목 동일 프레임 비교.
- **PNG 가 git 동기화 안 되어도** review JSON 만으로 당시 차트 상태 재구성 가능 (schema v2.1).

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

## 3. 자산별 지원 / TF 용도

facts 는 5 TF 모두 산출 가능. **review 채점은 1M/1W/1D 만**, **entry 트리거는 1D/4H/1H** 사용.

| 자산 | 가용 TF | review 채점 TF | entry 트리거 TF |
|---|---|---|---|
| crypto | 1H / 4H / 1D / 1W / 1M | 1M+1W+1D | 1D+4H+1H |
| crypto < 6개월 | 1D / (1H if 있음) | 1D만 (1M/1W 자동 생략) | 1D+1H |
| KR / US | 1D / 1W / 1M | 1M+1W+1D | (1D만 — 1H 캐시 없음) |

facts/review 저장 경로: `data/cache/{asset}/visual_review/`.

소스 캐시:
- 1H/4H → `data/cache/crypto/1h/{SYMBOL}.parquet` (4H 는 1H 에서 리샘플)
- 1D/1W/1M → `data/cache/{asset}/1d/{SYMBOL}.parquet` (1W/1M 은 1D 에서 리샘플)

## 4. 7단계 분석 프로토콜 (Claude 가 따라야 할 순서)

차트 분석은 항상 이 7단계로 진행. **1M/1W/1D 채점에만 적용**. 1H/4H 는 facts 만 산출하고 채점은 안 함 (entry 트리거 정량 신호용).

| # | 단계 | 보는 것 | 결과 → 필드 |
|---|---|---|---|
| **1** | 빅픽처 | 가격 범위, 전체 슬로프, 직전 고점 대비 | facts: `last_close`, `ret_30d/90d`, `from_period_high_pct` |
| **2** | 추세 해부 | MA 정배열, MA 간격, MA 기울기, 가격-MA 거리 | facts: `ma_stack`, `ma_slopes`, `ma_spread`, `price_pos`, `dist_from_ma`, `nearest_ma` |
| **3** | 미시 행동 | 마지막 봉, 캔들 모양, 거래량, 최근 강양봉 | facts: `last_candle`, `recent_strong_bull` + Claude: `micro_action`, `volume_flag` |
| **4** | 핵심 레벨 | 지지/저항선 | Claude: `observations.key_levels` |
| **5** | 사이클 위치 | A/B 어느 단계? | Claude: `state` + `confidence` |
| **6** | 위험 | 과열, DD, 이상 패턴 | facts: `auto_risk_flags` + Claude: 시각 보강 |
| **7** | 액션 | 매수/관망/회피 | Claude: `tf_consistency`, `verdict`, `verdict_reason`, `verdict_confidence` |

### 채점 워크플로

```
Step 0: facts.json 읽기 (단계 1, 2, 3-자동, 6-자동 결과)
Step 1: PNG 보고 빅픽처 sanity check
Step 2: MA 배열 + 가격 거리 확인 (facts 그대로 OK)
Step 3: 마지막 봉·거래량 시각 확인 → micro_action, volume_flag 결정
Step 4: 지지/저항 가격 픽 → observations.key_levels
Step 5: 1~4 종합 → state (A1~B5/C1) + confidence
Step 6: risk_flags = auto_risk_flags + 시각 보강
Step 7: 모든 TF 종합 → tf_consistency, verdict, verdict_reason
```

## 5. 저장 구조

```
data/cache/{asset}/visual_review/
├── coin_state.parquet           # 종목별 최신 상태 (한 줄 / symbol)
├── reviews/                     # ★ git tracked
│   └── {SYMBOL}/
│       └── {YYYYMMDD}.json      # 시점별 판정 (v2.1 schema)
└── charts/
    └── {SYMBOL}/
        └── {YYYYMMDD}/
            ├── _facts.json      # ★ git tracked (객관 사실, 최대 5 TF)
            ├── {SYMBOL}_1m.png  # gitignored (재생성 가능)
            ├── {SYMBOL}_1w.png  # gitignored
            ├── {SYMBOL}_1d.png  # gitignored
            ├── {SYMBOL}_4h.png  # gitignored (entry 용, 옵션)
            └── {SYMBOL}_1h.png  # gitignored (entry 용, 옵션)
```

### git 정책

```gitignore
# .gitignore
data/cache/*/visual_review/charts/**/*.png
```

PNG 는 큼 (~100KB × 3장 × 종목 수 = MB) + 재생성 가능. review JSON + facts.json 만 영구 보존하면 PNG 없어도 분석 재현 가능.

## 6. 차트 렌더링 규격

### 6.1 봉/MA/거래량

- **봉 수**: 200 봉 고정 (history 부족하면 가용 전체)
- **MA**: MA10 (gold) / MA20 (red) / MA50 (blue), width 0.8
- **거래량 서브플롯**: 포함
- **이미지**: 1280×720, dpi 110
- **렌더 도구**: `mplfinance` (style=charles, type=candle)
- **종목당 렌더 시간**: TF 한 장당 ~0.4초 (warmup 후) + facts.json 출력 ~0.05초
- **지원 TF**: 1H / 4H / 1D / 1W / 1M (5종)

### 6.2 history 부족 시 TF 자동 생략

`render.py` 가 자동 처리:
- bars < 10 인 TF 는 SKIP (PNG 미생성)
- review JSON 에서 해당 tf block 생략
- `tf_consistency` 는 가용 TF 만으로 평가 (또는 "분리")

### 6.3 MA 의미

- MA10 = 단기 추세선 (모멘텀)
- MA20 = 중기 추세선 (메인 지지/저항)
- MA50 = 장기 추세선 (큰 그림 지지/저항)

## 7. `_facts.json` 명세 (renderer 자동 출력)

차트 렌더와 동시에 객관적 사실을 자동 계산 후 JSON 으로 저장. **모든 필드는 자동 — Claude 가 손댈 일 없음, 그대로 review.context 에 복사**.

TF 는 호출 시 인자로 선택. 최대 5 TF (1m/1w/1d/4h/1h) 모두 같은 schema.

```json
{
  "symbol": "BTCUSDT",
  "asset": "crypto",
  "date_str": "20260520",
  "generated_at": "2026-05-20T14:00:00+09:00",
  "tfs": ["1m", "1w", "1d", "4h", "1h"],

  "tf_1m": {
    "last_close": 76803.8,
    "bars": 83,
    "date_range": "2019-07-31 ~ 2026-05-31",

    "ma10": 87668.74, "ma20": 91386.17, "ma50": 58902.23,
    "ma_stack": "혼합",                      // 정배열 / 역배열 / 혼합
    "ma_slopes": {"ma10": "down", "ma20": "up", "ma50": "up"},  // up/flat/down
    "ma_spread": "spread",                    // tight / normal / spread
    "price_pos": "between",                   // above_all / between / below_all
    "dist_from_ma": {"ma10_pct": -0.1239, "ma20_pct": -0.1596, "ma50_pct": 0.3039},
    "dist_from_ma_atr": {"ma10_atr": -0.687, "ma20_atr": -0.922, "ma50_atr": 1.132}, // ATR 정규화 거리 (1 ATR 단위)
    "nearest_ma": {"ma": "ma20", "dist_pct": -0.1596},   // 절대거리 최소 MA + 부호 유지

    "atr": 15813.05,                          // Wilder ATR(14)
    "atr_pct": 0.206,                         // ATR / close
    "adx": 28.97,                             // ADX(14). <20 횡보 / 25+ 추세
    "range_position": 0.26,                   // 최근 N봉 박스 내 위치 0=하단 / 1=상단

    "last_candle": {
      "type": "doji",                         // bull / bear / doji
      "body_pct": 0.0065,
      "upper_wick_pct": 0.88,                 // 위꼬리 / 봉 폭
      "lower_wick_pct": 0.04,                 // 아래꼬리 / 봉 폭
      "vol_rank_30d": 0.0,                    // 최근 30봉 중 거래량 백분위 (0~1)
      "vol_anomaly": null,                    // "spike" / "breakout" / null
      "accumulation_candle_score": 0.0,       // 0/0.3/0.6/1.0 (매집봉 단일봉)
      "distribution_candle_score": 0.0        // 0/0.3/0.6/1.0 (분배봉 단일봉)
    },

    "accumulation": {                          // multi-bar (5봉) 매집 — 기존
      "vol_5bar_vs_30bar": 0.9,
      "price_range_5bar_pct": 0.04,
      "accumulation_score": 0.0
    },

    "recent_strong_bull": null,               // 또는 아래 구조 (강양봉 발견 시)
    // {
    //   "bars_ago": 5, "body_pct": 0.0219, "vol_rank": 0.933, "close": 81056.6,
    //   "max_retrace_pct": 0.0623,             // 양봉 종가 대비 이후 최저점 하락폭
    //   "current_retrace_pct": 0.0525,         // 양봉 종가 대비 현재가 하락폭
    //   "holding": false                       // current<5% AND max<10% 면 true (안 무너짐)
    // }

    "ret_30d": 0.041,                          // 30봉 수익률 (TF 단위)
    "ret_90d": 0.156,
    "from_period_high_pct": -0.309,
    "vol_avg_recent_vs_prior": 0.829
  },

  "tf_1w": {...}, "tf_1d": {...}, "tf_4h": {...}, "tf_1h": {...},

  "auto_risk_flags": ["drawdown_deep"],       // parabolic/drawdown_deep/low_history/zombie

  "global_nearest_ma": {                       // 모든 TF × MA 중 절대거리 최소 1개 (cross-TF)
    "tf": "1h", "ma": "ma10", "dist_pct": -0.0005
  }
}
```

### 7.1 `vol_anomaly` 자동 감지 룰
- `"spike"`: body_pct < 1% AND vol_rank_30d > 0.85 (도지+거래량 폭증 → 매집/분배 의심)
- `"breakout"`: body_pct > 3% AND vol_rank_30d > 0.85 (큰 봉+거래량 폭증)
- `null`: 이상 없음

### 7.2 `accumulation_score` 자동 룰 (multi-bar)
- 1.0: vol_5/30 ≥ 1.5 AND 5봉 가격 폭 < 5%
- 0.6: vol_5/30 ≥ 1.2 AND 가격 폭 < 8%
- 0.3: vol_5/30 ≥ 1.0 AND 가격 폭 < 10%
- 0.0: 그 외

### 7.3 `auto_risk_flags` 자동 룰
- `parabolic`: 1D ret_30d > 0.5 OR 1D ret_90d > 1.0
- `drawdown_deep`: 1W (또는 1D) from_period_high_pct < -0.3
- `low_history`: TF 별 최소 봉수 부족 (crypto: 1h<200, 4h<100, 1d<100, 1w<50, 1m<24 / stocks 더 낮음)
- `zombie`: 1D vol_avg_recent_vs_prior < 0.3 AND abs(ret_90d) < 0.1

### 7.4 `nearest_ma` 자동 룰 (각 TF)
- 절대거리 `|dist_from_ma|` 최소인 MA 한 개 선택 (ma10/ma20/ma50 중)
- `dist_pct` 는 부호 유지 (음수 = MA 아래, 양수 = 위)
- threshold 없음 — 단순히 "어느 MA 가 가장 가까운지" + 거리값. **진입 트리거 필터/정렬용**.

### 7.5 `recent_strong_bull` 자동 룰 (각 TF)
최근 lookback 봉 안에 강양봉 1개 검색. **가장 최근** 봉 반환 (없으면 null).

강양봉 조건 (AND):
- `type=bull` (close > open AND body/range > 0.4)
- `body_pct >= 0.02` (2% 이상)
- 그 봉의 `vol_rank` (직전 30봉 대비) `>= 0.7`

lookback (TF 별):

| TF | lookback | 의미 |
|---|---|---|
| 1H | 48봉 | 이틀 |
| 4H | 24봉 | 4일 |
| 1D | 10봉 | 2주 |
| 1W | 6봉 | 1.5달 |
| 1M | 3봉 | 3달 |

출력: `{bars_ago, body_pct, vol_rank, close}` — `bars_ago=0` 이 가장 최근 봉.

### 7.6 `global_nearest_ma` 자동 룰 (cross-TF)
모든 TF × MA (최대 5×3=15개) 중 절대거리 최소 1개. 진입 트리거 종합 ranking 용.

### 7.7 `atr` / `atr_pct` / `dist_from_ma_atr` (각 TF)
**Wilder ATR(14)** — 봉당 평균 변동폭 절대값.
- `atr` : 가격 단위 (e.g. BTC 1D 약 2,000)
- `atr_pct` : `atr / close` (변동성 비교용)
- `dist_from_ma_atr.{ma}_atr` : `(close - ma) / atr`. 1.0 = 1 ATR 거리, ±0.5 이하 = 사실상 닿음
- 종목 변동성 자동 정규화. dist_pct 1.5% 가 BTC 엔 "닿음" 이지만 변동성 큰 알트엔 노이즈 — atr 단위가 진짜 거리.
- ATR 부족 시 (`bars < period+1`) `null`.

### 7.8 `adx` (각 TF)
**ADX(14)** — Wilder. 추세 강도 0~100 (방향 무관).
- `< 20` 횡보, `20~25` 약함, `25~50` 추세 있음, `50+` 강한 추세, `75+` 페러볼릭
- review state 검증용 — review 가 A2 라고 했어도 ADX 빠지면 토핑 의심 (state stale).
- 봉 부족 시 `null`.

### 7.9 `range_position` (각 TF)
최근 N봉 (1h=120, 4h=60, 1d=60, 1w=30, 1m=12) 박스 내 현재가 위치 0~1.
- `< 0.3` 박스 하단 (매집권)
- `> 0.7` 박스 상단 (분배권/신고가 임박)
- vol spike 가 발생했을 때 매집/분배 구분에 사용.

### 7.10 `last_candle.upper_wick_pct / lower_wick_pct`
봉 위·아래꼬리 비율 (봉 폭 대비).
- `lower_wick_pct >= 0.3` 이면 받침 (매집 신호)
- `upper_wick_pct >= 0.3` 이면 위꼬리 우세 (분배 신호)

### 7.11 `last_candle.accumulation_candle_score`
**vol_rank ≥ 0.85 필수**. 0/0.3/0.6/1.0.
- 패턴 (close_in_bar≥0.5, lower_wick≥0.3) 2점 + 위치 보너스 (range_position<0.4, from_high<-0.10) 2점
- pattern 2 + bonus 2 → 1.0
- pattern 2 + bonus 1 → 0.6
- pattern 1 + (vol_rank) → 0.3
- 0.6+ 면 매집봉 의심.

### 7.12 `last_candle.distribution_candle_score`
매집의 거울. **vol_rank ≥ 0.85 필수**.
- 패턴 (close_in_bar≤0.5, upper_wick≥0.3) 2점 + 위치 보너스 (range_position>0.6, from_high>-0.05) 2점
- 0.6+ 면 분배봉 의심.

### 7.13 `recent_strong_bull.max_retrace_pct / current_retrace_pct / holding`
강양봉 발견 후 retrace 정보.
- `max_retrace_pct` : 양봉 종가 대비 이후 최저점 하락폭 (양수)
- `current_retrace_pct` : 양봉 종가 대비 현재가 하락폭
- `holding=true` : `current<5%` AND `max<10%` (양봉 후 안 무너지고 수렴 중)
- **trend_pullback 핵심**: bars_ago≤10 AND holding=true 면 "장대양봉 + 수렴" 자동 캐치.

## 8. 채점 schema v2.1 (review JSON)

모든 필드 의무. v1 reviews 는 호환을 위해 계속 읽힘.

```json
{
  "symbol": "BTCUSDT",
  "asset": "crypto",
  "reviewed_at": "2026-05-20T15:00:00+09:00",
  "data_until": "2026-05-19",
  "scorer": {
    "model": "claude-sonnet-4-6",            // or claude-opus-4-7
    "agent_id": null,                        // 서브에이전트면 id
    "schema_version": 2.1
  },

  "tf_1m": {
    "state": "A2",                           // ★ Claude (11 enum, §9.1)
    "micro_action": "pullback_ma10",         // ★ Claude (9 enum, §9.2)
    "volume_flag": "normal",                 // ★ Claude (5 enum, §9.3)
    "confidence": "high",                    // ★ Claude (3 enum, §9.4)

    "context": { ... facts.tf_1m 그대로 복사 ... },

    "observations": {                        // ★ Claude (PNG 시각 추출)
      "key_levels": {"support": 95000, "resistance": 110000},
      "pattern": "stair_step_up",            // 자유 1~3 단어
      "recent_action": "신고가 갱신 후 MA10 풀백 진행"  // 1~2 문장
    }
  },
  "tf_1w": {...},
  "tf_1d": {...},

  "tf_consistency": "정합",                  // ★ Claude (§9.5)
  "verdict": "pass",                         // ★ Claude (§9.6)
  "verdict_confidence": "high",              // ★ Claude
  "verdict_reason": "전 TF A2 정합, 신고가 갱신 중",

  "risk_flags": ["parabolic"],               // auto + Claude 시각 보강

  "charts": {
    "1m": "charts/BTCUSDT/20260520/BTCUSDT_1m.png",  // 경로 hint
    "1w": "charts/BTCUSDT/20260520/BTCUSDT_1w.png",
    "1d": "charts/BTCUSDT/20260520/BTCUSDT_1d.png"
  }
}
```

## 9. ENUM 정의

### 9.1 `state` (11) — 사이클 단계

**사이클 A — 상승 추세**
| 값 | 시각 정의 |
|---|---|
| `A1` | 상승 출발. 변곡 직후 안정. MA 정배열 진행, 가격 MA20 위. |
| `A2` | 지속 상승. MA10/20/50 완전 정배열+우상향. 풀백마다 MA10/MA20 지지. |
| `A3` | 토핑 횡보. 신고가 못 가고 박스, MAs 평탄. |
| `A4` | 하락 첫 시도. MA20 아래 첫 음봉, 미확정. |
| `A5` | 하락 retest 확정. 풀백이 MA20 에 막힘+MA20 음 기울기. |

**사이클 B — 하락 추세**
| 값 | 시각 정의 |
|---|---|
| `B1` | 하락 시작. 피크 깬 첫 음봉+거래량. |
| `B2` | 지속 하락. MA 역배열+우하향. 좀비도 여기. |
| `B3` | 바닥 다지기. MAs 평탄·수렴, 가격 박스. |
| `B4` | 상승 첫 시도. MA20 위 첫 양봉, 미확정. |
| `B5` ⭐ | 상승 retest 확정. 풀백이 MA20 받음+MA20 양 기울기. **buy zone**. |

**C — 분류 불가**
| 값 | 시각 정의 |
|---|---|
| `C1` | 박스 (3년+ 횡보) / 펌프&덤프 / 비정상 / 신규 1D 도 박스 |

### 9.2 `micro_action` (9) — 단기 행동

| 값 | 의미 |
|---|---|
| `riding` | MA 위/아래 안정, 풀백 없이 진행 |
| `pullback_ma10` | MA10 닿는 중, 반등 미확정 |
| `pullback_ma20` | MA20 닿는 중, 반등 미확정 |
| `pullback_ma50` | MA50 까지 깊은 풀백, 반등 미확정 |
| `bounce_ma10` ⭐ | MA10 닿고 반등 확정 (양봉+거래량+MA10 위 복귀) |
| `bounce_ma20` ⭐ | MA20 닿고 반등 확정 (trend_pullback 핵심 시그널) |
| `bounce_ma50` ⭐ | MA50 닿고 반등 확정 |
| `breaking` | MA50 깨고 추세 끝나는 중 |
| `acceleration` | 페러볼릭 상승+거래량 폭증 |

**"반등 확정" 기준**: MA{N} 위로 복귀한 양봉+거래량+직전 1~2봉 안에 발생.

### 9.3 `volume_flag` (5) — 거래량 이상

| 값 | 의미 | 자동 신호 |
|---|---|---|
| `normal` | 추세에 부합 | (default) |
| `accumulation_suspect` ⭐ | 큰손 매집 의심 | spike + state∈{B3,B4,A1} OR acc_score≥0.6 |
| `distribution_suspect` | 큰손 분배 의심 | spike + state∈{A2,A3,A5} |
| `dry` | 좀비, 관심 빠짐 | vol_avg < 0.3 + 횡보 |
| `pump_dump_trace` | 작전 흔적 | 폭등 후 거래량 즉시 소멸 |

**판정 우선순위**: pump_dump_trace > distribution > accumulation > dry > normal.
**자세한 시각 패턴 / state 조합 → §10**.

### 9.4 `confidence` (3) — 자신감

| 값 | 의미 |
|---|---|
| `high` | 명확히 분류 가능 |
| `medium` | 경계 사례 |
| `low` | 데이터 부족 / 패턴 모호 |

각 TF 별로 + 최종 `verdict_confidence` 도 별도. low 인 케이스는 사람 재검토 큐 후보.

### 9.5 `tf_consistency` (3) — TF 간 정합성

| 값 | 의미 |
|---|---|
| `정합` | 모든 TF 가 같은 사이클(A or B) + 비슷한 단계 |
| `충돌` | 큰 TF 와 작은 TF 사이클이 다름 (예 1W=B, 1D=A) |
| `분리` | 같은 사이클인데 한 TF stable, 다른 TF 변환 중 |

### 9.6 `verdict` (4) — 최종 액션

| 값 | 의미 |
|---|---|
| `pass` | 매매 적합 (buy zone) |
| `watch` | 관망 (변곡 대기 / 충돌 / 페러볼릭 위험) |
| `skip` | 매매 회피 |
| `reject` | 영구 제외 (펌프&덤프 / 좀비+dry) |

**자동 derivation 룰 (예비)**:
- 큰 TF state ∈ {A1, A2, B5} + tf_consistency=정합 → `pass`
- 큰 TF state = B4 → `watch`
- 큰 TF state ∈ {B2, B3} → `skip` (B3는 watch 가능)
- 큰 TF state ∈ {A3, A4, A5} → `skip`
- volume_flag ∈ {pump_dump_trace} 또는 (dry + zombie risk) → `reject`
- volume_flag = accumulation_suspect + state ∈ {B3, B4} → `pass` 강화
- volume_flag = distribution_suspect + state ∈ {A2, A3} → `skip` 강화
- risk_flags 에 parabolic 있으면 한 단계 보수적

### 9.7 `risk_flags` (list) — 위험 태그

| 값 | 의미 | 자동/시각 |
|---|---|---|
| `parabolic` | 단기 폭등 | 자동 (1D ret_30d>0.5 OR ret_90d>1.0) |
| `drawdown_deep` | 피크 -30%+ | 자동 (1W from_period_high<-0.3) |
| `low_history` | 데이터 짧음 | 자동 (TF 별 봉수 부족) |
| `zombie` | 거래량 죽음 | 자동 (vol_avg<0.3 + 횡보) |
| `distribution_suspect` | 분배 의심 | 시각 (volume_flag 와 sync) |
| `pump_dump_trace` | 펌프&덤프 흔적 | 시각 (volume_flag 와 sync) |
| `accumulation_suspect` | 매집 의심 | 시각 (volume_flag 와 sync) |

## 10. `volume_flag` 시각 패턴 가이드

### 10.1 `accumulation_suspect` (매집 의심)

**시각**:
```
[가격]    ───•───•───•───•───•───   ← 작은 봉들 (도지/작은 양봉)
[거래량]   ▁▁▁▂▁▁▁▂▂█▂▂▂▂          ← 막대 하나 우뚝 (또는 줄지어 평균 위)
```

**state 조합별**:
| state | 해석 |
|---|---|
| B3 (바닥) + spike | ★ 매집 강함, B5 변환 임박 |
| B4 (상승 시도) + spike | 매집 확인 |
| A1 (변곡 직후) + spike | 새 추세 매집 |

### 10.2 `distribution_suspect` (분배 의심)

**시각**: accumulation 과 비슷하나 **고점권 + 위꼬리/음봉 거래량 우세**.

**state 조합별**:
| state | 해석 |
|---|---|
| A2 (강세) + spike | 분배 시작 → watch |
| A3 (토핑) + spike | ★ 분배 강함 → skip |
| A5 (retest) + spike | 마지막 분배 → exit |

### 10.3 `dry` (좀비)

**시각**: 거래량 막대 일관되게 평균 이하 + 가격 평탄.
**state 조합**: B2 + dry → 좀비 코인 / C1 + dry → reject 후보.

### 10.4 `pump_dump_trace` (펌프&덤프)

**시각**: 1~3봉 폭등 후 거래량+가격 즉시 죽음.
**자주 동반**: parabolic, drawdown_deep, low_history risk_flags 동시 트리거.
**verdict**: `reject` 확정.

## 11. 매매 함의 (요약)

| state | + volume_flag | verdict |
|---|---|---|
| A1, A2 | normal | pass (보유 / 풀백 매수) |
| A1, A2 | distribution | watch / skip |
| A2 | acceleration | watch (페러볼릭) |
| A3 | * | skip (비중 축소) |
| A4 | * | skip (exit 검토) |
| A5 | * | skip (exit 확정) |
| B1, B2 | * | skip |
| B2 | dry | reject (좀비) |
| B3 | accumulation | watch (변환 대기) |
| B3 | normal | watch (돌파 대기) |
| B4 | accumulation | pass (조심) |
| **B5** | normal/accumulation | **pass** ⭐ buy zone |
| C1 | pump_dump_trace | reject |

## 12. 헬퍼 모듈

```
research/visual_review/
├── __init__.py
├── facts.py           # 객관 사실 자동 계산 (compute_facts_all_tfs, auto_risk_flags)
├── render.py          # PNG + _facts.json 출력 (render_charts)
└── store.py           # reviews ↔ coin_state.parquet I/O (aggregate_state, load_review, save_review)
```

### CLI

```powershell
# review 용 차트 + facts.json (1M+1W+1D)
.venv/Scripts/python.exe -m research.visual_review.render BTCUSDT ETHUSDT --tfs 1m,1w,1d --asset crypto

# entry 용 facts (1D+4H+1H, PNG 도 같이 생성됨)
.venv/Scripts/python.exe -m research.visual_review.render BTCUSDT --tfs 1d,4h,1h --asset crypto

# 풀 — 5 TF 전체
.venv/Scripts/python.exe -m research.visual_review.render BTCUSDT --tfs 1m,1w,1d,4h,1h --asset crypto

# 집계 (reviews/*/<date>.json → coin_state.parquet)
.venv/Scripts/python.exe -m research.visual_review.store aggregate 20260520 --asset crypto

# 현재 상태 표시
.venv/Scripts/python.exe -m research.visual_review.store show --asset crypto
```

### Python

```python
from research.visual_review.render import render_charts
# review 용 (큰 그림 정성 채점용)
render_charts(["BTCUSDT", "ETHUSDT"], tfs=["1m","1w","1d"], asset="crypto")

# entry 용 (PNG 없이 facts 만 — Claude 채점 안 함, 정량 트리거 전용)
from research.visual_review.facts import compute_facts_all_tfs
facts = compute_facts_all_tfs("BTCUSDT", asset="crypto", tfs=["1d","4h","1h"])
# facts["global_nearest_ma"] / facts["tf_1h"]["nearest_ma"] / recent_strong_bull 활용

from research.visual_review.store import aggregate_state
aggregate_state("20260520", asset="crypto")
```

### 속도 가이드 (실측, 신규지표 atr/adx/range_pos/candle_score/retrace 포함)

| 작업 | 단일 종목 | 563 종목 |
|---|---|---|
| facts 5 TF (1m/1w/1d/4h/1h) | ~40 ms | ~22초 |
| facts entry 3 TF (1d/4h/1h) | ~25 ms | ~15초 |
| facts review 3 TF (1m/1w/1d) | ~15 ms | ~9초 |
| PNG 렌더 1 TF | ~0.4초 | ~4분 |

→ facts 만이면 전체 universe 30초 안에 갱신 — 1분 cron 으로 충분. PNG 는 review 모드에서만.

## 13. 채점 워크플로 (서브에이전트 / 직접)

### 13.1 효율적 처리 — `crypto-visual-reviewer` agent

전용 서브에이전트(`.claude/agents/crypto-visual-reviewer.md`) 가 schema v2.1 채점만 담당.
- 모델 **Sonnet 4.6 고정**, 도구는 Read/Glob/Grep/Write 만 (데이터 fetch 차단).
- 입력: batch 심볼 5~15개 + asset + date_str. PNG·facts 는 사전 렌더 가정.
- 출력: reviews/{SYMBOL}/{date}.json Write + 메인에 요약 한 줄씩.
- 10종목 batch ≈ 5~8분, ~$0.5. 3개 병렬 가능 → 30종목 ~10분.

refresh 모드 흐름:
1. 메인이 universe 로드 (classification.parquet) + render_charts 호출 (전체 PNG·facts 렌더)
2. 10종목씩 batch 분할
3. `Agent(subagent_type="crypto-visual-reviewer", ...)` 병렬 3개씩 호출
4. 모든 batch 완료 후 `store.aggregate_state` 로 집계

### 13.2 모델 선택

| 작업 | 권장 모델 | 이유 |
|---|---|---|
| 시각 채점 (refresh / signals) | **Sonnet 4.6** | 5x 저렴, 정확도 충분, 약간 보수적 (안전) |
| 복잡한 시각 audit / edge case | Opus 4.7 | 깊은 reasoning, 더 lenient |

**검증 사례**: 30 종목 비교 시 Opus vs Sonnet verdict 일치율 ~73~80%, 불일치는 대부분 1단계 인접 (pass↔watch, watch↔skip).

### 13.3 컨텍스트 윈도우 관리

- PNG 한 장 ≈ 1.2K 토큰. 30 종목 × 3 TF = ~110K 이미지 토큰
- **한 세션 20~30 종목** 권장 (Sonnet 1M context 이면 더 가능)
- `refresh` 모드는 batch 분할 (10 종목씩) → 병렬 가능

## 14. 동작 원칙

- **시각 판정 우선**: 코드 룰로 enum 자동 채점 X. Claude 가 PNG 보고 결정. 자동 facts 는 객관 사실만.
- **합의된 schema 외 새 값 금지**: 11 state / 9 micro_action / 5 volume_flag / 3 confidence / 6+ risk_flags. 새 값 필요 시 user 와 합의 후 SKILL.md 수정.
- **PNG 는 gitignored**: 재생성 가능. `render_charts(...)` 로 0.4s/종목.
- **review JSON + facts.json 은 git tracked**: 시계열 history + 객관 사실 영구 보존.
- **PNG 없이도 review 만으로 차트 상태 재구성 가능** (v2.1 핵심 목표).
- **시계열 history 유지**: `reviews/{SYMBOL}/` 옛 JSON 덮어쓰기 X. 날짜별 추가.
- **자동매매 X**: 추천 시그널 전용.
- **KST 시각 표준**: 모든 timestamp KST.

## 15. 향후 확장 / TODO

1. `filter.py` / `universe.py` 추가 — signals 모드 (오늘 신호 종목 자동 로드) + refresh 모드 (전체 universe + 사전 필터)
2. `signals.parquet` writer — 백테스트 신호 + visual_verdict 결합
3. 시계열 비교 모듈 — 지난주 vs 이번주 state 변화 추적
4. 자동 룰 + 시각 결합 정밀화 — verdict derivation 자동 룰 보완 (현재는 Claude 판단 위주)
5. KR/US 정식 지원 — render.py / facts.py 모두 asset='kr'/'us' 지원 검증
6. **Entry 트리거 통합** — `compute_facts_live(symbol, live_price)` 추가 (오늘 봉을 라이브 가격으로 합성), `entry_facts.parquet` writer (전체 universe nearest_ma + recent_strong_bull 종합 표), 대시보드 컬럼 노출

## 16. 캘리브된 표본 (검증 완료)

| state | crypto | US |
|---|---|---|
| A1 | TONUSDT 1D (B 전환 직후) | TXN 1M, ARM 1M, QCOM 1M |
| A2 | HYPEUSDT, NVDAUSDT, MUUSDT | NVDA, AAPL, AMZN, GOOGL, AMD, AVGO, LRCX, KLAC |
| A3 | ZECUSDT 1W | (정밀 표본 부족) |
| A4 | (transient) | (transient) |
| A5 | XAGUSDT 1D | META, NFLX (피크 후 retest) |
| B1 | (transient) | (transient) |
| B2 | ETHUSDT 1W, SOLUSDT 1W, DOGEUSDT 1M | TMUS 1W/1D |
| B3 | BTCUSDT 1W/1D, PEPEUSDT, ADAUSDT | META 1D, NFLX 1D |
| B4 | SUIUSDT 1D, ONDOUSDT 1D | TSLA 1D |
| B5 | (찾는 중) | (찾는 중) |
| C1 | RAVEUSDT, BSBUSDT (펌프&덤프) | (해당 없음) |

### volume_flag 표본
- `accumulation_suspect`: XAUTUSDT 1W, MUUSDT 1D (auto detect + 시각 확인)
- `distribution_suspect`: ORCAUSDT, ONDOUSDT, SKYAIUSDT (1W/1D)
- `pump_dump_trace`: LABUSDT, BSBUSDT, RAVEUSDT, UBUSDT, TRUMPUSDT
- `dry`: ADAUSDT 1W (이전 v2 판정 — v2.1 에선 normal 으로 회수됨)
