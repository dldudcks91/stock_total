# crypto_baseline (MA20w slope<0 short)

- 생성: 2026-05-18 21:40 KST
- Group: ma20w_short
- Module: `scripts.ma20w_short.baseline`
- Git: d1ff82d (main, **dirty** — 정확한 재현 보장 X. 커밋 후 재실행 권장)
- Finalized: 2026-05-18 23:35 KST

## 목적
주봉 MA20 의 **기울기(slope_4w)가 음수** 일 때 숏을 진입하는 전략의 베이스라인 성과를 확인한다.
- 가설: MA20w 하락 추세(slope_4w < 0) 구간은 통계적으로 음의 forward return 을 보여 단순 게이트만으로도 양의 숏 기대값.
- 자산: **숏 가능한 crypto (Bitget USDT-M)** 한정. KR/US 주식은 숏 제도 제약으로 1차 범위에서 제외.

## 정의
- `MA20w(t) = close.rolling(20, weekly).mean()`
- `slope_4w(t) = MA20w[t] / MA20w[t-4] - 1` (정규화 4주 차분, 단위: 비율)
- 진입 신호: `slope_4w(t) < 0`
- 진입 체결: 다음 주(`t+1`) 시가 (open) 숏
- 청산 신호: `slope_4w(t) ≥ 0`
- 청산 체결: 다음 주(`t+1`) 시가 (open)
- 룩어헤드 금지 (시그널 t 종가 → t+1 시가 체결)

## 방법
1. 데이터: `data/cache/crypto/1d/*.parquet` → `data.resample.load(symbol, "1w")` 로 W-MON 리샘플 (553 심볼)
2. 위 정의로 진입/청산 이벤트 추출, 트레이드 단위 short return 계산:
   - `trade_return = (entry_open - exit_open) / entry_open - fees`
3. 수수료/슬리피지: 라운드트립 15bps (entry 5 + exit 5 + slip 5). funding 비용은 Layer 1 이후 보강.
4. 4-group 분류 (`data/cache/crypto/classification.parquet`, 컬럼 `tier_final`) 별 분해 — trend / follower / whale / junk 중 어디서 숏 우위가 가장 강한지 확인

## 평가 지표 (PLAN ①~⑤)
| # | 기준 | 임계 |
|---|---|---|
| ① mean | 평균 short return | > 0 |
| ② win_rate | 승률 | ≥ 50% |
| ③ payoff | 평균이익 / 평균손실 | ≥ 1.0 |
| ④ var95 | 5th percentile (개별 트레이드) | 작을수록 좋음 (핵심) |
| ⑤ n_trades | 표본 크기 | ≥ 50 |

랭킹은 **VaR-adjusted expectancy = mean − 1.65 × std**.

## 핵심 결과

> 아래 표·해석은 1차 자동 작성된 초안입니다. PLAN ①~⑤ 판정과 다음 액션은 사용자가 검토·확정해 주세요 (스킬 명세: 핵심 결과 섹션은 자동 채움 X 권장).

### Overall (553 심볼 중 424 처리, 122 스킵 — 데이터 부족)
| 메트릭 | 값 | 판정 |
|---|---|---|
| n_trades | 1,173 | OK (≥ 50) |
| mean (short return / trade) | **−0.49%** | ① 음수 → 불합격 |
| median | +1.13% | — |
| std | 57.4% | 매우 큼 |
| win_rate | **51.0%** | ② 통과 |
| payoff (avg_win / |avg_loss|) | **0.94** | ③ 불합격 |
| VaR95 (트레이드 5th %ile) | **−92.9%** | ④ 매우 나쁨 |
| max_loss (single trade) | **−428.7%** | 가격 5배 폭등 동안 미청산 |
| VaR-adj expectancy (mean − 1.65σ) | **−95.2%** | 폐기권장 |
| avg_hold_weeks | 21.3주 | 청산 게이트가 늦음 |
| total_pnl (unit notional sum) | −5.78 | 음의 합 |

→ **단순 게이트(`slope_4w<0` → `slope_4w≥0`) 만으로는 ①·③·④ 불합격**. PLAN 의 폐기 조건에 해당.

### By tier (4-group classification)
| tier | n_trades | n_symbols | mean | win_rate | payoff | VaR95 | VaR-adj exp | hold(w) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| benchmark (BTC) | 9 | 1 | −23.3% | 22% | 0.71 | −71% | −83% | 15.3 |
| **follower** | 379 | 93 | **+4.3%** | 54% | 1.04 | −76% | −79% | 24.4 |
| junk | 231 | 174 | −3.9% | 56% | 0.66 | −109% | −120% | 15.6 |
| stable | 9 | 1 | −0.2% | 0% | 0.00 | 0% | 0% | 7.4 |
| trend | 461 | 125 | −2.6% | 46% | 1.02 | −95% | −94% | 22.0 |
| whale | 84 | 30 | +1.4% | 56% | 0.83 | −100% | −104% | 21.9 |

### 해석
1. **전체 평균은 사실상 0** — 단순 slope_4w 게이트만으로는 숏 우위 없음 (PLAN ① 실패).
2. **follower** (BTC 추종형 중·소형코인 93개) 만 평균 +4.3% 로 미세한 우위. 이 그룹에서는 Layer 1 진입 그리드가 가치 있을 가능성.
3. **trend / junk / benchmark** 는 음의 평균 — 추세 코인은 미청산 동안 가격 폭등 사례(max_loss −428%)가 평균을 압도. **청산 게이트가 너무 늦다** (평균 보유 21주).
4. **VaR95 가 모든 tier 에서 −70%~−109%** — 청산 룰만으로는 꼬리 위험 통제 불가. Layer 2 의 SL/TP 가 필수.

### 다음 액션 (PLAN Layer 1·2 분기)
- **Layer 1 (entry grid)** 은 **follower 단독** 또는 **follower + (trend/whale에 추가 필터)** 로 좁혀서 진행. 전체 풀로 그리드 돌려도 노이즈만 늘 가능성.
- **Layer 2 (exit grid)** 가 더 시급. 고정 보유 {2,4,6,8,12}주 / SL +5% / TP −20% 등으로 평균 보유 21주를 단축, max_loss 꼬리부터 컷.
- PLAN 폐기 조건 ("전체/그룹 모두 평균 기대값 ≤ 0") 은 **부분 미달** — 전체는 ≤0 이나 follower 가 양수라 가설 완전 폐기는 아님. **게이트 자체보단 청산이 문제**라는 진단.

## 산출물

| 파일 | 크기 | 설명 |
|---|---:|---|
| `output/trades.parquet` | 63.6 KB | 트레이드 1,173 건. 컬럼: symbol, tier, entry_idx, exit_idx, entry_dt, exit_dt, entry_open, exit_open, hold_weeks, gross_ret, fees_ret, funding_ret, net_ret |
| `output/summary.json` | 4.0 KB | overall 메트릭 + by_tier 리스트 + 사용 params |
| `output/summary_by_tier.csv` | 1.6 KB | tier 별 (benchmark/follower/junk/stable/trend/whale) ①~⑤ + VaR-adj exp + 평균 보유주수 |

## 재현
`REPRODUCE.md` 참조.
