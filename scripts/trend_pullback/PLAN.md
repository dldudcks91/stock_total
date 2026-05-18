# trend_pullback 연구 계획

> 위치: `scripts/trend_pullback/PLAN.md`
> 작성: 2026-05-18 KST · 마스터 플랜 (모든 후속 run 의 상위 계약)

## 0. 큰 질문

"**1W MA20 slope > 0** 게이트 안에서, 어떤 진입/확인 룰이 자동매매 가능한 edge 를 만드는가?"

조작적 정의 — 어떤 룰(cell) 이 "통과" 하려면 다음 모두를 동시 만족:

| # | 기준 | 임계 |
|---|---|---|
| ① | 평균 기대값 | 168h 또는 672h 기준 `mean > 0` |
| ② | 승률 | `win ≥ 50%` |
| ③ | VaR-adj. expectancy | `mean − 1.65 × std > 0` (개별 트레이드 좌측 꼬리 컨트롤) |
| ④ | 표본 크기 | cell 별 `n ≥ 100` (충족 못 하면 폐기) |
| ⑤ | baseline 대비 개선 | 단순 retest baseline (win 32~33%) 대비 **+5pp 이상** 개선 |

랭킹은 단일 메트릭이 아니라 **VaR-adj. expectancy** 로. "평균은 좋은데 가끔 -50% 맞는 룰" 을 거르기 위해서.

## 1. Run 구조 (Layer)

### L0 — 베이스라인 (완료)

이미 3개 sub-run 으로 분리해 끝냄. 이 PLAN.md 는 retro-fit 으로 묶어둠.

- **L0a `20260518-2115_baseline_1W_slope_imp7_vol5x`** — slope>0 + 1H 임펄스 7% + vol 5× 강한 모멘텀 트리거. 168h win **37~44%** (bars 4-6 best 44%). 강한 모멘텀 트리거의 존재로 retest 류와 비교 기준 마련.
- **L0b `20260518-2140_1W_ma20_touch_slope_up`** — 주봉 단순 retest. 4w win **33.5%**, 24w win 23.9%. 가설 부분 기각: 단순 weekly retest 는 edge 없음.
- **L0c `20260518-2147_1H_touch_1W_ma20_slope_up`** — 1H 인트라위크 retest. 4w win **32.5%**. 표본 2.3× 늘었으나 win 더 낮음. weekly close 회복 케이스 추가가 우위 시그널 X 확인.

→ **결론**: 단순 retest 자동매매 불가. **확인봉(t+1)** 의 모멘텀/볼륨 조건을 추가해 sub-cell 우위가 있는지 본다.

### L0d — slope cross-up 이벤트 스터디 (완료)

목적: 가격 조건 없이 **"1W MA20 기울기가 ≤0 → >0 로 바뀌는 순간"** 만 트리거. 그 시점에 진입했을 때 1d ~ 8w 까지 일봉 종가 수익률 곡선 분포. 추세 회귀 자체에 edge 가 있는지 답 (price-action 빼고 순수 게이트 효과 측정).

- 트리거: `MA20[W] − MA20[W-1] > 0` AND `MA20[W-1] − MA20[W-2] ≤ 0` (strict cross-up)
- 진입: 주 W 종가 확정 후 첫 1D 봉 open
- 호라이즌: **1, 2, 3, 4, 5, 6, 7d, 14, 21, 28, 35, 42, 49, 56d** (1~7일 + 1~8주)
- 자산: Bitget USDT-M 553 종목, 1D 캐시 (1H→1D 리샘플)

### L2 — 1H 장대양봉 + 4MA stack breakout 진입 (진행 중)

목적: 다중 타임프레임 MA 정배열 상태에서 강한 1H 장대양봉이 신호를 만들 때 추격 vs 눌림목 두 전략 비교.

**공통 트리거 (T)**: 1H 봉 close 가 1H/4H/1D/1W MA20 4개 모두 위 + body_ret ≥ 임계 + vol_ratio ≥ 임계

**A. `chase_breakout`** — T 봉의 다음 1H 봉 open 진입 (즉시 추격)
**B. `pullback_after_breakout`** — T 발생 후 `low ≤ 1H_MA10` 인 첫 봉 찾으면 다음 봉 open 진입. timeout 내 없으면 폐기

forward horizons: 4h, 12h, 24h, 72h(3d), 168h(1w), 336h(2w), 672h(4w)

자산: Bitget USDT-M 553 종목, 1H 캐시 (방금 업데이트 2026-05-19 01h KST 까지)

