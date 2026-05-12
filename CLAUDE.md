# research_lab (옛 crypto_backtest)

크립토 + KOSPI + NASDAQ 통합 리서치 / 백테스트 / 대시보드 (개인 연구용).

> 프로젝트 디렉터리 이름은 추후 리네임 예정. 코드/문서상 명칭은 자유롭게 사용.

## 구성 요약

- **데이터 수집** — Bitget(crypto 1H/1D), FinanceDataReader(KR/US 1D), 한경 컨센서스(KR 정성), DART(KR 펀더멘털)
- **백테스트** — 벡터화 엔진, 자산 무관 (현 단계는 crypto 위주, 주식은 단계적 확장)
- **리서치 리포트** — KR 종목 종합 리서치 (정량+정성 통합 마크다운 리포트)
- **대시보드** — Streamlit 멀티페이지

## 디렉터리 규약

```
data/
├── sources/         # 데이터 fetcher
│   ├── bitget.py    # Bitget USDT-M 1H/1D (async REST, --granularity)
│   └── stocks.py    # FDR 기반 KR(KOSPI) / US(NASDAQ) 1D
├── cache/
│   ├── crypto/
│   │   ├── 1h/{SYMBOL}.parquet
│   │   ├── 1d/{SYMBOL}.parquet
│   │   └── classification.parquet
│   ├── kr/          # {6자리코드}.parquet
│   └── us/          # {TICKER}.parquet
├── resample.py      # 1h/1d 캐시 우선, 4h/1w/1M는 메모리 리샘플
├── classification.py # 크립토 4그룹 분류
└── universe.py      # 분류 결과에서 그룹별 심볼 추출

backtest/
├── engine/          # 시그널 → 체결 → 포지션 → 성과
├── strategies/      # 한 파일 = 한 전략 (전략별 .md 리포트 동거)
└── runs/            # 런 결과 (런별 디렉터리)

research/            # KR 종목 리서치 (옛 stock_research 흡수)
├── collect.py       # FDR 일봉 단일 종목 헬퍼
├── analyze.py       # 정량 지표 (자산 무관)
├── broker_report.py # 한경 컨센서스 크롤
├── pdf_parse.py     # PDF에서 목표주가/투자의견 추출
├── dart.py          # DART OpenAPI
├── financials.py    # PDF 추정치 표 파싱
├── industry.py      # KSIC 업종/피어
├── report.py        # 종합 리포트 통합 (CLI)
├── reports/         # 산출 마크다운 리포트
├── cache/           # 한경 PDF·DART JSON 캐시
└── analysis/        # 정량 분석 결과 JSON

dashboards/          # Streamlit
notebooks/           # 임시 탐색용
scripts/             # 배치 실행 스크립트
```

## 런 디렉터리 규약 (백테스트)

`backtest/runs/{YYYYMMDD-HHMMSS}_{strategy}_{symbol}/`
- `config.yaml` — 사용한 파라미터
- `trades.parquet` — 체결 로그
- `equity.parquet` — 자본 곡선
- `metrics.json` — 샤프, MDD, 승률 등

## 데이터 스키마

### Crypto (Bitget 1H/1D)
컬럼: `timestamp`(UTC ms), `open, high, low, close, volume`(코인 수량), `amount`(거래대금 USDT). 소문자.
캐시 파일: `data/cache/crypto/1h/{SYMBOL}.parquet`, `data/cache/crypto/1d/{SYMBOL}.parquet`.
4h/1w/1M는 `data.resample.load`가 메모리 리샘플로 생성 (1w/1M는 1d 캐시 우선).
심볼 포맷: Bitget 원본 (`BTCUSDT`, 슬래시·콜론 없음).

### KR/US (FDR 1D)
컬럼: `Open, High, Low, Close, Volume, Change`. 대문자. 인덱스는 `DatetimeIndex` (naive).
KR 티커: 6자리 문자열 (앞자리 0 유지).
US 티커: 영문 대문자.

> 두 스키마가 다르므로 자산을 가로지르는 코드는 정규화 후 사용.

## Python 환경 (venv 필수)

이 프로젝트의 **모든 파이썬 실행은 프로젝트 루트의 `.venv` 를 경유**한다. 시스템(anaconda/global) 파이썬으로 실행 금지 — 의존성 격리와 재현성을 위해.

- 인터프리터: `.venv/Scripts/python.exe` (Windows) / `.venv/bin/python` (POSIX)
- streamlit / pip 등 entry-point: `.venv/Scripts/streamlit.exe`, `.venv/Scripts/pip.exe`
- venv 가 없으면 먼저 생성: `python -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.txt`
- 모든 SKILL.md 와 docs 의 예시 명령은 `.venv/Scripts/python.exe -m ...` 형태로 작성.
- Claude 가 Bash 로 파이썬을 호출할 때도 반드시 `.venv/Scripts/python.exe` 사용 (그냥 `python` 금지).
- VSCode 는 `.vscode/settings.json` 으로 인터프리터·통합 터미널이 자동 venv. 다른 IDE 사용 시 동일하게 설정.

## 시간 표준

