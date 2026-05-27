# 롱 진입 전략 5분류 — 토론 기록

> 위치: `docs/strategy_discussion.md`
> 시작: 2026-05-27 KST
> 목적: 사용자가 추구하는 **롱 진입 패턴 5가지** 의 정의와 현재 시스템 매핑.
> 이어서 대화하기 위한 컨텍스트 기록. (운영 매뉴얼 아님 — 합의 후 별도 PLAN 파일로 옮길 것)

---

## 0. 토론 출발점

- 사용자: "research / scripts / backtest 가 분리되어야 할 이유가 있냐"
  → 옵션 A 진행 완료: `research/visual_review/` → `scripts/_common/visual_review/` 이동. `research/` 는 KR 리포트 전용으로 명확화.
- 그 후 롱 전략 카테고리 토론으로 전환. **사용자가 추구하는 진입 패턴 4~5가지** 를 정리하는 것이 본 문서 목적.
- **결정 사항**: 본 토론에서 `backtest/strategies/*` 는 평가 대상에서 제외. `scripts/` 안의 점수 로직만으로 평가.

---

## 1. 5개 패턴 정의 (사용자 합의 대기 중)

> **공통 원칙**: 5개 패턴 모두 **TF 무관**. 1m / 1w / 1d / 4h / 1h 어떤 봉에서든 발생 가능. 시간축은 검출 함수의 입력 파라미터이지 패턴 정의의 일부가 아니다.

### 패턴 1. 강한 양봉 후 눌림 (First Pullback)
- **핵심**: 큰 양봉 → 조정 (MA10/20 터치) → 다음 양봉에 진입
- **상태**: 이미 추세 있음. 단기 휴식
- **알려진 이름**: Bull Flag, Cup-with-Handle 손잡이

### 패턴 2. 꾸준한 상승 (Steady Climb)
- **핵심**: 강한 양봉 없이 작은 양봉이 누적, 변동성 낮음, MA10 위에서 미끄러지듯
- **상태**: 추세 진행 중. 신선도 무관
- **알려진 이름**: Stage 2 Steady, Slow Riding

### 패턴 3. 채널링 (Repeated MA Touch)
- **핵심**: **같은 MA 를 3회 이상 정확히** 맞고 튕김. USUSDT 주봉 MA10 같은 예시 (단, 1h/4h/1d 모두 가능)
- **상태**: 명확한 트렌드 라인. 터치 이력이 신뢰의 원천
- **알려진 이름**: Channel Riding, MA Bounce Series

### 패턴 4. 저점에서 추세 돌리기 (Stage 1→2)
- **핵심**: 한참 하락/횡보 → 양봉 점화 → 첫 눌림 + 반등
- **상태**: **추세 막 발생**. 신선함이 핵심
- **알려진 이름**: Trend Reversal, Stage 2 Entry, Weinstein

### 패턴 5. Spring (Wyckoff Spring)
- **핵심**: 박스 매집 → 박스 하단 잠깐 깸 (가짜 이탈) → 다시 위로 + 반전
- **상태**: **아직 추세 없음 / 매집 끝물**. 가장 빠른 진입
- **알려진 이름**: Failed Breakdown, Bear Trap
- **사용자 코멘트**: "이부분이 어려워보임"

---

## 2. 패턴 간 관계

### 한눈에 비교

> 모든 패턴은 TF 무관. 같은 패턴이 1m / 1w / 1d / 4h / 1h 어디서든 발생.

| # | 추세 유무 | 신선도 | 진입봉 가격 위치 | 빈도 | 검출 난이도 |
|---|---|---|---|---|---|
| 1. 첫 눌림 | YES | 단기 휴식 | MA10/20 위 | 많음 | 쉬움 |
| 2. 꾸준한 상승 | YES | 진행 중 (오래 OK) | MA10 살짝 위 | 많음 | 쉬움 |
| 3. 채널링 | YES | 진행 중 (필수: 3회+ 터치) | MA 정확히 닿음 | 중간 | 중간 |
| 4. Stage 1→2 | **NO→YES 전환** | 막 발생 | 베이스 직후 | 적음 | 어려움 |
| 5. Spring | **아직 NO** | 매집 끝물 | 베이스 하단 잠깐 깸 | 매우 적음 | 매우 어려움 |

### 카테고리 분류
- **추세 안 진입** (1, 2, 3): 신뢰도↑ 빈도↑ — 메인 운용
- **추세 전환 잡기** (4, 5): 신뢰도↓ 빈도↓ — 잡으면 alpha 큼

### 부분집합 관계
- **1번 ⊃ 4번**: 4번 = 1번 + "직전 베이스" 게이트
- **2번 ⊃ 3번**: 3번 = 2번 + "3회 이상 터치" 게이트
- **5번 독립**: 베이스 안의 가짜 이탈 — 다른 4개와 모양 다름