게이트/lookahead: 1H MA20 은 close[i] 포함 (당해 봉 종가 검사). 4H/1D/1W MA20 은 직전 완료된 higher-TF 봉의 값 (shift(1) + merge_asof backward) — lookahead 방지.

### L3 — 매집봉 vs 추세지속 분류 (진행 중)

목적: L2 결과에서 본 "강한 양봉 + 4MA stack" 트리거가 winner/loser 거의 5:5 로 갈리는 문제 해결. 트리거 시점/직전/직후 feature 로 매집봉(false breakout, distribution) vs 추세지속(real continuation) 을 사후 분리할 discriminator 찾기.

**입력**: `runs/20260519-0300_strong_breakout/output/events_B.parquet` 의 body=0.03 vol=3.0 timeout=24h subset (n≈6,210 all-years).

**feature 그룹**:
- **A (트리거 봉 구조, no-lookahead)**: upper_wick_ratio, body_to_range, lower_wick_ratio, close_to_high_pct
- **B (트리거 직전 컨텍스트, no-lookahead)**: vs_24h_high_pct, pre_24h_range_pct, pre_consec_up_h, pre_vol_quiet_ratio, vs_72h_low_pct
- **C (트리거 직후 confirmation, 4h 지연 진입)**: next_4h_held (모든 low ≥ trigger low), next_4h_max_close, next_4h_avg_vol_ratio, next_4h_body_sum

**분석**:
1. 각 feature 5분위 → 168h 보유 win/mean
2. winner (fwd_ret_168h > +5%) vs loser (< -5%) 그룹 평균 feature 값 비교
3. 상위 2~3개 discriminator 결합 grid

### L0e — slope cross-up + 첫 MA10 터치 진입 (진행 중)

목적: L0d 에서 발견된 패턴 (cross-up 직진입은 단기 음수, retouch 시 14d 단기 우위) 의 진화 — **MA20 slope 양으로 돌아간 후 첫 주봉 MA10 터치 시점 매수**. MA10 은 MA20 보다 가격에 가까워 touch 빈도 높고 더 빠른 진입 가능.

- 게이트: `MA20[W] > MA20[W-1]` AND `MA20[W-1] ≤ MA20[W-2]` (1W MA20 slope cross-up, strict)
- 트리거: cross-up 확정 후 (= 주 W+1 부터) 1D 봉 중 `low ≤ MA10_locked ≤ high` 인 **첫 봉**
- 진입: 그 1D 봉의 다음 1D open (no lookahead)
- 호라이즌: 1, 2, 3, 4, 5, 6, 7d, 14, 21, 28, 35, 42, 49, 56d
- 자산: Bitget USDT-M 553 종목, 1D 캐시 (방금 업데이트, 2026-05-17 까지)

### L1 — 확인봉 grid (다음, 이 run)

`retest_confirm_grid`. L0c 의 1H touch event 골격 위에:

- **확인봉 = touch 봉의 다음 1H 봉 (i+1)**, 진입 = i+2 open (no lookahead — 확인봉이 close 된 후 진입)
- 확인봉에서 측정할 feature:
  - `body_ret` = `(close[i+1] − open[i+1]) / open[i+1]` (양봉/음봉 + 강도)
  - `color` = `close[i+1] > open[i+1]` (양봉 boolean)
  - `vol_ratio` = `volume[i+1] / SMA(volume, 20)[i]` (룩어헤드 방지: i 시점까지 평균만 사용)
  - `up_wick_ratio` = `(high[i+1] − max(open, close)) / (high − low)`
  - `low_wick_ratio` = `(min(open, close) − low[i+1]) / (high − low)`
  - `rsi14` at i+1 (1H, Wilders)
  - `touch_depth` = `(MA20_locked − low[i]) / MA20_locked` (얼마나 깊이 빠졌나 — touch 봉 기준)
- 분석:
  - 각 feature 당 quintile (5분위) → cell 별 n / mean / median / std / win / VaR-adj at 168h / 672h
  - body_ret × vol_ratio 2D grid (5×5)
  - body_ret × touch_depth 2D grid (5×5)
- 출력:
  - `output/events_confirm.parquet` — events + feature + 재진입 forward returns
  - `output/grid_1d.csv` — 각 feature 1D quintile 표
  - `output/grid_body_vol.csv` — 2D grid (body × vol)
  - `output/grid_body_depth.csv` — 2D grid (body × touch_depth)
- 판정: 어느 한 cell 이라도 ①~⑤ 통과하면 L2 로 진입. 못 하면 트리거 자체 폐기.

### L2~ (이후, 결과 보고 결정)

