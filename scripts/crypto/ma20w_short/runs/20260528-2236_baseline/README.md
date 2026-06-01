# baseline

- 생성: 2026-05-28T22:36:56+09:00 (KST)
- Group: crypto/ma20w_short
- Module: `scripts.crypto.ma20w_short.baseline`
- Git: d1d7cbb (main, **dirty** — finalize 시 재현성 경고)

## 목적

[PLAN.md](../../PLAN.md) Layer 0 — **MA20w 터치 숏 가설의 sanity check**.
무필터 진입 룰 (다운트렌드 게이트 + 직전 완성 주봉 MA20w 일봉 터치) + 단순 청산
(`close_1d ≥ MA20w`) 으로 4 그룹별 평균 expectancy 부호를 확인.

음수면 가설 자체 폐기. 양수면 Layer 1 (`exit_grid`, 640 조합) 로 진입.

## 파라미터 스윕

baseline 은 **단일 청산 룰** 의 sanity check 이므로 exit 스윕 X.
대신 그룹 축을 비교 단위로 사용.

| param | sweep values | default |
|---|---|---|
| `group` | [trend, follower, whale, junk] | (모두) |
| `exit_rule` | `close_1d ≥ MA20w` | (고정) |

(스윕은 Layer 1 `exit_grid` run 에서 풀 그리드)

## 방법

### 게이트
- `close_1w(t) < MA20w(t)` AND `slope_4w(t) = MA20w[t]/MA20w[t-4] − 1 < 0`

### 진입
- 게이트 만족한 주봉의 직후 주차 동안, 일봉 high ≥ MA20w(직전 완성 주봉) 인 첫 일봉
- 진입가 = MA20w 지정가 (intraday touch 시 그 가격으로 체결)
- 종목당 포지션 1개, 청산 후 4주 쿨다운

### 청산
- 일봉 종가 ≥ MA20w(현재 진입 시점의 MA20w 고정값) 시 다음 일봉 시가 청산
- 강제 청산 없음 (트레일/TP/Stop/Hold cap 전부 X)

### 비용
- 진입 5bps + 청산 5bps + 슬리피지 5bps = 라운드트립 15bps
- Funding cost 제외

## 핵심 결과

### 그룹별 baseline (single-exit) 성능

| group    | n_sym | n_trades | mean_ret | median_ret | win_rate | payoff | var_adj_ex | mdd     | sharpe | avg_hold(d) |
|----------|-------|----------|----------|------------|----------|--------|------------|---------|--------|-------------|
| trend    | 124   | 682      | +0.09%   | −1.90%     | 26.8%    | 2.78   | −28.79%    | −100.1% | 0.02   | 17.5        |
| follower | 93    | 606      | +1.33%   | −1.42%     | 29.2%    | 3.32   | −25.82%    | −100.0% | 0.29   | 19.4        |
| whale    | 30    | 131      | +2.39%   | −0.94%     | 38.9%    | 2.39   | −30.00%    | −93.6%  | 0.40   | 23.2        |
| junk     | 37    | 106      | +3.60%   | −2.54%     | 31.1%    | 3.49   | −40.83%    | −99.4%  | 0.38   | 30.9        |
| **ALL**  | 284   | 1525     | +1.03%   | −1.73%     | 29.1%    | 3.03   | −28.87%    | −101.6% | 0.20   | 19.7        |

### 판정

- ① mean > 0 : ✅ **모든 그룹 통과** (trend +0.09% 가 최소)
- ② win_rate ≥ 45% : ❌ 전부 미달 (27~39%) — payoff 가 받쳐주지만 짧은 손실/긴 이익 구조
- ③ payoff ≥ 1.0 : ✅ 전부 통과 (2.38~3.49)
- ④ var_adj_ex > 0 : ❌ **전부 음수** — 표준편차가 평균의 17~20배라 변동성 페널티 후 손실. squeeze 위험 큼
- ⑤ n_trades ≥ 50 : ✅ 전부 통과
- **폐기 조건 (전 그룹 mean ≤ 0): 미발동** → Layer 1 (`exit_grid`) 진행 가능

### 메모 (Layer 1 진입 전 가설)

- median 이 전 그룹 음수 → **트레이드 절반 이상이 손실**. mean 을 끌어올리는 건 소수 대박. **TP / trail 로 대박을 안정화** 하면 var_adj 가 양수로 갈 가능성
- MDD −100% 는 equity 계산 시 trade-by-trade compounding + 100% 풀비중 가정 결과 (분산 미반영). 실전은 한 종목당 0.5~5% 비중이라 실제 MDD 는 훨씬 작음
- **whale 그룹이 가장 매력적** (sharpe 0.40, win_rate 39%) → 분산이 적고 일관됨. junk 는 mean 최대지만 var_adj 도 최악 (-41%) — 변동성 폭증
- Layer 1 그리드의 핵심 가설: **Stop = "MA20w 위 0~5%" 손절 / TP = "−15~−40%" 익절 / Hold = 1~10w 제한** 중 어떤 조합이 var_adj 를 양수로 끌어올리나

## 산출물

| 파일 | 크기 | 설명 |
|---|---|---|
| `output/summary.json` | 2.4 KB | params + 그룹별 핵심 메트릭 JSON |
| `output/summary_by_group.csv` | 1.1 KB | 그룹×지표 wide 표 (위 핵심 결과 표의 source) |
| `output/trades.parquet` | 75.6 KB | 전체 1525 trades raw (symbol/group/entry/exit/ret_gross/ret_net/holding_days/exit_reason) |

## 재현

`REPRODUCE.md` 참조.
