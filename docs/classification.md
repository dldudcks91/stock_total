# 코인 행동 분류 (Classification)

`/classify-coins` 스킬 산출물(`data/cache/classification.parquet`)의 의미와 대시보드 활용 계획.

## 4그룹 정의 (`tier_final`)

| 그룹 | 코드 | 정의 | 대표 코인 (현재 분류 결과) |
|---|---|---|---|
| 🟢 **추세형** | `trend` | 자기 시장을 가진 메이저 알트. 자기 추세를 만들거나(R²<0.5 + Hurst>0.55) 거래량이 압도적으로 큰 동조 메이저 | ETH, SOL, XRP, BNB, ADA, AVAX, DOGE, LINK, BCH, TRX, TON, UNI, SHIB, PEPE |
| 🔵 **추종형** | `follower` | BTC와 강하게 동조 (R²>0.6, β>1). 자기 시장 약함, BTC 따라 움직임 | LTC, NEAR, ATOM 등 |
| 🟡 **세력형** | `whale` | 적당한 두꺼운 꼬리(8≤kurt_t<20) + 펌프 빈도 있음. 단발 충격 또는 가벼운 세력 개입 | (분류 결과 30개) |
| 🔴 **잡코인** | `junk` | 진짜 주작(반복 펌프 + 두꺼운 꼬리) + 신규 미검증 (1년 미만 데이터) + 분류 불가 | TRUMP, PI, H, SPK 등 |

특수 라벨 (4그룹 외):
- `benchmark`: BTCUSDT 자체 (분류 대상 X, 베타 계산 기준)
- `stable`: 연 변동성 < 5% (USDC 페어 등)

## 현재 분포 (2025년 말 기준 543개)

| 그룹 | 개수 | 비율 |
|---|---|---|
| junk | 292 | 53.8% |
| trend | 126 | 23.2% |
| follower | 93 | 17.1% |
| whale | 30 | 5.5% |
| benchmark | 1 | 0.2% |
| stable | 1 | 0.2% |

**시사점**: Bitget USDT-perp의 절반 이상이 잡코인(주작 또는 1년 미만 신규). 백테스트 유니버스를 `trend + follower + whale = 249개` 로 좁히는 것이 합리적.

## 메트릭 정의

| 메트릭 | 의미 | 정상 범위 |
|---|---|---|
| `r2_btc` | BTC 일일수익률 회귀 결정계수 (0~1) | 0.3~0.9 |
| `beta_btc` | BTC 베타 | 0.5~2.0 |
| `hurst` | R/S 분석 추세 지속성. 0.5=랜덤워크, >0.55=추세성 | 0.45~0.65 |
| `kurtosis` | Pearson 첨도 (정규=3). 단발 outlier에 민감 | 3~50+ (TRX는 406) |
| `kurt_trimmed` | 양극단 0.5%씩 윈저화 후 첨도. **분류 룰의 주 기준** | 3~25 |
| `pump_count_per_year` | \|z\| > 5 봉 빈도 (연단위) | 0~10 |
| `pump_recurrence` | 펌프 이벤트가 분포된 분기 비율 (0~1). 단발 충격 ↓, 반복 펌프 ↑ | 0~0.5 |
| `realized_vol_annual` | 연율화 실현 변동성 | 0.5~2.5 |
| `volume_score_3y` | 2023~2025 누적 USDT 거래대금 | — |
| `listing_days` | **Bitget 캐시 데이터 보유 일수** (코인 자체 나이 X) | 5~967 |

## 그룹별 추천 전략 (가설)

이 단계는 아직 백테스트 검증 전. 다음 단계에서 정량 검증 예정.

| 그룹 | 추천 전략 후보 | 이유 |
|---|---|---|
| **trend** | SMA cross, Donchian breakout, 시계열 모멘텀 | 자기 추세 명확 → 트렌드 추종이 잘 먹힐 가능성 |
| **follower** | BTC 신호 활용 (BTC가 트렌드일 때 동일 방향), 베타 추적 | 자기 알파 약함, BTC 의존 |
| **whale** | 평균회귀 + 트렌드 필터, 펌프 후 fade | 두꺼운 꼬리 = 평균 복귀 가능성 |
| **junk** | **백테스트 유니버스에서 제외 권장** | 신뢰성 낮음 |

## 대시보드 통합 계획