L1 통과 cell 발견 시에만 진행. 후보:
- L2 `entry_combo` — L1 top-K 의 2-way 조합 + slope_accel(MA20 2차 미분 양)
- L3 `exit_grid` — TP/SL/trailing
- L4 `oos` — IS 2020–2023 / OOS 2024–2026
- L5 `stability` — 4-group classification × top 룰, per-symbol expectancy 분포

이 단계들은 L1 결과 확인 후 본 PLAN 에 보강해 진행.

## 2. 파라미터 스윕 매트릭스

모든 결정 변수는 단일 값이 아니라 sweep 비교. 결과는 sweep 행 단위 표.

| Layer | param | sweep values | default | 의미 |
|---|---|---|---|---|
| L0d | `horizon_days` | [1,2,3,4,5,6,7, 14,21,28,35,42,49,56] | — | forward 수익률 측정점 (sweep 자체가 핵심 axis, default 없음) |
| L0e | `ma_short_period` | [5, 10, 15] | 10 | 첫 터치 대상 주봉 MA 길이 |
| L0e | `gate_strict` | [True, False] | True | True=cross-up (slope 막 양으로 돈 시점) / False=slope_up 유지중 어디든 |
| L2(공통) | `body_ret_min` | [0.01, 0.02, 0.03] | 0.02 | 1H 양봉 body 최소 (%, 1H scale) |
| L2(공통) | `vol_ratio_min` | [1.0, 2.0] | 1.0 | 1H vol / SMA20(vol) 최소 |
| L2b only | `pullback_timeout_h` | [24, 168] | 24 | 풀백 기다리는 최대 시간 (h) |
| L2b only | `pullback_target` | ['1h_MA10'] | '1h_MA10' | 풀백 도달 기준 (현재 1H MA10 한정) |
| L3 | `n_quantiles` | [5] | 5 | feature 5분위 |
| L3 | `winner_threshold_pct` | [+0.05] | +0.05 | winner 라벨 (fwd_ret_168h > X) |
| L3 | `loser_threshold_pct` | [-0.05] | -0.05 | loser 라벨 (fwd_ret_168h < X) |
| L3 | `post_confirm_bars` | [4, 8] | 4 | C 그룹 confirmation 윈도우 (1H 봉 단위) |
| L1 | `ma_period_weekly` | [10, 20, 30, 50] | 20 | 게이트 1W MA 길이 |
| L1 | `confirm_offset` | [1, 2, 3] | 1 | touch 봉(i) 으로부터 확인봉 거리 (시간). entry = i+offset+1 open |
| L1 | `vol_sma_period` | [10, 20, 50] | 20 | 확인봉 volume 정규화 분모 길이 |
| L1 | `rsi_period` | [7, 14, 21] | 14 | 확인봉 RSI 길이 |

기본 정책: **marginal sweep** — 각 param 만 변화시키고 나머지는 default 고정. 4 + 3 + 3 + 3 − 4 = 9 unique 조합 (default point 1 + 각 axis non-default 합).

추가 sub-cell grid (위 sweep 과 별개):
- 확인봉 feature 의 5분위 (`n_quantiles=5`) 또는 3분위 — quintile 자체도 sweep param `[3, 5]` 으로 비교.

## 3. 데이터 / 표본 가드

| 항목 | 값 |
|---|---|
| 데이터 범위 | 1H 캐시 시작 (~2020) ~ 2026-05 |
| 자산 | crypto 만 (553 USDT-M) |
| 인터벌 | 1H trigger + 1W MA20 (locked from prev week) |
| 룩어헤드 | MA20·slope locked from prev week. vol_ratio 분모는 i 시점까지 평균. 확인봉 close 본 뒤 i+2 open 진입. |
| 수수료/슬리피지 | 0 (분석용 raw return) — L3 에서 추가 |
| 최소 표본 | cell 별 `n ≥ 100` |
| 생존편향 | 현재 살아있는 심볼만 (1차 한계, 폐지 심볼 보강은 별도) |

## 4. 폐기 조건

- L1: 5분위 어느 cell 도 ①~⑤ 동시 충족 못 함 → "slope_up + retest + 확인봉" 가설 폐기, 다른 게이트 (e.g. 가격액션 + 펀더멘털) 로 전환.
- L4 (OOS): IS 대비 Sharpe < 50% → 과적합, 폐기.

## 5. 다음 즉시 액션

1. `/study init trend_pullback retest_confirm_grid`
2. `scripts/trend_pullback/retest_confirm_grid.py` 모듈 작성
3. 실행 → `output/` 결과
4. `/study finalize`
5. README "핵심 결과" 손으로 채움 → L2 진행 여부 판정
