# breakout_mtf_stack

- 생성: 2026-05-19 02:00 KST
- Group: trend_pullback
- Module: `scripts.trend_pullback.breakout_mtf_stack`
- Git: 0066b6f (main, dirty)

## 목적

[PLAN.md](../../PLAN.md) L2. 1H 강한 장대양봉 + 4 TF (1H/4H/1D/1W) MA20 stack 위 마감을 트리거로 두 진입 전략 비교:

- **A. chase_breakout** — 트리거 봉 다음 1H 봉 open 진입 (즉시 추격)
- **B. pullback_after_breakout** — 트리거 후 첫 1H MA10 풀백 시점 진입 (timeout 내 풀백 없으면 폐기)

## 파라미터 스윕

| param | sweep values | default | 의미 |
|---|---|---|---|
| `body_ret_min` | [0.01, 0.02, 0.03] | 0.02 | 1H 봉 (close-open)/open 최소 |
| `vol_ratio_min` | [1.0, 2.0] | 1.0 | 1H vol / SMA(vol,20) 최소 |
| `pullback_timeout_h` | [24, 168] | 24 | (B 만) 풀백 기다리는 최대 시간 (h) |

cooldown 24h (동일 심볼 24h 내 중복 트리거 제거).

## 방법

553 USDT-M 1H 캐시 (~5년, 2026-05-19 01h 까지). 1H MA20 = 현재봉 포함. 4H/1D/1W MA20 = 직전 완료된 higher-TF 봉의 MA (shift(1) + merge_asof backward, no lookahead).

A 진입: 트리거 봉 i 다음 1H open
B 진입: i+1..i+timeout 중 `low ≤ MA10_1h_locked ≤ high` 인 첫 봉 j 의 다음 1H open

forward returns: 4h/12h/24h/72h(3d)/168h(1w)/336h(2w)/672h(4w)

## 핵심 결과

n_events: A=**88,036**, B=**175,655** (B 가 약 2× 많은 이유: 한 트리거에서 2 timeout 모두 별도 row). cooldown 24h 적용 후 unique 트리거 = A 와 동일 ≈ 88k.

### A vs B 직접 비교 (168h = 1주 보유 기준)

**전체 데이터 (~5년)**:

| body | vol | A n | A mean | A win | B n | B mean | B win | win_diff(B-A) |
|---|---|---|---|---|---|---|---|---|
| 0.01 | 1.0 | 24,250 | +0.89% | 44.4% | 24,134 | +0.95% | 44.7% | +0.31pp |
| 0.02 | 1.0 | 15,824 | **+1.11%** | 43.8% | 15,739 | **+1.15%** | **44.5%** | +0.64pp |
| 0.02 | 2.0 | 11,718 | +0.99% | 43.4% | 11,641 | +0.94% | 44.1% | +0.73pp |
| 0.03 | 1.0 | 9,961 | +1.21% | 43.2% | 9,903 | +1.15% | 43.7% | +0.41pp |
| 0.03 | 2.0 | 7,925 | +1.09% | 42.5% | 7,871 | +0.98% | 43.3% | +0.75pp |

**2025+ 슬라이스 (~1.5년)**:

| body | vol | A n | A mean | A win | B n | B mean | B win | win_diff(B-A) |
|---|---|---|---|---|---|---|---|---|
| 0.01 | 1.0 | 11,636 | -2.64% | 34.6% | 11,570 | -2.61% | 34.9% | +0.35pp |
| 0.02 | 1.0 | 7,552 | -2.30% | 34.9% | 7,504 | -2.32% | **35.7%** | +0.73pp |
| 0.02 | 2.0 | 5,670 | -2.32% | 34.8% | 5,626 | -2.26% | 35.8% | +1.02pp |
| 0.03 | 1.0 | 4,878 | -2.13% | 34.9% | 4,850 | -2.16% | 35.8% | +0.90pp |
| 0.03 | 2.0 | 3,942 | -2.24% | 34.3% | 3,912 | -2.15% | 35.5% | +1.18pp |

→ **B 가 A 보다 168h win 약 +0.5~+1.2pp 일관 우위**, 그러나 둘 다 절대 win < 45% (전체) / < 36% (2025+). 매수 우위라기보다 동전 살짝 아래.

### A 호라이즌 곡선 (body=0.02 vol=1.0)

**전체 데이터**:

| 보유 | n | mean | median | win |
|---|---|---|---|---|
| 4h | 16065 | -0.01% | -0.36% | 44.9% |
| 24h | 16044 | -0.10% | -1.06% | 43.5% |
| 72h | 16009 | +0.29% | -1.44% | 43.8% |
| **168h** | 15824 | +1.11% | -2.46% | 43.8% |
| 672h | 14802 | +3.56% | -7.70% | 39.7% |

**2025+ 슬라이스**:

| 보유 | n | mean | median | win |
|---|---|---|---|---|
| 4h | 7793 | +0.05% | -0.30% | 45.7% |
| 24h | 7772 | -0.63% | -1.36% | 41.0% |
| 168h | 7552 | -2.30% | -5.69% | 34.9% |
| 672h | 6530 | -4.40% | -13.4% | 28.4% |

