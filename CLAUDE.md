# cryto_backtest

크립토 백테스팅 + 데이터 분석 + 대시보드 (개인 연구용).

## 디렉터리 규약

- `data/cache/` — parquet 캐시. 파일명: `bitget_{SYMBOL}_1h.parquet` (예: `bitget_BTCUSDT_1h.parquet`)
- 1시간 봉만 저장. 4H/1D/1W는 `data.resample.load(symbol, interval)`로 즉석 생성
- `backtest/engine/` — 백테스트 엔진 (시그널 → 체결 → 포지션 → 성과)
- `backtest/strategies/` — 전략 구현. 한 파일 = 한 전략
- `backtest/runs/` — 백테스트 결과 (런별 디렉터리)
- `dashboards/` — Streamlit 앱
- `notebooks/` — 임시 탐색용

## 런 디렉터리 규약

`backtest/runs/{YYYYMMDD-HHMMSS}_{strategy}_{symbol}/`
- `config.yaml` — 사용한 파라미터
- `trades.parquet` — 체결 로그
- `equity.parquet` — 자본 곡선
- `metrics.json` — 샤프, MDD, 승률 등

## 데이터 스키마

OHLCV 컬럼: `timestamp`(UTC ms), `open`, `high`, `low`, `close`, `volume`(코인 수량), `amount`(거래대금 USDT).
타임스탬프는 항상 UTC. 표시할 때만 KST로 변환.
심볼 포맷은 Bitget 원본 (`BTCUSDT`, 슬래시·콜론 없음).

## 외부 의존

실시간 시세 수집기는 별도 프로젝트 (`crypto_realtime_collector`). 이 프로젝트는 그 DB를 **읽기만** 함.

## 코딩 원칙

- 백테스트는 **벡터화 우선** (pandas/numpy). 루프는 정말 필요할 때만
- 룩어헤드 바이어스 금지: 시그널은 `t` 시점, 체결은 `t+1` 시점
- 수수료/슬리피지는 명시적으로 (기본값에 의존 X)
