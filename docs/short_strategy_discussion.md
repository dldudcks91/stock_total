# 숏 진입 전략 — 토론 기록 (크립토 전용)

> 위치: `docs/short_strategy_discussion.md`
> 시작: 2026-05-28 KST
> 목적: 크립토 숏 진입 패턴 후보 정리 + 롱(`strategy_discussion.md`) 대비 비대칭 정리.
> 자산: **crypto 전용** (KR/US 는 제도적 숏 제약, 그리고 KR/US 는 long-only 알파 위주 운용 합의)
> 출발: 기존 `scripts/crypto/ma20w_short/` 폐기. "주봉 MA20 slope < 0" 단일 게이트 가설은 좁다고 판단, 룰 자체를 재정의.

---

## 0. 토론 출발점

- 사용자 발언: "코인이새기들 숏쳐야될듯" → 크립토 시장 전반의 분배/하락 구간에 대한 숏 알파 필요.
- 롱 5패턴(`strategy_discussion.md`) 과 **대칭 구조** 로 숏 패턴을 분류. 다만:
  - 롱은 시간 비대칭(상승은 길고 느림) 가정이라면, 숏은 정반대(하락은 빠르고 짧음) → 운용 파라미터 자체가 다름.
  - 크립토 한정 추가 시그널: **funding rate, OI (Open Interest), LSR (Long/Short Ratio)** — 주식엔 없는 데이터.
- **결정 사항**: 이 토론은 진입 패턴 후보 나열까지. 합의 후 `scripts/crypto/<strategy>/PLAN.md` 로 분해.

---

## 1. 5개 숏 패턴 정의 (사용자 합의 대기 중)

> **공통 원칙**: 5개 패턴 모두 **TF 무관**. 1m / 1w / 1d / 4h / 1h 어떤 봉에서든 발생 가능.
> 롱 5패턴과 1:1 대칭이지만, 모양·검출·운용은 비대칭.

### 패턴 S1. 강한 음봉 후 반등 거부 (First Lower-High / Bear Flag)
- **핵심**: 큰 음봉 → 짧은 반등 (MA10/20 터치) → 다음 음봉에 진입
- **상태**: 이미 하락 추세. 단기 휴식 후 재가속
- **알려진 이름**: Bear Flag, Pennant Breakdown
- **롱 대칭**: 패턴 1 (First Pullback) 의 거울
- **검출 난이도**: 쉬움. 거래량 폭증이 동반되면 신뢰도↑

### 패턴 S2. 꾸준한 하락 (Steady Decline / Staircase Down)
- **핵심**: 강한 음봉 없이 작은 음봉이 누적, 변동성 낮음, MA10 아래에서 미끄러지듯
- **상태**: 추세 진행 중. Stage 4 정중앙
- **알려진 이름**: Stan Weinstein Stage 4, Slow Bleed
- **롱 대칭**: 패턴 2 (Steady Climb) 의 거울
- **주의**: 크립토에서는 흔치 않다 — 보통 폭락 후 횡보로 가지, 꾸준히 흘러내리는 경우는 알트 분배 후반에 주로 출현

### 패턴 S3. 채널링 (Repeated MA Rejection)
- **핵심**: **같은 MA(주로 MA20 또는 MA50) 에 3회 이상 정확히** 닿고 거부 (위로 못 뚫음)
- **상태**: 명확한 하락 채널 라인. 거부 이력이 신뢰의 원천
- **알려진 이름**: Descending Channel, MA Rejection Series
- **롱 대칭**: 패턴 3 (Repeated MA Touch) 의 거울 — 단, 롱은 "위에서 닿고 튕김", 숏은 "아래에서 닿고 거부됨"
- **크립토 예시 후보**: 알트 long-tail 하락 (LUNA, ATOM 등 2022~2023)

### 패턴 S4. 고점에서 추세 돌리기 (Stage 3→4 / Distribution Top)
- **핵심**: 한참 상승/횡보 (분배) → 음봉 점화 (neckline 이탈) → 첫 반등 + 거부
- **상태**: **추세 막 발생**. Wyckoff Distribution → markdown 전환
- **알려진 이름**: Head & Shoulders, Wyckoff Distribution (SOW/LPSY), Stage 3→4
- **롱 대칭**: 패턴 4 (Stage 1→2) 의 거울
- **신뢰도**: H&S confirmed 시 80% 가까운 성공률 보고
- **사용자 주목 포인트**: 크립토 사이클 정점 잡기 — alpha 가장 큰 구간