- **저장은 원본 그대로** (crypto는 UTC ms, 주식은 naive DatetimeIndex).
- **표시·로그는 KST** (Asia/Seoul) 로 통일.
- 자산을 가로지르는 비교 시 `pd.Timestamp` 로 변환 후 KST normalize.

## 코딩 원칙

- **Python 3.9 호환 유지** — PEP 604(`str | None`) 금지, `Optional[str]` 사용. PEP 585 generic은 OK (`list[str]`은 3.9에서도 동작하지만 quoted form 권장 시 따옴표).
- 실행 스크립트는 `sys.stdout.reconfigure(encoding='utf-8')` 로 Windows cp949 한글 깨짐 방지.
- 백테스트는 **벡터화 우선** (pandas/numpy). 루프는 정말 필요할 때만.
- **룩어헤드 바이어스 금지**: 시그널은 `t` 시점, 체결은 `t+1` 시점.
- 수수료/슬리피지는 명시적으로 (기본값에 의존 X).
- 노트북은 탐색용, 재사용 로직은 `.py` 모듈로.

## 비밀 관리

- DART API 키는 프로젝트 루트의 `.env` (gitignore) 에 `DART_API_KEY=...`.
- 코드/리포지토리/대화 로그에 키 평문 노출 금지.

## 외부 의존

- 실시간 시세 수집기는 별도 프로젝트 (`crypto_realtime_collector`). 이 프로젝트는 그 DB를 **읽기만** 함.

## 스킬 vs 에이전트 규칙

**Skill** (`.claude/skills/`) — 트리거 → 결과로 끝나는 단일 동작. `/{name}` 으로 호출.
**Agent** (`.claude/agents/`) — 여러 skill·도구를 순서대로 엮는 다단계 자율 작업.

판단 기준:
1. 자산마다 데이터 소스·캘린더가 다르면 → 자산별 prefix skill (`crypto-*`, `kr-*`, `us-*`)
2. 엔진/포맷이 같고 자산만 바뀌면 → 공통 skill (+`--asset` 인자)
3. 한 번에 끝나는 명령형 작업이면 → Skill
4. 수집→분석→종합 같은 다단계 자율 작업이면 → Agent

### 현재 Skill 목록 (`.claude/skills/`)

| skill | 자산 | 역할 |
|---|---|---|
| `crypto-fetch` | crypto | Bitget 1H/1D OHLCV 다운로드 (`--granularity`) |
| `crypto-classify` | crypto | BTC 벤치마크 4그룹 분류 |
| `kr-fetch` | KR | FDR로 KOSPI 일봉 다운로드 |
| `us-fetch` | US | FDR로 NASDAQ 일봉 다운로드 |
| `analyze-metrics` | 전 자산 | 이동평균·RSI·수익률·변동성 |
| `new-strategy` | 백테스트 | 전략 파일 템플릿 생성 |
| `run-backtest` | 백테스트 | 단일 전략 단일 심볼 실행 |
| `compare-runs` | 백테스트 | 두 런 메트릭 비교 |
| `plot-chart` | 전 자산 | Bitget 스타일 캔들+MA+거래량+RSI Plotly 차트 |
| `launch-dashboard` | UI | Streamlit 실행 |

### 현재 전략 목록 (`backtest/strategies/`)

| 전략 | 라벨 | 자산 | 용도 | 비고 |
|---|---|---|---|---|
| `quiet_bottom` | **조용한 바닥** | KR / US | 추천 시그널 (자동매매 X) | 1차 구현 — 6 조건 (close>MA20, slope/accel 양, avg_dd_104w≤-0.45, path_R²_52w≤0.50, ret_4w≤+60%). 자세히: [QUIET_BOTTOM.md](backtest/strategies/QUIET_BOTTOM.md) |
| `clean_dive_turn` | — | — | deprecated alias of `quiet_bottom` | 호환 유지용 |
| `ma_slope_turn_up` | — | 전 자산 | 슬로프 양 전환 진입 (실험) | quiet_bottom의 전신 |
| `weekly_trend` / `sma_cross` / `breakout_start` / ... | — | 크립토 위주 | 단순 추세/돌파 베이스라인 | |

### 현재 Agent 목록 (`.claude/agents/`)

| agent | 역할 |
|---|---|
| `stock-report` | 종목 종합 리서치 리포트 (다른 agent/skill 조합 후 마크다운 산출) |
| `industry-analysis` | 업황/업계 정성 분석 |
| `broker-consensus` | 한경 컨센서스 수집·요약 (KR) |
| `fundamentals-deep` | DART 분기 실적 (KR) |

## 데이터 접근 컨벤션

- **크립토**: 백테스트/대시보드는 항상 `from data.resample import load` 로만. 캐시 직접 read 금지.
- **KR 주식**: `from research.collect import load_daily, fetch_daily` 또는 직접 `data/cache/kr/{ticker}.parquet` parquet read.
- **US 주식**: `data/cache/us/{ticker}.parquet` 직접 read 또는 추후 공통 loader 추가.

자산을 가로지르는 추상 loader: `data.loader.load_ohlcv(asset, symbol, interval)` 사용 가능 (crypto: 1h/4h/1d/1w, kr/us: 1d/1w).