### 시간 시퀀스 (한 종목의 전체 라이프사이클)
```
하락/횡보 → 매집 → Spring(5) → 베이스 깸 양봉 → 첫 눌림 = Stage1→2(4)
                                                ↓
                                          정배열 형성
                                                ↓
                                       N차 눌림 = 첫 눌림(1)
                                                ↓
                                  꾸준한 상승(2) / 채널링(3)
                                                ↓
                                          추세 종료 / 분배
```

---

## 3. 현재 시스템 매핑 (scripts only)

### 평가 대상 함수

`backtest/strategies/*` 는 본 토론에서 제외. `scripts/` 안의 점수 로직만 평가:

| 전략 | 함수 위치 | 운영 path |
|---|---|---|
| trend_pullback | `scripts/kr/trend_pullback/scoring.py` (v3) | numeric ratio |
| trend_pullback | `scripts/kr/trend_pullback/scoring_label.py` | label-based dict (recommend_all 표준) |
| trend_pullback | `scripts/crypto/trend_pullback/scoring.py` | crypto TF-무관 |
| trend_pullback | `scripts/_common/visual_review/setup_scores.py` | facts dict 기반 |
| trend_chase | `scripts/kr/trend_chase/scoring.py` (v5_1) | numeric ratio |
| trend_chase | `scripts/kr/trend_chase/scoring_label.py` | label-based dict |
| trend_chase | `scripts/crypto/trend_chase/scoring.py` (6 함수) | 1d / mtf / entry_1h / entry_4h |
| trend_chase | `scripts/_common/visual_review/setup_scores.py` | facts dict 기반 |
| ma20w_short | `scripts/crypto/ma20w_short/_common.py` | slope_4w 게이트 (short, 본 토론 외) |
| **quiet_bottom** | **없음** | scripts 단에 미구현 |
| **cascading_pullback** | **없음** | backtest 본체 wrapper 만 |

### 패턴 ↔ 코드 매핑

| 사용자 패턴 | 현재 시스템 | 매핑 수준 |
|---|---|---|
| 1. 첫 눌림 | `setup_scores.trend_pullback` (facts) ★ + KR `scoring_label` (label) | **정확** — Minervini 정의에 가장 근접 |
| 2. 꾸준한 상승 | KR `score_pullback_v3` + crypto `score_chase_1d_core` 일부 | **부분** — ret_90d 가중치로 간접 캡처. 직접 정의 없음 |
| 3. 채널링 | **`score_chase_mtf`** (2026-05-27, crypto) | ★ **이미 존재** — 단 trend_chase 폴더에 묻혀있음. 위치 부정합 |
| 4. Stage 1→2 | 없음 | **신규 필요** |
| 5. Spring | 없음 | **신규 필요** (난이도 높음) |

### 핵심 진단

1. **`score_chase_mtf` 가 사실 채널링 (패턴 3)** — 강양봉/거래량 컴포넌트 다 제거하고 1h+4h+1d+1w 정배열 게이트 + 1h MA10 bounce 횟수 (48h, 2~3회 sweet)만 본다. 이름과 위치만 잘못 됨.
2. **`trend_chase` 이름이 6 갈래 함수에 분산** — universe 가 다 다름. 어느 게 운영 표준인지 코드만 봐서는 모호.
3. **`trend_pullback` 도 3~4 갈래** — `scoring.py` (numeric) 와 `scoring_label.py` (라벨 기반) 의 universe 가 disjoint.
4. **scripts 단에 quiet_bottom 점수 없음** — backtest 본체에만 있음. 운영 path 끊김.
5. **ATR 정규화는 `setup_scores` 만** — 다른 모든 path 는 % 절댓값 (3%, 5%, 8%) 으로 변동성 무시.
6. **`score_*_crypto_tf` 의 "TF 무관" 은 거짓말** — `compute_indicators` 의 rolling 윈도우 (10/30/252) 가 TF 별로 다른 시간 의미를 만듦.

### USUSDT 채널링 검증 결과
- 사용자 차트: 2026-04~2026-05 의 6주 USUSDT 주봉 MA10 반복 터치
- `trend_pullback` (default): 10봉 모두 score=0 — `rally_lookback=60` 게이트가 신규 알트 차단
- `trend_pullback` (tuned, rally_lb=12): 1봉만 score=55 < threshold(80)
- **결론**: 현재 `trend_pullback` 으로는 채널링 못 잡음. 별도 channeling 전략 필요. 단 `score_chase_mtf` 가 이미 그 정의 — 분리만 필요.

---

## 4. 미해결 결정사항

### A. 패턴 정의 자체
- ✅ **5개 본질 정의 확정** (2026-05-27)
  - 시간축은 패턴 정의의 일부가 아님 (TF 무관 — 1m/1w/1d/4h/1h 어디서든 발생)
