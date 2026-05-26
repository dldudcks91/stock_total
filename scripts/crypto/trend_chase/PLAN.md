# crypto/trend_chase — PLAN

## 목적

크립토 멀티 TF (1h/4h/1d) 특성을 활용한 "추격" 시그널. KR `scripts/kr/trend_chase` (v5.1) 의
**핵심 패턴 (MA10 riding + 강양봉 + 진입 시점 페널티)** 을 보존하되, crypto 의 다음 특성을 활용:

- **24/7 거래** → 1h/4h 봉이 유의미한 단위
- **변동성 스케일** : 1h≈1%, 4h≈2%, 1d≈4%, 1w≈10% (BTC σ 기준)
- **TF 계층 알라인먼트** : 1d 추세 방향 + 4h 가속 + 1h 진입 트리거

기존 `backtest/strategies/trend_chase.py` (dashboards 가 쓰는 single-TF 엔진) 은 그대로 두고,
이 폴더는 **그 엔진을 멀티 TF 로 조합한 추천/백테스트 layer**.

## 점수 설계 (v1)

**입력**: 1d df (primary) + 1h df + 4h df (alignment 용). 모두 같은 종목.

```
score_chase_crypto(df_1d, df_1h, df_4h) -> Series (1d index)

= score_1d_core(df_1d)                                # KR v5.1 가중치 1d 스케일 적용
+ alignment_bonus_4h(df_1d, df_4h)                    # 4h ret_60bars + MA10 slope 일치
+ alignment_bonus_1h(df_1d, df_1h)                    # 1h vol_burst (최근 24h)
+ entry_timing_penalty(df_1d, df_1h)                  # 1h 봉 폭등 후면 페널티
```

### 1) 1d core (KR v5.1 동일 골격)

- 정배열 + MA slope up
- ret_30d / ret_90d 양봉 (crypto 스케일은 KR 보다 후함: ret_30d > 0.5 가 "흔함")
- 거래량 폭증
- MA10 riding (1d): `ma10_touch_recent_5d`, `ma10_strong_up`, `dist_ma10` 0~0.15
- 강양봉 holding (1d): `today_strong_bull`, `bullish_holding`, 신고가 근접
- 페널티: bear_stack, Close < MA10

차이점 (KR 대비):
- `ret_30d` 임계값을 crypto 스케일로 조정: > 1.0 (×2 정도)
- `today_chg` 임계값: > 0.30 (×2)
- `dist_ma10` 페널티: > 0.50 (×1.5) — crypto 변동성 더 큼

### 2) 4h alignment 보너스 (+10)

`df_4h` 의 cutoff 시점 last row 에서:
- `bull_stack_4h == 1` and `ma10_slope_4h > 0`  → +5
- `ret_60bars_4h > 0.20` (60×4h = 10일치)  → +5

### 3) 1h alignment 보너스 (+10)

`df_1h` 의 cutoff 시점 last row 에서:
- 1h 거래량 폭증 (`vol_24h / vol_prior_72h > 2.0`)  → +6
- 1h 가격 > 1h MA20 and 1h MA20 slope > 0  → +4

### 4) 1h 진입 시점 페널티 (-)

- 직전 24h 누적 등락률 > 0.20 → -15 (너무 늦은 진입)
- 직전 4h 봉 ret > 0.10  → -10
- 1h `dist_ma10` > 0.20  → -8 (KR v5.1 의 dist_ma10 페널티 1h 버전)

### 합계 최대값 (페널티 제외)

- 1d core: ~95 (KR v5.1 의 106 에서 today_chg 페널티 빼고 비슷)
- 4h: 10
- 1h: 10
- **CH_CRYPTO_MAX ≈ 115**

## 운영 threshold (백테스트 검증 완료, 2026-05-26)

검증 결과 **threshold ≥ 60** 로 확정 (자세히: [README.md](README.md)):
- D+30 mean +32.7%, sharpe 0.203, n=828
- 점수 분위 q9 (top 10%) 만 명확한 alpha (q0~q8 거의 무차별)
- 최적 hold = D+30 (KR v5.1 의 D+60 과 다름)
- Win rate 40% 전후 + fat tail = 추천 / 시각 검토 진입용 (자동매매 X)

KR v5.1 의 threshold ≥ 13 과 crypto 의 ≥ 60 차이는 점수 max 차이 (KR 106 vs Crypto 115)
+ 가산 패턴 차이 (crypto 는 멀티 TF 보너스 10+10 만큼 점수가 더 큼).

## 백테스트 구조

`backtest_runner.run_backtest` 는 single-TF cache. crypto chase 는 멀티 TF 필요 →
**자체 harness**:

```python
for sym in symbols:
    df_1d = load("1d", sym)
    df_1h = load("1h", sym)
    df_4h = load("4h", sym)  # 1h 리샘플 OK
    score = score_chase_crypto(df_1d, df_1h, df_4h)
    fwd_ret = df_1d["close"].shift(-h) / df_1d["close"] - 1
    ...
```

cascading_pullback 의 `cp_1h_backtest_3d.py` 와 유사한 패턴.

## 변경 history

**2026-05-26 v2 (entry timing)**:
- 사용자 의도 "지금 타기 좋은 타점에 있냐" → 1h primary `score_chase_entry_1h` + 4h primary `score_chase_entry_4h` 추가
- 평가 시점: 기존 1d 봉 종가 → **1h/4h 봉 last close** (현재 시각)
- `recommend.py` 의 default = entry score, `--tf` 옵션 (1h | 4h)
- 백테스트는 여전히 v1 (1d primary) 사용 — entry score 백테스트는 1h-bar fwd_ret 으로 별도 작업

**2026-05-26 v2.1 (MA10 only → MA10/MA20 OR)**:
- 사용자 지적: MA10 에만 매몰되면 dist_ma10 ≈ 10% / dist_ma20 ≈ 1% 같은 깊은 풀백 진입 자리를 페널티로 떨어뜨림
- 패턴 1 분해: **1a MA10 riding** + **1b MA20 riding** 둘 다 점수 부여 (OR 점수)
- dist 페널티는 `min(|dist_ma10|, |dist_ma20|)` (nearest-MA) 기준 — 두 MA 모두 멀어진 자리만 페널티
- max 점수 110 → **130** (MA20 가산점 +16 만큼)

## 향후 개선

- entry score 전용 백테스트 (1h 봉 진입 + N시간 fwd_ret) — threshold 정량 검증 필요 (현재 min-score=50 은 임시)
- 4h primary 의 last 4h bar 가 미완성 봉인 경우 (e.g. cache 가 4h 의 마지막 봉 진행 중) 처리 명확화
- multi-symbol concurrency 강화 (ThreadPoolExecutor 8 workers — 1h cache 큰 종목 많아지면 더 늘리기)
- backtest_runner 일반화 (multi-TF cache 지원) — cascading_pullback 도 같이 흡수 가능

## 향후 자산

KR 의 v5.1 single-TF 와 crypto 의 multi-TF 가 본질적으로 다른 setup. 공통 코어
(`score_1d_core`) 는 _common 으로 추출 가능하지만 v1 에서는 strategy 폴더 안에 self-contained.
