---
name: crypto-classify
description: BTC를 벤치마크로 두고 캐시의 모든 코인을 4그룹(trend / follower / whale / junk)으로 분류한다. 내부적으로 7-way 룰+kmeans 결과(tier_detail)도 함께 저장. 트리거 `/crypto-classify`. 인자가 없으면 기본값(--start 2023-01-01 --end 2025-12-31 --method both)으로 실행하고 `data/cache/crypto/classification.parquet`에 저장. 분기마다 또는 신규 심볼이 다수 추가되었을 때 재실행 권장.
---

# /crypto-classify

캐시(`data/cache/crypto/1h/{SYMBOL}.parquet`)의 모든 심볼에 대해 일봉 기준 6개 메트릭을 계산하고 두 가지 방식(rules / kmeans)으로 분류한다.

## 실행

기본 실행:

```bash
.venv/Scripts/python.exe -m data.classification
```

옵션:

```bash
.venv/Scripts/python.exe -m data.classification \
  --start 2023-01-01 --end 2025-12-31 \
  --method both \                # rules | kmeans | both (기본 both)
  --btc-symbol BTCUSDT \
  --out data/cache/crypto/classification.parquet \
  [--symbol BTCUSDT --symbol ETHUSDT]   # 명시 심볼 (반복) — 미지정 시 캐시 전체
```

성공 시 stdout에 `saved: ... (N symbols)` 와 `tier_final` 분포가 출력된다. 캐시가 비어있거나 BTCUSDT가 없으면 친절한 안내와 함께 종료 코드 2.

## 산출물 (`data/cache/crypto/classification.parquet`)

컬럼: `symbol, tier_final, tier_detail, tier_rule, tier_kmeans, r2_btc, beta_btc, hurst, kurtosis, kurt_trimmed, pump_count_per_year, pump_recurrence, realized_vol_annual, volume_score_3y, listing_days, last_price, max_drawdown_3y, classified_at, n_obs`

- `tier_final`: **사용자 노출용 4그룹** (trend / follower / whale / junk + benchmark + stable)
- `tier_detail`: 내부 7-way (leader / co_leader / beta_follower / whale_driven / pump_dump / unclassified_new / mixed) — 어떤 신호로 분류됐는지 추적용
- `tier_rule` / `tier_kmeans`: 룰·kmeans 각각의 raw 결과

## 최종 4그룹 (tier_final)

| 그룹 | 의미 | 포함되는 detail | 추천 전략 |
|---|---|---|---|
| **trend** (추세형) | 자기 시장 가진 메이저 — 자기 추세 또는 거래량 압도적 | leader, co_leader | 트렌드 추종 — SMA cross, Donchian breakout |
| **follower** (추종형) | BTC와 강하게 동조 (R²>0.6, β>1) | beta_follower | BTC 신호 활용, 단순 베타 추적 |
| **whale** (세력형) | 적당한 두꺼운 꼬리(8≤kurt_t<20) + 펌프 빈도 | whale_driven | 평균회귀 + 트렌드 필터, 펌프 후 fade |
| **junk** (잡코인) | 진짜 주작 + 신규 미검증 + 분류 불가 | pump_dump, unclassified_new, mixed | 백테스트 유니버스에서 제외 권장 |
| `benchmark` | BTCUSDT 자체 | — | — |
| `stable` | 연 변동성 < 5% | — | — |

## 내부 7-way 세부 분류 (tier_detail)

| detail | 룰 조건 |
|---|---|
| `pump_dump` | kurt_trimmed > 20 AND pump_recurrence > 0.3 (반복 펌프) |
| `co_leader` | 0.5 ≤ R² ≤ 0.75 AND 거래량 상위 5% AND kurt_trimmed < 10 |
| `leader` | R² < 0.5 AND Hurst > 0.55 AND kurt_trimmed < 8 AND 거래량 상위 30% |
| `beta_follower` | R² > 0.6 AND β > 1.0 AND kurt_trimmed < 8 |
| `whale_driven` | 8 ≤ kurt_trimmed < 20 AND pump_count > 2 |
| `unclassified_new` | listing_days < 365 |
| `stable` | realized_vol < 0.05 |
| `mixed` | 어느 룰도 안 걸림 → kmeans로 fallback |

## 메트릭 정의

- **R²_btc**: `corr(daily_ret, btc_daily_ret)²`
- **beta_btc**: `cov(coin, btc) / var(btc)`
- **hurst**: R/S 분석, 시차 [10, 20, 40, 80, 160]
- **kurtosis**: Pearson(=Fisher False) 4차 모먼트, 정규분포 ≈ 3
- **kurt_trimmed**: 양극단 0.5%씩 윈저화 후 kurtosis (단발 outlier 제거)
- **pump_count_per_year**: `(|z|>5).sum() / years`
- **pump_recurrence**: `|z|>5` 이벤트가 분포된 분기 비율 (0~1). 단발 충격은 낮고, 반복 펌프는 높음.
- **realized_vol_annual**: `daily_ret.std() * sqrt(365)`

## 주의

- `listing_days`는 **Bitget 캐시의 데이터 보유 일수**이지 코인 자체 나이가 아님 (예: ZEC는 2016년 코인이지만 Bitget이 최근에 상장하면 listing_days가 작게 나옴).
- 4그룹 매핑은 `data.classification.GROUP4_MAP` 에 정의됨.

## 재실행 권장 주기

- 분기마다 (3개월에 1회) 정기 재실행
- 신규 심볼이 캐시에 50개 이상 추가되었을 때
- 큰 시장 레짐 전환(BTC ATH 갱신, 대형 청산) 직후

## 주의

- BTCUSDT 1h 캐시가 반드시 존재해야 함.
- 일부 심볼이 캐시에 없어도 동작 (스킵).
- 출력 parquet은 매 실행마다 덮어쓴다.