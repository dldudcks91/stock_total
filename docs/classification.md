# 코인 분류 (Classification)

`/crypto-classify` 스킬 산출물(`data/cache/crypto/classification.parquet`)과 `data/sectors.py` 산출물(`data/cache/crypto/sectors.parquet`)의 의미.

분류는 **2축 직교 체계**:
- **행동 라벨** (behavior) — OHLCV 통계 기반. 자동, 분기 재실행. 전략 매칭에 사용.
- **섹터 라벨** (sector) — CoinGecko `/coins/{id}` 의 `categories` 기반. 멀티 라벨. 시장 내러티브에 사용.

## 1) 행동 라벨 (`tier_final`) — 6그룹 + 시스템 2

| 그룹 | 코드 | 정의 | 대표 코인 (가설) |
|---|---|---|---|
| 🟢 **추세형** | `trend` | 자기 시장을 가진 메이저 알트. 자기 추세를 만들거나(R²<0.5 + Hurst>0.55) 거래량이 압도적으로 큰 동조 메이저 | ETH, SOL, XRP, BNB, ADA, AVAX, DOGE, LINK, BCH, TRX, TON, UNI, SHIB, PEPE |
| 🔵 **추종형** | `follower` | BTC와 강하게 동조 (R²>0.6, β>1). 자기 시장 약함, BTC 따라 움직임 | LTC, NEAR, ATOM 등 |
| 🟡 **세력형** | `whale` | 적당한 두꺼운 꼬리(8≤kurt_t<20) + 펌프 빈도 있음. 단발 충격 또는 가벼운 세력 개입 | (분류 결과 30개) |
| 🟠 **주작의심** | `junk_pump` | 반복 펌프(`pump_recurrence>0.3`) + 두꺼운 꼬리(`kurt_trimmed>20`) — 진짜 주작 시그니처 | TRUMP, 일부 PEPE 변종 등 |
| ⚪ **신규 미검증** | `junk_new` | `listing_days<365` — Bitget 캐시 데이터가 1년 미만이라 통계 신뢰도 낮음 | 최근 1년 내 상장 코인 |
| 🔴 **잡코인** | `junk` | 어느 룰에도 안 잡힘 (mixed). KMeans 폴백도 분류 불가 | (소수) |

특수 라벨:
- `benchmark`: BTCUSDT 자체 (분류 대상 X, 베타 계산 기준)
- `stable`: 연 변동성 < 5% (USDC 페어 등)

> **junk 세분화 배경**: 옛 4그룹에서는 "junk" 가 50%+ 를 잡아먹어 의미가 흐릿했다. 진짜 주작(`junk_pump`) / 데이터 부족(`junk_new`) / 분류 불가(`junk`) 는 본질이 다르므로 분리. 옛 코드 호환은 `data.universe.sample_group("junk")` 이 셋을 모두 합쳐서 반환한다.

## 2) 섹터 라벨 (`sectors`)

CoinGecko `/coins/{id}` API 의 `categories` 배열을 그대로 멀티 라벨로 저장. 600+ 카테고리 중 해당 코인이 속한 것들이 list[str] 로 들어감.

```
ETHUSDT → ["Smart Contract Platform", "Layer 1 (L1)", "Ethereum Ecosystem", "Proof of Stake (PoS)"]
PEPEUSDT → ["Meme", "Ethereum Ecosystem", "Pump.fun Ecosystem (사후)"]
ONDOUSDT → ["Real World Assets (RWA)", "DeFi"]
```