### B 호라이즌 곡선 (body=0.02 vol=1.0 timeout=24h)

**전체 데이터**:

| 보유 | n | mean | median | win |
|---|---|---|---|---|
| **4h** | 15988 | +0.07% | -0.05% | **49.0%** |
| 12h | 15985 | +0.19% | -0.27% | 46.9% |
| 24h | 15975 | +0.09% | -0.70% | 44.6% |
| 168h | 15739 | +1.15% | -2.18% | 44.5% |
| 672h | 14732 | +3.48% | -7.52% | 39.6% |

**2025+ 슬라이스**:

| 보유 | n | mean | median | win |
|---|---|---|---|---|
| **4h** | 7753 | -0.01% | -0.11% | **47.8%** |
| 24h | 7740 | -0.50% | -1.13% | 41.4% |
| 168h | 7504 | -2.32% | -5.59% | 35.7% |
| 672h | 6497 | -4.47% | -13.2% | 28.3% |

→ B 의 단기 (4h) win 약 49% 가 모든 슬라이스 중 최고. 1주 이상 보유는 어느 슬라이스도 50% 못 미침.

### Sweep axis 효과 (모두 약함)

- `body_ret_min` 1→3% 늘리면 표본 60% 감소, win 약간 ↓, mean 약간 ↑. 강한 양봉만 잡아도 우위 안 생김.
- `vol_ratio_min` 1→2 늘리면 표본 25% 감소, 결과 거의 변함 없음. 거래량 spike 단독 필터 효과 없음.
- `pullback_timeout_h` 24 vs 168: **거의 동일** (almost all pullbacks 24h 안에 발생) → 더 짧게 (e.g. 6h, 12h) sweep 해서 차이 보는 게 의미 있을 듯.

## 시사점

1. **MTF MA20 stack 단독 게이트는 약함**. 이미 4 TF 모두 정배열인 상태는 추세 후반부에 가까워 평균회귀 가능성 ↑. 5년치 전체 데이터 168h win 44% — 동전보다 약간 아래.
2. **B (pullback) 가 A (chase) 보다 일관 우위지만 차이 +0.5~+1.2pp 로 작음**. 두 전략 모두 50% win 못 넘음. 단기 (4h) 만 B 가 49% 가까이 도달.
3. **2025+ 환경에서 두 전략 모두 명백히 음수** (mean -2~-4%, win 35% 전후). 알트 약세장에서는 어느 진입 룰이든 추세 추종 매수가 작동 X.
4. **추가 게이트 필요**:
   - 사전 하락이 충분히 있었던 종목만 (= bottom reversal 컨디션)
   - BTC slope_up regime 필터
   - 트리거 봉이 직전 N시간 고점 (e.g. 24h high) 돌파인지
   - 트리거 봉 자체가 단일 24h 변동성의 X배 이상인지 (단순 body% 가 아니라 z-score)
5. **timeout sweep 더 짧게**: 24h 와 168h 차이 없음 → 풀백은 거의 다 24h 안. 6h / 12h / 24h sweep 으로 좁힐 가치.

## 차트

`B_2025_top_bot_grid.png` — best combo (B, body=0.02 vol=1.0 timeout=24h, 2025+) 의 **168h 기준 TOP 20 winner + BOT 20 loser**. 5×8 grid, 1H OHLC + 4개 MA20 line (1H 파랑, 4H 주황 점선, 1D 녹색 점, 1W 보라 점선).

상단 4행 (winners): 트리거 후 풀백 → 강한 반등으로 1주 동안 +30% 이상 상승 패턴. 트리거 직전이 베이스/풀백의 끝이었던 경우.
하단 4행 (losers): 트리거 후 짧은 반등 후 곧바로 폭락. 트리거 봉 자체가 단기 정점이었던 케이스 — "stack 정렬 = trend mature = exhaustion 직전" 의 전형.

## 산출물

| 파일 | 크기 | 설명 |
|---|---|---|
| `output/events_A.parquet` | ~ | 88,036 A events (모든 combo) |
| `output/events_B.parquet` | ~ | 175,655 B events (모든 combo × timeout) |
| `output/events_A_2025plus.parquet` | ~ | A 2025+ subset (43,198) |
| `output/events_B_2025plus.parquet` | ~ | B 2025+ subset (86,216) |
| `output/sweep_A_overall.csv` | ~ | combo × horizon long |
| `output/sweep_B_overall.csv` | ~ | combo × horizon long |
| `output/sweep_A_body.csv` / `_vol.csv` | ~ | A marginal wide |
| `output/sweep_B_body.csv` / `_vol.csv` / `_timeout.csv` | ~ | B marginal wide |
| `output/sweep_A_all_long.csv` / `_2025_long.csv` | ~ | A all-period / 2025+ long table |
| `output/sweep_B_all_long.csv` / `_2025_long.csv` | ~ | B all-period / 2025+ long table |
| `output/B_2025_top_bot_20.csv` | ~ | best combo top 20 winner + bot 20 loser metadata |
| `output/B_2025_top_bot_grid.png` | 0.9MB | 위 40 events 의 1H 차트 그리드 |

## 재현

`REPRODUCE.md` 참조.
