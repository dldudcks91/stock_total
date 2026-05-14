# Live 페이지 KOSPI 탭 로딩 지연 — 분석 및 해결안

작성: 2026-05-14
대상 파일: `dashboards/pages/3_Live.py`, `dashboards/live/kospi.py`, `dashboards/live/nasdaq.py`,
          `dashboards/_stock_grid.py`, `dashboards/_recommendation.py`,
          `backtest/strategies/trend_chase.py`

---

## 1. 증상

Live 페이지 진입 시 KOSPI 탭(과 NASDAQ 탭)이 매우 느리게 뜸. 특히 Streamlit 서버 재시작 후 첫 진입에서 체감 가장 큼.

## 2. 원인 (Streamlit 레벨 + 코드 레벨)

### 2-1. `st.tabs`는 모든 탭 본문을 매 rerun마다 실행 (Streamlit 디자인)

`dashboards/pages/3_Live.py:36-42` —

```python
tab_bitget, tab_kospi, tab_nasdaq = st.tabs(["📡 Bitget", "🇰🇷 KOSPI", "🇺🇸 NASDAQ"])
with tab_bitget: bitget.render(st)
with tab_kospi:  kospi.render(st)
with tab_nasdaq: nasdaq.render(st)
```

탭 클릭은 CSS 토글일 뿐, 서버 측 스크립트는 세 탭 본문을 모두 실행. → Bitget 탭만 보고 싶어도 KOSPI 949 종목 계산이 무조건 일어남.

### 2-2. KOSPI는 949 종목 × 2 회 풀스캔

`dashboards/live/kospi.py:282-309` 에서 동일 종목 집합에 대해 두 번 풀스캔:

- `_cached_reference_levels(tuple(codes_all))` — parquet 1500봉씩 949회 read → MA × {1d,1w,1M}, HL × {7d,28d,90d,1y,5y}
- `_cached_recommendations(tuple(codes_all))` — **같은 parquet 재read** + 4 전략 점수 (trend_chase 1d/1w, trend_pullback 1d/1w, quiet_bottom 1w)

콜드 캐시일 때 ≈ 1900회 parquet read.

### 2-3. `trend_chase`의 비벡터화 `rolling.apply` — 실제 CPU 병목

`backtest/strategies/trend_chase.py:104-107` —

```python
amt.rolling(lb, min_periods=min(60, lb)).apply(
    lambda x: (x[-1] >= np.quantile(x, p["amount_pctl_min"])) * 1.0,
    raw=True,
)
```

`lb=250`. 매 바마다 Python 콜백으로 `np.quantile` 호출. 1500봉 × 949종목 × (1d+1w) ≈ 280만 호출.

### 2-4. `@st.cache_data(ttl=...)` 는 서버 재시작 시 휘발

`kospi.py:129, 134, 147, 176`. TTL 만료 또는 서버 재기동 후 첫 접속마다 위 비용을 처음부터 부담.

---

## 3. Streamlit-native 해결안 (2-layer)

### Layer 1 — Lazy tab execution (Streamlit ≥ 1.55, 2026-03 도입)