자세한 fetch 절차·심볼 정규화 규칙은 [data/sectors.py](../data/sectors.py) 참조.

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
| `realized_vol_annual` | 연율화 실현 변동성 (전체 윈도우) | 0.5~2.5 |
| `volume_score_3y` | 윈도우 기간 누적 USDT 거래대금 | — |
| `avg_quote_vol_30d` | **최근 30일 평균 USDT 거래대금** — 유동성 tier 표시용 | — |
| `vol_30d` | 최근 30일 연환산 변동성 — 현재 레짐 | 0.3~3.0 |
| `vol_pct_rank` | `vol_30d` 의 자기 자신 히스토리 백분위 (0~1) — 변동성 압축/팽창 식별 | 0~1 |
| `listing_days` | **Bitget 캐시 데이터 보유 일수** (코인 자체 나이 X) | 5~967 |

## 그룹별 추천 전략 (가설)

이 단계는 아직 백테스트 검증 전. 다음 단계에서 정량 검증 예정.

| 그룹 | 추천 전략 후보 | 이유 |
|---|---|---|
| **trend** | SMA cross, Donchian breakout, 시계열 모멘텀, trend_pullback | 자기 추세 명확 → 트렌드 추종이 잘 먹힐 가능성 |
| **follower** | BTC 신호 활용 (BTC가 트렌드일 때 동일 방향), 베타 추적 | 자기 알파 약함, BTC 의존 |
| **whale** | 평균회귀 + 트렌드 필터, 펌프 후 fade | 두꺼운 꼬리 = 평균 복귀 가능성 |
| **junk_pump** | **백테스트 유니버스에서 제외** | 반복 펌프 — 신뢰성 낮음, 룩어헤드 위험 |
| **junk_new** | **백테스트 유니버스에서 제외**, 단 모니터링은 OK | 1년 미만 — 통계 추정치 불안정 |
| **junk** | 검토 후 결정 | 어느 룰에도 안 잡힘 — 케이스별 검토 |

## 대시보드 통합 (미구현 아이디어)

분류 정보를 UI 에 노출할 만한 자리:
- 백테스트/추천 사이드바에 심볼 옆 그룹 배지 (🟢 trend / 🔵 follower / 🟡 whale / 🟠 junk_pump / ⚪ junk_new / 🔴 junk)
- 산점도 (R²_btc × kurt_trimmed, 색=tier_final) + 그룹별 메트릭 분포
- 라이브 뷰에서 그룹별 섹션 그룹핑 (junk 계열 기본 접힘)

*현재 UI 통합은 없음. 필요할 때 별도 스킬/페이지로 붙일 계획.*

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

1. **OHLCV만 사용**: 행동 라벨은 가격 통계만 사용. PEPE/SHIB 같은 큰 거래량 밈코인은 trend로 분류되지만 실제 성격(meme)은 섹터 라벨로만 잡힘.
2. **시간 의존성**: 행동 라벨은 정적 분류 (2023~2025 한 시점). SOL은 2021년엔 잡코인이었지만 현재는 trend. 과거 백테스트에 현재 분류를 적용하면 미세한 시각 편향(look-ahead bias) 존재.
3. **listing_days 함정**: ZEC(Zcash)는 2016년 코인이지만 Bitget 상장이 늦어 listing_days가 작음 → `junk_new` 로 떨어짐. **코인 나이 ≠ 데이터 나이**. CoinGecko `genesis_date` 를 같이 보면 보완 가능.
4. **junk 세분화 (2026-05 갱신)**: 옛 4그룹은 junk 가 50%+ 였음. 이제 `junk_pump` / `junk_new` / `junk` 세 라벨로 본질 분리. junk_new 가 대부분일 것으로 예상 — 자연스러운 분포.
5. **섹터 라벨 시간 안정성**: 카테고리는 거의 변하지 않지만, CoinGecko가 새 카테고리를 만들면 멀티 라벨이 늘어남. `fetched_at` 으로 시점 기록.

## 관련 파일

- 분류 모듈: [`data/classification.py`](../data/classification.py)
- 산출물: `data/cache/crypto/classification.parquet`
- 스킬: [`/crypto-classify`](../.claude/skills/crypto-classify/SKILL.md)
- 베이스 데이터: `data/cache/crypto/1h/{SYMBOL}.parquet`
