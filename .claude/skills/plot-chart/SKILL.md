---
name: plot-chart
description: 임의 심볼(crypto/KR/US)의 OHLCV를 Bitget/TradingView 스타일 인터랙티브 캔들 차트로 그린다. 이동평균(기본 MA7/25/99), 거래량 막대, RSI(옵션) 서브플롯 포함. Plotly Figure 반환 — Streamlit 대시보드 또는 노트북에서 그대로 사용. 사용자가 "차트", "캔들", "candle", "chart", "{심볼} 보여줘", "이평선"을 요청할 때 발동.
---

# /plot-chart

자산 무관 캔들 차트 모듈. crypto(Bitget 1H/4H/1D/1W) / KOSPI / NASDAQ 모두 동일 API로 처리.

## 구성

- **`data/loader.py`** — `load_ohlcv(asset, symbol, interval)` 자산 무관 로더
- **`dashboards/charts.py`** — `plot_ohlcv(df, ...)` Plotly Figure 빌더 + `plot_symbol(...)` 편의 함수
- **`dashboards/pages/7_Chart.py`** — Streamlit 페이지 (사이드바 선택 + URL query params 지원)

## Python API

### 1) 자산+심볼로 한 번에

```python
from dashboards.charts import plot_symbol

fig = plot_symbol("crypto", "BTCUSDT", "1d", bars=500)
fig.show()   # 노트북

# Streamlit
import streamlit as st
st.plotly_chart(fig, use_container_width=True)
```

### 2) DataFrame 직접 넘기기

```python
from data.loader import load_ohlcv
from dashboards.charts import plot_ohlcv

df = load_ohlcv("kr", "005930", "1d").tail(300)
fig = plot_ohlcv(
    df,
    title="삼성전자 · 1D",
    ma_periods=(20, 60, 120),    # 한국식 (Bitget은 7/25/99)
    show_volume=True,
    show_rsi=True,
    skip_weekends=True,          # 주식은 토/일 공백 제거
    height=760,
)
```

## 인자

| 인자 | 기본값 | 의미 |
|---|---|---|
| `ma_periods` | `(7, 25, 99)` | 이동평균 주기 (Bitget 기본값). 여러 개 가능. |
| `show_volume` | `True` | 거래량 막대 서브플롯 |
| `show_rsi` | `False` | RSI 서브플롯 (기본 14 기간) |
| `rsi_period` | `14` | RSI 기간 |
| `height` | `720` | Figure 높이(px). RSI 켜면 +120 권장 |
| `range_slider` | `False` | x축 미니 슬라이더 |
| `skip_weekends` | `False` | 주식차트에서 토/일 공백 제거. crypto는 False(24/7). |

## Streamlit 페이지 사용

```bash
.venv/Scripts/streamlit.exe run dashboards/app.py
# → 사이드바 "📈 Chart" 페이지 진입
# → 자산(crypto/kr/us) · 심볼 · 인터벌 · MA · RSI 선택
```

다른 페이지에서 딥링크로 차트 열기:
```
/Chart?asset=crypto&symbol=BTCUSDT&interval=4h
/Chart?asset=kr&symbol=005930&interval=1d
```

## 입력 DataFrame 스키마

`plot_ohlcv` 는 양쪽 모두 자동 인식 (내부에서 정규화):

- **crypto** (`data.resample.load`): 소문자 `open/high/low/close/volume` + `timestamp` (UTC ms)
- **주식** (`data/cache/{kr,us}/*.parquet`): TitleCase `Open/High/Low/Close/Volume` + `DatetimeIndex(naive)`

타임존: 내부적으로 KST로 변환 후 표시 (CLAUDE.md의 시간 표준).

## 디자인 결정

- **차트 라이브러리**: Plotly (인터랙티브, Streamlit 통합, 노트북 호환). matplotlib/mplfinance는 정적 출력만 가능.
- **색상**: Bitget 팔레트 (`#1FCC81` up, `#F6465D` down). 다크 테마 고정. 라이트 모드는 향후 옵션화.
- **MA 기본값**: Bitget 차트와 동일한 7/25/99. 한국 주식 차트 관행(20/60/120)과 다름 — 호출자가 명시.
- **range_slider 기본 False**: 화면 공간 절약. 필요하면 켜기.

## 제약

- 1번에 한 심볼만. 멀티 심볼 비교 차트는 별도 함수(`plot_compare`) 필요시 추가.
- 4H 이상 인터벌 + 주식(`skip_weekends=True`)은 휴장 시간이 살짝 어색할 수 있음 — 일봉/주봉에서 사용 권장.
- 거래량 단위가 자산별로 다름 (crypto=코인 수량, 주식=주식 수). 차트에는 그대로 표시.
- 캔들 1000개 이상 그리면 브라우저 렌더링이 느려질 수 있음 — `bars` 파라미터로 제한.

## 향후 확장

- Drawing tools (추세선/지지저항선)
- 백테스트 시그널/체결을 오버레이로 표시 (`overlay_trades=trades_df`)
- 다른 지표 추가 (MACD, Bollinger Bands, VWAP)
- 멀티 심볼 비교 (`plot_compare(["BTCUSDT", "ETHUSDT"], normalize=True)`)