### 패턴 S5. Upthrust (Wyckoff UTAD / Bull Trap)
- **핵심**: 박스 분배 → 박스 상단 잠깐 돌파 (가짜 돌파) → 다시 아래로 + 반전
- **상태**: **아직 하락 추세 없음 / 분배 끝물**. 가장 빠른 진입
- **알려진 이름**: Upthrust After Distribution (UTAD), Bull Trap, Failed Breakout
- **롱 대칭**: 패턴 5 (Spring) 의 거울
- **난이도**: 가장 어려움 — 진짜 돌파인지 가짜 돌파인지 사후에만 확정. 다만 funding rate / LSR 같은 derivatives 데이터로 사전 신호 보강 가능

---

## 2. 패턴 간 관계

### 한눈에 비교

> 모든 패턴은 TF 무관. 같은 패턴이 1m / 1w / 1d / 4h / 1h 어디서든 발생.

| # | 추세 유무 | 신선도 | 진입봉 가격 위치 | 빈도 | 검출 난이도 |
|---|---|---|---|---|---|
| S1. Bear Flag | YES | 단기 휴식 | MA10/20 아래 | 많음 | 쉬움 |
| S2. Steady Decline | YES | 진행 중 (오래 OK) | MA10 살짝 아래 | 적음 (크립토) | 쉬움 |
| S3. MA Rejection | YES | 진행 중 (필수: 3회+ 거부) | MA 정확히 닿음 | 중간 | 중간 |
| S4. Stage 3→4 | **YES→NO 전환** | 막 발생 | 분배 직후 | 적음 | 어려움 |
| S5. Upthrust | **아직 YES (분배 끝물)** | 가짜 돌파 직후 | 박스 상단 잠깐 깸 | 매우 적음 | 매우 어려움 |

### 카테고리 분류
- **하락 안 진입** (S1, S2, S3): 신뢰도↑ 빈도↑ — 메인 운용
- **하락 전환 잡기** (S4, S5): 신뢰도↓ 빈도↓ — 잡으면 alpha 큼 (사이클 top)

### 부분집합 관계 (롱과 동일)
- **S1 ⊃ S4**: S4 = S1 + "직전 분배 (Stage 3 박스)" 게이트
- **S2 ⊃ S3**: S3 = S2 + "3회 이상 MA 거부" 게이트
- **S5 독립**: 박스 안의 가짜 돌파 — 다른 4개와 모양 다름

### 시간 시퀀스 (한 종목의 분배~하락 라이프사이클)
```
정배열 추세 종료 → 분배 (Stage 3) → Upthrust(S5) → neckline 이탈 음봉 = Stage3→4(S4)
                                                       ↓
                                                 역배열 형성
                                                       ↓
                                              N차 반등 거부 = Bear Flag(S1)
                                                       ↓
                                       꾸준한 하락(S2) / 채널 거부(S3)
                                                       ↓
                                              매도 클라이맥스 / Stage 1 (재매집)
```

---

## 3. 크립토 특수 — 롱과 비대칭인 부분 (가장 중요)

### 3.1 시간/공간 비대칭

| 항목 | 롱 | 숏 |
|---|---|---|
| 잠재 수익 | 무한 | 0 (-100% 캡) |
| 잠재 손실 | -100% 캡 | **무한** (이론상) |
| 추세 지속 | 길고 느림 (months~years) | 빠르고 짧음 (days~weeks) |
| 진입 윈도우 | 넓음 | **좁음** — 늦으면 바닥, 빠르면 squeeze |
| 변동성 | 상승 구간 낮음 | 하락 구간 폭증 |
| 갭 | 갭 하락 (드물게 손실) | **갭 상승** (악재 회복 / 펌프) — 손절 점프 빈번 |

→ 운용 임팩트: **trail/SL 더 빡빡하게**, hold 기간 짧게, position size 작게.

### 3.2 크립토 한정 derivatives 시그널 (주식 대비 강점)

