# crypto/trend_chase

크립토 멀티 TF 추격 시그널. 두 점수 함수 보유:

| 함수 | 입력 | 시점 평가 | 용도 |
|---|---|---|---|
| `score_chase_crypto` (v1, 1d primary) | df_1d + df_1h alignment | 1d 봉 종가 시점 | 백테스트 (D+N hold 평가) |
| **`score_chase_entry_1h`** (v2, **1h primary**) | df_1h + df_1d confirm | **1h 봉 last 시점** | **추천 (지금 타점)** |

사용자 의도 (2026-05-26): *"crypto 는 1h/4h 기준. 추천은 결국 타기 좋은 타점에 지금 있냐가 중요."*
→ `recommend.py` 는 v2 (entry timing) 사용. `backtest.py` 는 v1 (1d entry) 사용 — 두 함수 검증 목적 다름.

> 설계 가설은 [PLAN.md](PLAN.md).

## 운영 명령

```bash
# 1h primary 추천 (단기 hold — 수시간) — 1h cache 의 가장 최근 봉 자동 cutoff
.venv/Scripts/python.exe -m scripts.crypto.trend_chase.recommend --tf 1h --topn 20 --min-score 50

# 4h primary 추천 (중기 hold — 1~3일)
.venv/Scripts/python.exe -m scripts.crypto.trend_chase.recommend --tf 4h --topn 20 --min-score 50

# 특정 시점 추천
.venv/Scripts/python.exe -m scripts.crypto.trend_chase.recommend --tf 1h --cutoff "2026-05-26 11:00"

# 백테스트 (v1, 1d primary, multi-TF alignment) — entry score 백테스트는 별도 작업 예정
.venv/Scripts/python.exe -m scripts.crypto.trend_chase.backtest --start 2025-11-26 --end 2026-05-26
```

## 모듈

| 파일 | 역할 |
|---|---|
| `scoring.py` | `score_chase_crypto(df_1d, df_1h)` — 1d core + 1h/4h 멀티 TF 보너스 + 진입 페널티 |
| `backtest.py` | 자체 multi-TF harness (1d primary + 1h cache load), threshold sweep + 분위 분석 |
| `recommend.py` | cutoff 시점 점수 TOP N. CSV 저장. |
| `PLAN.md` | 설계 가설 (KR v5.1 대비 crypto 스케일 조정값, 향후 개선) |

## 점수 구조

### v1 `score_chase_crypto` (1d primary, max ≈ 115)

| 컴포넌트 | 범위 | 핵심 |
|---|---|---|
| 1d core | 0~95 | KR v5.1 골격: 정배열, ret_30d/90d, 거래량 폭증, MA10 riding, 강양봉 holding (crypto 임계값 ×2) |
| 4h alignment | 0~10 | 4h bull_stack + ma10_slope > 0, 4h ret_60bars > 0.20 |
| 1h alignment | 0~10 | 1h vol_burst (24h vs prior 72h), 1h 가격 > MA20 |
| 진입 시점 페널티 | -33~0 | 직전 24h 누적 ret > 20% / 4h ret > 10% / 1h dist_ma10 > 20% |

### v2 entry (1h primary `score_chase_entry_1h` / 4h primary `score_chase_entry_4h`, max ≈ **130**)

같은 가중치 구조. 4h 는 1h cache 를 4h 리샘플 후 같은 점수 식 적용 (시간 horizon 24h/72h/168h 유지, bar count 만 ÷4).