### Phase 1: 백테스트 대시보드에 분류 정보 표시 (`dashboards/backtest_app.py`)

런 디렉터리의 `config.yaml` 에서 symbol 추출 → classification.parquet 조회 → 사이드바에 표시:
- 심볼명 옆에 그룹 배지 (🟢 trend, 🔵 follower, 🟡 whale, 🔴 junk)
- config 요약 박스에 분류 메트릭 6개 (R², β, Hurst, kurt_t, pump_rec, vol)
- 그룹별 추천 전략과 비교 ("이 코인은 trend인데 평균회귀 전략을 썼다 — 권장 X")

### Phase 2: 분류 자체 대시보드 추가 (신규 페이지 또는 토글)

새 Streamlit 페이지 `dashboards/classification_app.py`:
- **상단 KPI**: 그룹별 코인 수, 평균 변동성, 평균 거래대금
- **그룹별 산점도**:
  - X축: R²_btc (BTC 동조성)
  - Y축: kurt_trimmed (꼬리 두께)
  - 색상: tier_final
  - 호버: 심볼·메트릭
- **그룹별 메트릭 분포** (violin/box plot): kurt_t, hurst, vol 등
- **유니버스 필터**: 그룹 체크박스로 "내가 백테스트할 코인 목록" 필터링 후 export

### Phase 3: 실시간 대시보드 통합 (`dashboards/realtime_app.py`)

실시간 시세 화면에서 그룹별 그룹핑:
- 트렌드 코인 섹션 / 추종 코인 섹션 / 세력 코인 섹션 / 잡코인 섹션
- 그룹별 평균 일일 수익률 (시장 무드 파악)
- 잡코인은 기본적으로 접혀 있음 (필요 시 펼침)

## 데이터 접근 패턴

```python
import pandas as pd
from pathlib import Path

CLASSIFICATION_PATH = Path("data/cache/classification.parquet")

def load_classification() -> pd.DataFrame:
    """전체 분류 결과 로드. 매번 IO이므로 streamlit @cache_data 권장."""
    if not CLASSIFICATION_PATH.exists():
        return pd.DataFrame()
    return pd.read_parquet(CLASSIFICATION_PATH)

def get_tier(symbol: str) -> str:
    """심볼 1개의 tier_final. 없으면 'unknown'."""
    df = load_classification()
    row = df[df["symbol"] == symbol]
    return row["tier_final"].iloc[0] if len(row) else "unknown"

def list_by_tier(tier: str) -> list[str]:
    """그룹별 심볼 목록."""
    df = load_classification()
    return df[df["tier_final"] == tier]["symbol"].tolist()
```

## 재실행 정책

- **분기마다** 1회 (`/classify-coins`) — 신규 상장 코인이 unclassified_new에서 졸업
- **신규 심볼 50개 이상** 캐시에 추가 시 재실행
- **큰 시장 레짐 전환** 직후 (ATH 갱신, 대형 청산 이벤트 후)

매 실행 시 `classified_at` ISO datetime이 기록됨 → 대시보드에서 "분류 기준일: 2026-05-10" 식으로 표시 권장.

## 한계와 정직한 평가

1. **OHLCV만 사용**: 시총·홀더 분포·온체인 데이터 없이 분류. PEPE/SHIB 같은 큰 거래량 밈코인은 trend로 분류되지만 실제 성격은 다를 수 있음.
2. **시간 의존성**: 정적 분류 (2023~2025 한 시점). SOL은 2021년엔 잡코인이었지만 현재는 trend. 과거 백테스트에 현재 분류를 적용하면 미세한 시각 편향(look-ahead bias) 존재.
3. **listing_days 함정**: ZEC(Zcash)는 2016년 코인이지만 Bitget 상장이 늦어 listing_days=77일 → junk로 떨어짐. **코인 나이 ≠ 데이터 나이**.
4. **junk가 절반**: 너무 큼. 진짜 주작(12개)와 신규 미검증(280개)는 본질이 다름. 대시보드에서는 `tier_detail` 로 세부 표시 권장.

## 관련 파일

- 분류 모듈: [`data/classification.py`](../data/classification.py)
- 산출물: `data/cache/crypto/classification.parquet`
- 스킬: [`/crypto-classify`](../.claude/skills/crypto-classify/SKILL.md)
- 베이스 데이터: `data/cache/crypto/1h/{SYMBOL}.parquet`