[공식 문서](https://docs.streamlit.io/develop/api-reference/layout/st.tabs) 의 `on_change="rerun"` + `TabContainer.open` 패턴.

```python
# dashboards/pages/3_Live.py
tab_bitget, tab_kospi, tab_nasdaq = st.tabs(
    ["📡 Bitget", "🇰🇷 KOSPI", "🇺🇸 NASDAQ"],
    on_change="rerun",          # ← 탭 전환 시 전체 rerun
    key="live_active_tab",
)

if tab_bitget.open:             # ← 활성 탭만 본문 실행
    with tab_bitget:
        bitget.render(st)
if tab_kospi.open:
    with tab_kospi:
        kospi.render(st)
if tab_nasdaq.open:
    with tab_nasdaq:
        nasdaq.render(st)
```

→ Live 페이지 첫 진입 시 Bitget만 계산. KOSPI 탭을 실제로 클릭해야 KOSPI 본문이 처음 실행됨.

### Layer 2 — `@st.cache_data(persist="disk")` 로 재시작에도 캐시 유지

[Caching 공식 문서](https://docs.streamlit.io/develop/concepts/architecture/caching) — `persist="disk"` 는 결과를 `~/.streamlit/cache/` 에 pickle 로 저장. 서버 재기동·다른 사용자 세션 모두 디스크 캐시 공유.

```python
# dashboards/live/kospi.py
@st.cache_data(persist="disk", show_spinner=False)
def _cached_reference_levels(symbols_tuple: tuple, version: str) -> pd.DataFrame:
    return compute_reference_levels(list(symbols_tuple), cache_loader=_cached_cache_tails)

@st.cache_data(persist="disk", show_spinner=False)
def _cached_recommendations(symbols_tuple: tuple, version: str) -> pd.DataFrame:
    ...
```

**주의**: `persist="disk"` 는 TTL 을 무시. 캐시 무효화 키를 명시 — fetch_log mtime 을 version 으로:

```python
version = str(int(_FETCH_LOG.stat().st_mtime)) if _FETCH_LOG.exists() else "0"
refs = _cached_reference_levels(tuple(codes_all), version)
```

"KOSPI 데이터 받기" 버튼으로 fetch_log 가 갱신될 때만 캐시 무효화. 그 외에는 영구 보존.

---

## 4. 효과 비교

| 시나리오 | 현재 | Layer 1만 | Layer 1+2 |
|---|---|---|---|
| Live 첫 진입 (Bitget 탭) | KOSPI+NASDAQ 모두 계산 | Bitget만 | Bitget만 |
| KOSPI 첫 클릭 (서버 켜진 후 최초) | (이미 계산됨) 즉시 | ~30s 계산 | ~30s 계산 |
| KOSPI 두 번째 클릭 (TTL 내) | 즉시 | 즉시 | 즉시 |
| **서버 재시작 후 KOSPI 첫 클릭** | **~30s** | **~30s** | **즉시 (디스크)** |
| 다른 사용자 KOSPI 첫 클릭 | ~30s | ~30s | 즉시 (공유) |

---

## 5. 실행 순서

1. **호환성 점검** — `streamlit>=1.55` 가 현재 `streamlit-aggrid`, `streamlit-lightweight-charts` 와 호환되는지 확인.
   - 현재 설치: `streamlit==1.50.0`.
   - 별도 브랜치에서 작업 권장 (st-aggrid 가 streamlit major bump 에 민감).
2. **Layer 1 적용** — `dashboards/pages/3_Live.py` 만 수정 (≈ 5줄).
3. **Layer 2 적용** — `dashboards/live/kospi.py`, `dashboards/live/nasdaq.py` 의 캐시 데코레이터에 `persist="disk"` + fetch_log mtime version 키 추가.
4. **(보너스) `trend_chase.py` 벡터화** — `amt.rolling(250).quantile(0.70)` 후 비교 한 번. Layer 2 의 "최초 1회 콜드 빌드" 시간을 단축. Layer 1+2 적용 후엔 우선순위 낮음.

---

## 6. 호환성 확인용 명령

```powershell
# 현재 버전
.venv/Scripts/python.exe -c "import streamlit, st_aggrid, streamlit_lightweight_charts as lwc; print('st', streamlit.__version__); print('agg', st_aggrid.__version__); print('lwc', getattr(lwc, '__version__', 'n/a'))"

# 업그레이드 (별도 브랜치에서)
.venv/Scripts/python.exe -m pip install -U "streamlit>=1.55" streamlit-aggrid streamlit-lightweight-charts
```

업그레이드 후 회귀 점검 포인트:
- AgGrid 의 `JsCode` / `GridOptionsBuilder` API
- `streamlit-lightweight-charts` 의 `renderLightweightCharts` 시그니처
- `st.dialog`, `st.fragment`, `st.segmented_control` 동작 (Live 페이지에서 사용 중)

---

## 7. 참고 링크

- [st.tabs — Streamlit Docs](https://docs.streamlit.io/develop/api-reference/layout/st.tabs)
- [2026 release notes](https://docs.streamlit.io/develop/quick-reference/release-notes/2026) — v1.55.0 에서 `on_change` 도입
- [Caching overview](https://docs.streamlit.io/develop/concepts/architecture/caching)
- [st.cache_data](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data) — `persist="disk"` 는 TTL 무시
- [Working with fragments](https://docs.streamlit.io/develop/concepts/architecture/fragments)