| 컴포넌트 | 범위 | 핵심 |
|---|---|---|
| 1h/4h 추세 + 정배열 | 0~20 | bull_stack, ma10/20 slope up |
| ret_24h / ret_72h | -18~20 | crypto 1h≈1% / 4h≈2% σ → 24h +5~20% sweet, +30% 폭등 페널티 |
| vol_burst (24h vs prior 72h) | -5~12 | 추격의 핵심 거래량 폭증 |
| **패턴 1a: MA10 riding** | 0~19 | strong_up (+6) + 최근 12h MA10 터치 (+8) + dist_ma10 0~5% (+5) |
| **패턴 1b: MA20 riding (NEW)** | 0~16 | 깊은 풀백 후 진입. strong_up (+5) + 최근 24h MA20 터치 (+7) + dist_ma20 0~8% (+4) |
| **dist 페널티 — nearest-MA 기준** | -18~0 | min(\|dist_ma10\|,\|dist_ma20\|) > 8%(-4) / 12%(-10) / 20%(-18). **두 MA 모두 멀어진 자리만 페널티** |
| 패턴 2: 강양봉 holding | 0~18 | strong_bull (body>2~4% + vol_rank>0.85), bullish_holding |
| 4h alignment (1h 점수일 때) | 0~10 | 4h bull_stack + ret_60_4h > 20% |
| 1d 추세 confirm | -23~16 | 1d bull_stack + ret_30/90d 강세 / 약세 페널티, 신고가 근접 |
| 진입 페널티 | -27~0 | 직전 4h ret > 10% (-12), 24h > 30% (-15) |

**MA20 추가 이유** (2026-05-26 사용자 지적): MA10 에만 매몰되면 깊은 풀백 (예: dist_ma10 9% / dist_ma20 1%) 진입 자리를
페널티로 떨어뜨림. 두 라인 모두 valid 진입 지지선이라 OR 점수 + dist 페널티는 nearest-MA 기준으로 변경.

## KR v5.1 대비 차이

| 항목 | KR | Crypto |
|---|---|---|
| 1d ret_30d 임계값 (10점) | > 1.0 | > 2.0 |
| 1d ret_90d 임계값 (10점) | > 2.0 | > 4.0 |
| today_chg 페널티 시작 | 0.15 | 0.30 |
| dist_ma10 페널티 시작 | 0.20 | 0.45 |
| 멀티 TF 보너스 | 없음 (1d 단일) | 4h + 1h 알라인먼트 |
| 진입 시점 페널티 | today_chg + dist_ma10 (1d) | + 1h 봉의 24h/4h ret + 1h dist_ma10 |

## 데이터 의존

- `data/cache/crypto/1d/{SYM}.parquet` — 필수
- `data/cache/crypto/1h/{SYM}.parquet` — 선택 (없으면 1d core 점수만 사용, 멀티 TF 보너스/페널티 = 0)

cache 갱신은 `/crypto-fetch` 스킬.

## 운영 threshold (백테스트 검증 완료)

**threshold ≥ 60** — 6개월 (567 종목 × 113 거래일, 19,197 샘플) 백테스트 결과:

| threshold | n | D+30 mean | D+30 sharpe | win |
|---|---|---|---|---|
| ≥ 0 (baseline) | 13,239 | +0.83% | 0.012 | 36.7% |
| ≥ 20 | 6,172 | +5.5% | 0.066 | 39.0% |
| ≥ 40 | 2,622 | +15.2% | 0.133 | 41.7% |
| **≥ 60 (운영)** | **828** | **+32.7%** | **0.203** | **42.4%** |
| ≥ 80 (공격) | 92 | +85.9% | 0.377 | 47.8% |

분위 q9 (top 10%, 점수 56~101) 만 차별력 명확. q0~q8 거의 무차별.
`recommend.py --min-score` 의 기본값 = 60.

**최적 hold period: D+30** (KR v5.1 의 D+60 과 다름 — crypto 가 변동성 빨라 60일이면 mean 회귀).

**Win rate 40% 전후 + median 음수 + mean 양수 = fat tail** 특성 (대박 일부 + 작은 손실 다수).
자동매매보다 추천 / 시각 검토 후 진입용으로 사용 권장.

## 향후 개선 (PLAN.md)

- multi-symbol concurrency 강화 (현재 ThreadPoolExecutor 8 workers — IO bound 면 더 늘릴 수 있음)
- 1h trigger 기반 intra-day entry 시점 측정 (현재는 1d 종가 진입)
- `_common.backtest_runner` 일반화: multi-TF cache 지원 → cascading_pullback 도 흡수 가능

## 사용자 표준 명령 (메모리 등록 후보)

추천 출력 포맷이 사용자 표준으로 안착하면 `feedback_crypto_recommend_format.md` 메모리로
등록 예정. 현재는 검토 단계.