- ✅ **운용 공통 게이트 확정** (2026-05-27) — §7 참조
- 다음: 패턴별 운용 파라미터 (holding/stop/비중) 는 향후 토론

### B. 코드 정리
- `score_chase_mtf` 를 `scripts/crypto/channeling/` 으로 분리할지 (가장 작은 변경, 큰 효과)
- `trend_chase` 6 갈래 중 운영 표준 1개 명시 — 나머지는 baseline 또는 삭제
- scripts 단 `quiet_bottom` / `cascading_pullback` 점수 신설 vs 운영 universe 에서 제거

### C. 신규 전략
- 패턴 4 (Stage 1→2): quiet_bottom watchlist × trend_pullback 합성으로 구현 가능. 우선순위?
- 패턴 5 (Spring): 검출 난이도 가장 높음. v2 미루기?

### D. 다음 토론 순서 (사용자 결정 대기)
- **(a) 운용 측면**: holding 기간, stop, 비중, 동시 보유 가능성
- **(b) 검출 측면**: 5개 각각 어떤 지표로 잡나
- **(c) 우선순위**: 빈도×신뢰도 관점에서 어디부터 잘 만들까

**클로드 추천 순서**: (c) → (b) → (a)

---

## 5. 작업 이력 (이 세션)

1. `research/visual_review/` → `scripts/_common/visual_review/` 이동 완료 (옵션 A)
   - 20 파일 import 경로 업데이트
   - smoke test 통과
   - 미커밋 상태 (작업 완료 후 별도 커밋 예정)
2. 5개 패턴 토론 정리 (본 문서)
3. 5개 패턴 본질 정의 확정 (시간축 = 패턴 정의의 일부 아님, TF 무관)
4. 운용 공통 게이트 확정 — §7 (주봉 MA20 slope ≥ 0)

---

## 6. 빠르게 다시 시작하는 법

다음 세션에서 이 문서로 컨텍스트 복원하려면:
```
@docs/strategy_discussion.md 읽고 우리가 멈춘 지점부터 이어가자
```

마지막 멈춘 지점: **§4-D 다음 토론 순서 결정 대기 — (b) 검출 측면 / (c) 우선순위 중 선택**.

§7 운용 게이트 확정됨 (주봉 MA20 slope ≥ 0). 검출 단계는 이 게이트를 사전 universe filter 로 가정.

---

## 7. 운용 공통 원칙

### 7.1 트리거 게이트 — 주봉 MA20 slope ≥ 0

**모든 롱 진입의 사전 universe filter.** 5개 패턴 (§1) 중 어느 것의 시그널이 발생하더라도, 본 게이트 미달이면 진입 보류.

**정의:**
```
slope_4w(t) = MA20w[t] / MA20w[t-4] - 1
조건       : slope_4w(t) ≥ 0
기준 시점  : 직전 완성 주봉 (룩어헤드 회피 — 미완성 주봉 사용 금지)
```

**선택 이유 (close > MA20 게이트 대비):**
- `close > MA20` 만 보면 큰 음봉 후 잠깐 위로 튀어오른 거짓 돌파 통과
- `MA20 slope ≥ 0` 은 MA20 자체의 방향성을 본다 — 더 본질적
- 4주 정규화 차분 (`scripts/crypto/ma20w_short.slope_4w` 정의 동일) — 1주 차분 대비 노이즈 적음

**5개 패턴별 통과 여부:**

| 패턴 | 통과 | 이유 |
|---|---|---|
| 1. 첫 눌림 | ✅ | 추세 안 → 당연히 slope > 0 |
| 2. 꾸준한 상승 | ✅ | 정의상 slope > 0 |
| 3. 채널링 | ✅ | 정의상 slope > 0 |
| 4. Stage 1→2 | ✅ | slope 가 0 에서 + 로 막 전환되는 시점 — 진짜 신선한 진입 |
| 5. Spring | ✅ | 박스 매집 끝물 보통 slope ≈ 0 — 0 포함이므로 통과 |

→ 5개 모두 살아남음. `close > MA20` 게이트는 Spring 차단됐는데 이 정의는 살린다.

**차단되는 종목:**
- Stage 4 (분배 후 하락) — slope 음수
- 데드 캣 바운스 — slope 음수
- 횡보 → 깨고 하락 직전 — slope 음수로 전환

**신규 종목 처리:**
- 주봉 20봉 미만 (= 약 5개월 미만 상장 종목) → MA20 미정 → **universe 자동 제외**
- 신규 알트, 신규 IPO 못 잡는 정책 인정

**구현 위치 (예정):**
- `scripts/_common/long_gate.py` 같은 자산 무관 helper
- 모든 패턴별 scoring 함수가 마지막에 게이트 통과 여부로 score floor 0 처리
- 일봉 시그널이라도 주봉 MA20 slope 는 직전 완성 주봉 (보통 월요일 09:00 KST 이전 마감 주봉)