#### Funding Rate (8h 주기 펀딩비)
- **양의 펀딩비 (positive funding)**: perp 가 spot 위 → 롱이 숏에게 지불 → 시장은 long-heavy
- **음의 펀딩비 (negative funding)**: perp 가 spot 아래 → 숏이 롱에게 지불 → 시장은 short-heavy
- **활용**:
  1. **숏 진입 시그널**: 극단적 양의 펀딩비 (e.g. +0.1%/8h 이상 지속) → 롱 squeeze 후보 → contrarian short
  2. **숏 보유 비용**: 음의 펀딩비 구간 = 숏이 매 8h 비용 지불 → carry cost 부담
  3. **신호 강도**: 펀딩비 + price action 동시 발현 시에만 (둘 중 하나만으론 너무 빈번)

#### LSR (Long/Short Ratio)
- 거래소 (Binance/Bitget) account 기반 L:S 비율
- **> 1.0 = 롱 우세, < 1.0 = 숏 우세**
- **활용**: contrarian — 극단치(LSR ≥ 3 같은)일수록 squeeze 후보. 단독 신호 X, derivatives confirm 용
- 출처: CoinGlass, 거래소 자체 API

#### Open Interest (OI)
- 미체결 계약 총량. 상승 + 가격 상승 = 신규 롱 진입. 상승 + 가격 하락 = 신규 숏 진입
- **숏 cascade 예측**: 가격 상승 + OI 급증 + 양의 펀딩비 = 청산 캐스케이드 위험 ↑↑ — 이런 구간에 숏 진입은 squeeze 직격탄

#### Liquidation Heatmap
- 청산 가격 클러스터 시각화 (CoinGlass 등)
- **운용**: 대량 롱 청산 가격대 위에서 숏 진입 시, 그 가격대까지 가격 끌어내릴 확률 ↑ ("magnet effect")

### 3.3 크립토 숏의 운용 원칙 (검색 결과 종합)

- **레버리지 ≤ 5x** (squeeze 생존 가능 수준)
- **stop loss 는 기술적 레벨 위** (구체 가격 위, "swing high + ATR" 같이 클러스터링 회피)
- **수직 캔들 추격 금지** — 진입은 반등 거부 확인 후
- **funding cost 누적 모니터링** — 1주 hold 시 평균 -0.5~-1% 정도는 각오
- **저유동성 알트 단독 숏 금지** — squeeze + 슬리피지 직격탄. BTC/ETH/major alt 한정

---

## 4. 현재 시스템 매핑 (scripts only)

### 평가 대상 함수
- 현재 `scripts/crypto/` 안에 **숏 점수 함수 0개**. 기존 `ma20w_short/` 폐기 후 신규 작성 필요.

### 패턴 ↔ 코드 매핑 (예상)

| 패턴 | 신규 폴더 후보 | 재사용 가능 코드 |
|---|---|---|
| S1. Bear Flag | `scripts/crypto/bear_flag/` | `trend_pullback/scoring.py` 거울 — MA10/20 reject 로직 |
| S2. Steady Decline | `scripts/crypto/steady_decline/` | `trend_pullback` 의 slope/거리 함수 부호 반전 |
| S3. MA Rejection | `scripts/crypto/ma_rejection_short/` | `_common/touch_count.py` 같은 신규 헬퍼 필요 |
| S4. Stage 3→4 | `scripts/crypto/distribution_top/` | quiet_bottom 의 6 조건 거울 — close<MA20, slope/accel 음, avg_runup, neckline 이탈 |
| S5. Upthrust | `scripts/crypto/upthrust/` | 가장 신규 — 박스 검출 + 가짜 돌파 검출 + funding/LSR confirm |

### 핵심 진단
1. **S1~S3 는 롱 거울로 빠르게 빌드 가능** (점수 함수 부호 반전 + MA 위→아래 로직)
2. **S4, S5 는 신규 로직 필요** — 분배 박스 검출, 가짜 돌파 검출
3. **derivatives 데이터 수집 인프라 부재** — 현재 `data/sources/bitget.py` 는 OHLCV 만. funding/LSR/OI 수집기 추가 필요 (Bitget API 또는 CoinGlass)

---

## 5. 미해결 결정사항 (사용자 결정 대기)

