---
name: launch-dashboard
description: Streamlit 멀티페이지 대시보드(`dashboards/app.py`)를 실행한다. 사이드바에서 Bitget / KOSPI / NASDAQ / Mobile / Chart 페이지를 전환한다. 라이브 시세 표·차트를 띄우고 싶을 때 사용한다.
---

# launch-dashboard

Streamlit 멀티페이지 대시보드를 실행하는 스킬.

## 트리거

- `/launch-dashboard` — 대시보드 실행 (모든 페이지 포함)

> 옛날 `/launch-dashboard backtest` / `/launch-dashboard realtime` 형태는
> 더 이상 사용하지 않음. 단일 진입점에서 사이드바로 페이지 전환.

## 실행 명령

```bash
.venv/Scripts/streamlit.exe run dashboards/app.py
```

## 페이지 구성

| 페이지 | 파일 | 설명 |
|---|---|---|
| Home | `dashboards/app.py` | 페이지 안내 |
| Bitget | `dashboards/pages/3_Bitget.py` | Bitget USDT-M 전 종목 라이브 시세 표 (REST `/api/v2/mix/market/tickers` 직접 폴링) |
| KOSPI | `dashboards/pages/4_KOSPI.py` | 시총 상위 KOSPI 종목 라이브 표 (Naver 비공식 `m.stock.naver.com/api/stocks/marketValue/KOSPI`) |
| NASDAQ | `dashboards/pages/5_NASDAQ.py` | 캐시된 NASDAQ 심볼 병렬 라이브 표 (Naver 비공식 per-symbol) |
| Mobile | `dashboards/pages/6_Mobile.py` | 모바일 친화 카드 리스트 (Bitget 앱 스타일) |
| Chart | `dashboards/pages/7_Chart.py` | 임의 심볼 캔들 차트 (crypto/KR/US) |

공통 헬퍼는 `dashboards/_lib.py` 에 있음 (IO, 시간대 변환 등).

## Bitget 페이지

- 데이터 소스: 공개 REST `https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES`
- 사이드바: Auto-refresh 토글 + 주기(5/10/30/60s), 수동 Refresh, "Bitget 데이터 받기"(1H+1D 백그라운드 fetch), symbol 검색, Top N, 정렬 컬럼/방향, 표시 컬럼 multiselect
- 표 컬럼(기본): Symbol, Mark, 24h %, 24h High/Low, Quote Vol(USDT), Funding, Open Interest
- 24h % / Funding 은 부호에 따라 녹/적 색상
- 자동 새로고침은 `st.fragment(run_every=...)` 빌트인 사용 — 별도 패키지 불필요
- 수집기 DB 와 분리되어 있으므로 collector 가 안 도는 환경에서도 동작

## 포트 / 접속

- 기본 포트: **8503** (`.streamlit/config.toml` 의 `[server] port` 로 고정)
- 같은 포트가 사용 중이면 다음 빈 포트(8504, …)로 자동
- 접속: `http://localhost:8503`
- 다른 포트로 띄우고 싶으면:

  ```bash
  .venv/Scripts/streamlit.exe run dashboards/app.py --server.port 8600
  ```

## 종료

- 터미널에서 **Ctrl+C** 두 번 (PowerShell 동일)

## 트러블슈팅

- `ModuleNotFoundError: streamlit` → `.venv/Scripts/pip.exe install -r requirements.txt`
- `Invalid frequency: ME` / 캐시 계산 실패 → **anaconda 등 venv 외 python 으로 streamlit 이 떠 있음**.
  `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` 로 CommandLine 에 `anaconda` 가 들어간 PID 모두 `Stop-Process -Id <PID> -Force` 후 `.venv/Scripts/streamlit.exe` 로 재기동. (pandas 2.2+ 의 `resample("ME")` 가 anaconda 의 옛 pandas 1.5 에선 깨짐.)
- 외부 접속이 필요하면 `--server.address 0.0.0.0` 추가