---
name: analyze-metrics
description: OHLCV 데이터프레임으로 이동평균·RSI·수익률·변동성 등 정량 지표를 계산하고 리포트용 요약을 산출. 크립토/주식/지수 모든 자산군에 적용 가능 (컬럼 표기 차이 자동 처리). 사용자가 "지표", "이동평균", "RSI", "수익률", "변동성", "차트 데이터", "metrics"를 요청할 때 발동.
---

# /analyze-metrics

자산 무관(asset-agnostic) 정량 지표 계산. crypto 1H/4H/1D, KR/US 1D 모두에 적용. `research/analyze.py`가 실제 구현.

## 컬럼 규약

자산마다 컬럼 케이스가 다르므로 입력 단계에서 정규화:

- **크립토 (`data.resample.load`)**: 소문자 `open, high, low, close, volume, amount`
- **주식 (`research.collect.load_daily` / FDR)**: 대문자 `Open, High, Low, Close, Volume, Change`

`research.analyze` 는 양쪽 모두 받도록 작성. 새로 호출할 때 어느 케이스인지 확인.

## 기본 지표

```python
# 이동평균 (Close 컬럼 기준)
df["MA20"]  = df["Close"].rolling(20).mean()
df["MA60"]  = df["Close"].rolling(60).mean()
df["MA120"] = df["Close"].rolling(120).mean()

# 수익률
df["ret_1d"] = df["Close"].pct_change()
df["ret_1m"] = df["Close"].pct_change(20)    # 약 1개월 (영업일)
df["ret_1y"] = df["Close"].pct_change(252)

# 변동성 (연환산, 영업일 252 기준)
df["vol_20d"] = df["ret_1d"].rolling(20).std() * (252 ** 0.5)
```

크립토는 영업일이 없으므로 변동성 연환산에 `sqrt(365)` 사용 — `research.analyze.report_metrics(df, asset="crypto")` 처럼 분기.

## RSI

```python
def rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)
```

## 리포트용 요약 (`report_metrics`)

| 항목 | 값 |
|---|---|
| 기준일 | YYYY-MM-DD |
| 종가 | 단위 자동 (KRW/USD/USDT) |
| 52주 최고 / 최저 | 영업일 252 기준 |
| MA20 / MA60 / MA120 위치 | 위/아래 |
| 1M / 3M / 1Y 수익률 | %, %, % |
| 20D 변동성 (연환산) | % |
| RSI(14) | 값 + 과매수(>70)/과매도(<30) 라벨 |

## 종목 비교

벤치마크와의 상대 수익률 곡선을 항상 동봉:

- 크립토 → BTCUSDT
- KOSPI 종목 → `KS11` (KOSPI 지수)
- KOSDAQ 종목 → `KQ11`
- NASDAQ 종목 → `IXIC`

## 원칙

- **lookahead bias 방지**: 백테스트용으로 쓸 때는 `rolling()` 후 `shift(1)` 필수
- 결측 처리는 `dropna()` 일괄 호출보다 단계별 명시
- 52주 최고/최저는 `df.tail(252)` 사용 (영업일). `df.last("252D")` 는 캘린더 일이라 부정확
- 결과는 `research/analysis/{ticker}_{YYYYMMDD}.json` 에 캐시