### A. 패턴 정의 자체
- A1. 5패턴 분류 OK 인가? (롱과 1:1 대칭 구조 유지 vs 숏 고유 패턴 추가)
- A2. S2 (Steady Decline) 는 크립토에 너무 드물면 제외? (4패턴으로 줄임)
- A3. funding/LSR/OI 같은 derivatives 시그널을 **독립 패턴** 으로 둘지, 아니면 5패턴의 **confirm filter** 로만 쓸지

### B. 우선 구현 순서
- B1. S1 (Bear Flag) — 가장 쉽고 빈도 많음 → 먼저
- B2. S4 (Stage 3→4) — alpha 가장 큼 → 두 번째
- B3. S3 (MA Rejection) — 신뢰도 높음, 빈도 중간 → 세 번째
- B4. S5 (Upthrust) — 가장 어려움, 데이터 인프라 필요 → 마지막

### C. 신규 인프라
- C1. Funding rate / OI / LSR 수집기 작성 — Bitget REST 직접 vs CoinGlass API
- C2. 캐시 구조 — `data/cache/crypto/derivatives/{SYMBOL}.parquet` 형태?
- C3. Backtest 에서 funding cost 어떻게 반영? (기존 ma20w_short PLAN 의 가정: -0.6%/주)

### D. 운용 정책
- D1. 숏 진입 자산 범위 — 전체 553 symbol vs 분류된 trend/follower 그룹만 vs market cap top-30 만
- D2. 레버리지 정책 — 1x (spot equivalent) vs 2~3x
- D3. 자동매매 X 추천 전용? (사용자 메모 `feedback_user_preferences.md`: "자동매매 X 추천만" — 숏도 동일?)

---

## 6. 작업 이력 (이 세션)

1. 사용자: "롱 전략 지금 5가지지?" → CLAUDE.md 표(3개 구현) + `docs/strategy_discussion.md`(5패턴 토론) 정리.
2. 사용자: "숏전략은 보통 어떻게 잡지?" → 답변 (3 템플릿: trend-following / distribution top / blow-off + 크립토 비대칭).
3. 사용자: "ma20w_short 삭제하고 숏전략으로 가자, 코인이새기들 숏쳐야될듯, 인터넷 검색으로 천천히 다시 세워봐"
4. `scripts/crypto/ma20w_short/` 삭제 (PLAN.md + baseline.py + 1 run 폐기).
5. WebSearch 10건 — bear flag / Wyckoff distribution / funding arbitrage / blow-off / squeeze cascade / Stage 4 / LSR / momentum-mean-reversion / descending triangle / pump-dump.
6. 본 문서 작성.

---

## 7. 빠르게 다시 시작하는 법

- 이 파일 (`docs/short_strategy_discussion.md`) + 롱 토론 (`docs/strategy_discussion.md`) 두 개 읽으면 컨텍스트 복원.
- 합의 완료 패턴부터 `scripts/crypto/<short_strategy_name>/PLAN.md` 로 분리.
- 5패턴 모두 합의되면 본 토론 문서는 **참고용** 으로만 남기고, 실제 운용은 PLAN 별로.

---

## 8. 출처 (웹 검색 — 2026-05-28)

