---
name: launch-dashboard
description: Streamlit 멀티페이지 대시보드(`dashboards/app.py`)를 실행한다. 사이드바에서 Backtest(단일 런 뷰어) / Compare(멀티 런 비교) / Realtime(스텁) 페이지를 전환한다. 백테스트 결과를 시각화하거나 여러 런을 비교하고 싶을 때 사용한다.
---

# launch-dashboard

Streamlit 멀티페이지 대시보드를 실행하는 스킬.

## 트리거

- `/launch-dashboard` — 대시보드 실행 (모든 페이지 포함)

> 옛날 `/launch-dashboard backtest` / `/launch-dashboard realtime` 형태는
> 더 이상 사용하지 않음. 단일 진입점에서 사이드바로 페이지 전환.

## 실행 명령

```bash
streamlit run dashboards/app.py
```

## 페이지 구성

| 페이지 | 파일 | 설명 |
|---|---|---|
| Home | `dashboards/app.py` | 런 인벤토리 + 최근 10개 런 요약 |
| Backtest | `dashboards/pages/1_Backtest.py` | 단일 런 뷰어 (메트릭, equity, drawdown, position 분포, trades) |
| Compare | `dashboards/pages/2_Compare.py` | 2개 이상 런 비교 (메트릭 표 + delta, equity overlay, drawdown overlay, config diff) |
| Tickers | `dashboards/pages/3_Tickers.py` | Bitget USDT-M 전 종목 라이브 시세 표 (REST `/api/v2/mix/market/tickers` 직접 폴링) |
| Realtime | `dashboards/pages/9_Realtime.py` | 외부 수집기 DB 연동 예정 (현재 스텁) |

공통 헬퍼는 `dashboards/_lib.py` 에 있음 (IO, drawdown, 시간대 변환, config diff 등).

## Backtest 페이지

- 사이드바에서 런 선택, KST/UTC 토글
- 메트릭 카드 9개 (total_return, cagr, sharpe, mdd, n_trades, win_rate, avg_pnl_pct, avg_holding_bars, n_bars)
- Equity + Drawdown 서브플롯
- Position time distribution + 최근 100건 trades 테이블

## Tickers 페이지

- 데이터 소스: 공개 REST `https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES`
- 사이드바: Auto-refresh 토글 + 주기(5/10/30/60s), 수동 Refresh, symbol 검색, Top N, 정렬 컬럼/방향, 표시 컬럼 multiselect
- 표 컬럼(기본): Symbol, Mark, 24h %, 24h High/Low, Quote Vol(USDT), Funding, Open Interest
- 24h % / Funding 은 부호에 따라 녹/적 색상
- 자동 새로고침은 `streamlit-autorefresh` 패키지 필요 (없으면 수동만)
- 수집기 DB 와 분리되어 있으므로 collector 가 안 도는 환경에서도 동작

## Compare 페이지

- 사이드바에서 **2개 이상**의 런을 multiselect 로 선택 (첫 선택이 baseline)
- KST/UTC 토글, "Equity 정규화 (start=1.0)" 토글
- strategy/symbol/interval 이 다르면 노란 경고 (compare-runs 스킬과 같은 정책)
- **Metrics**: 행=런, 열=METRIC_KEYS 표 + 첫 런 기준 delta 표 (pp = percentage point)
- **Equity Overlay**: 모든 런을 한 차트에 겹쳐 그림. 정규화 ON 시 각 런의 equity / equity[0]
- **Drawdown Overlay**: 모든 런의 DD 곡선 겹쳐 그림
- **Config Diff**: 평탄화한 config 키 중 **값이 다른 키만** 표시

## 포트 / 접속

- 기본 포트: **8501**
- 같은 포트가 사용 중이면 다음 빈 포트(8502, …)로 자동
- 접속: `http://localhost:8501`
- 다른 포트로 띄우고 싶으면:

  ```bash
  streamlit run dashboards/app.py --server.port 8600
  ```

## 종료

- 터미널에서 **Ctrl+C** 두 번 (PowerShell 동일)

## 트러블슈팅

- `ModuleNotFoundError: streamlit` → `pip install -r requirements.txt`
- `No runs yet.` 화면 → 먼저 `python -m backtest.engine.runner …` 로 백테스트 실행
- 외부 접속이 필요하면 `--server.address 0.0.0.0` 추가