**Bear Flag / Breakdown / Trend-following Short**
- [Bear Flag Pattern: Crypto Charts & Technical Analysis 2026 — ChangeNow](https://changenow.io/blog/bear-flag-in-crypto)
- [Short Selling Crypto: How to Profit in Bear Markets — Altrady](https://www.altrady.com/blog/crypto-trading-strategies/short-selling-crypto)
- [Bear Flag Pattern: Structure, Signals, and Breakdown — BYDFi](https://www.bydfi.com/en/cointalk/bear-flag-pattern)

**Wyckoff Distribution / H&S**
- [Wyckoff Distribution: Key Pattern Explained — LuxAlgo](https://www.luxalgo.com/blog/wyckoff-distribution-key-pattern-explained/)
- [Wyckoff Distribution Pattern: Smart Money Signals & Reversals — TrendSpider](https://trendspider.com/learning-center/chart-patterns-wyckoff-distribution/)
- [Head and Shoulders Pattern in Technical Analysis — Altrady](https://www.altrady.com/crypto-trading/technical-analysis/head-and-shoulders-chart-patterns)

**Blow-off Top / Parabolic Fade / RSI Divergence**
- [Blow-Off Top: Identifying the Indicators — GTF](https://www.gettogetherfinance.com/blog/blow-off-top-identifying-the-indicators-in-technical-analysis/)
- [Parabolic Blow-Off Top — Bearish Chart Pattern — ChartGuys](https://www.chartguys.com/chart-patterns/parabolic-blow-off-top)
- [RSI Divergence: 4 Types, Crypto Examples — Plisio](https://plisio.net/education/rsi-divergence-bullish-bearish)

**Funding Rate / Perpetual Futures**
- [Funding Rate Arbitrage Across Exchanges — Medium / Coinmonks](https://medium.com/coinmonks/funding-rate-arbitrage-across-exchanges-capturing-discrepancies-in-bitcoin-perpetuals-74970b09357f)
- [How to Analyze Funding Rates in Crypto: Complete Guide 2026 — Zipmex](https://zipmex.com/blog/how-to-analyze-funding-rates-in-crypto/)
- [Perpetual futures funding: payment frequency and trading strategies — MetaMask](https://metamask.io/news/perpetual-futures-funding-frequency-strategies)

**Long/Short Ratio (Contrarian)**
- [Long Short Ratio: Master Crypto Sentiment in 2026 — WalletFinder](https://www.walletfinder.ai/blog/long-short-ratio)
- [BTC Perpetual Futures Long/Short Ratio: A Contrarian Signal for Positioning in 2026 — Ainvest](https://www.ainvest.com/news/btc-perpetual-futures-long-short-ratio-contrarian-signal-positioning-2026-2601/)
- [Long Short Ratio — CoinGlass (live data)](https://www.coinglass.com/LongShortRatio)

**Squeeze / Liquidation Cascade / Risk**
- [How to Detect, Defend and Profit from Short Squeeze Crypto — Bitunix](https://blog.bitunix.com/en/crypto-short-squeeze-detect-defend-profit/)
- [Short Squeeze in Crypto Explained — BingX](https://bingx.com/en/learn/article/what-is-short-squeeze-in-crypto-how-liquidations-trigger-price-surge)
- [Bitcoin Futures Market Microstructure: Liquidation Cascades — XT Exchange / Medium](https://medium.com/@XT_com/bitcoin-futures-market-microstructure-liquidation-cascades-funding-regimes-and-open-interest-978b107b4889)
- [How to Predict An October 10-Style Bitcoin Crash Early — BeInCrypto](https://beincrypto.com/liquidation-cascade-onchain-technical-analysis/)

**Stan Weinstein Stage 4**
- [The Complete Guide to Stan Weinstein's Stage Analysis — TraderLion](https://traderlion.com/trading-strategies/stage-analysis/)
- [Stan Weinstein's 30-week MA — RobertBrain](https://www.robertbrain.com/technicalanalysis/weinstein.html)

**Mean Reversion / Momentum Research**
- [Systematic Crypto Trading Strategies: Momentum, Mean Reversion & Volatility Filtering — Medium](https://medium.com/@briplotnik/systematic-crypto-trading-strategies-momentum-mean-reversion-volatility-filtering-8d7da06d60ed)
- [Cryptocurrency Momentum and Reversal — Dobrynskaya, SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3913263)
- [Bitcoin Mean Reversion Strategies Outperform Momentum In Low Volume Regimes — QuantifiedStrategies](https://www.quantifiedstrategies.com/bitcoin-mean-reversion-strategies-outperform-momentum-in-low-volume-regimes/)

**Descending Triangle (S4 보조)**
- [Master the Descending Triangle Pattern in Crypto Trading — BingX](https://bingx.com/en/learn/article/how-to-trade-descending-triangle-pattern-in-crypto-market)
- [Descending triangle pattern: 78% success rate crypto guide — ChartScout](https://chartscout.io/descending-triangle-pattern-crypto)

**Pump & Dump (S5 알트 한정 위험)**
- [How to Beat Crypto Pump and Dump — Bitget Wiki](https://www.bitget.com/wiki/how-to-beat-crypto-pump-and-dump)
- [The Anatomy of a Cryptocurrency Pump-and-Dump Scheme — ResearchGate](https://www.researchgate.net/publication/329206760_The_Anatomy_of_a_Cryptocurrency_Pump-and-Dump_Scheme)
