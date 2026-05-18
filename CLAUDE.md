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
├── sources/             # 데이터 fetcher
│   ├── bitget.py        # Bitget USDT-M 1H/1D (async REST, --granularity)
│   ├── bitget_live.py   # Bitget 실시간 스냅샷 (마지막 가격/표 렌더용)
│   ├── _snapshot.py     # 스냅샷 캐시 헬퍼
│   ├── stocks.py        # FDR 기반 KR(KOSPI) / US(NASDAQ) 1D
│   ├── naver_kr.py      # 네이버 금융 KR 실시간 보조 소스
│   └── naver_us.py      # 네이버 금융 US 실시간 보조 소스
├── cache/
│   ├── crypto/
│   │   ├── 1h/{SYMBOL}.parquet
│   │   ├── 1d/{SYMBOL}.parquet
│   │   └── classification.parquet
│   ├── kr/              # {6자리코드}.parquet + _refs.parquet + _recs.parquet
│   └── us/              # {TICKER}.parquet + _refs.parquet + _recs.parquet
├── loader.py            # 자산·인터벌 무관 load_ohlcv()
├── resample.py          # 1h/1d 캐시 우선, 4h/1w/1M는 메모리 리샘플
├── classification.py    # 크립토 4그룹 분류
├── universe.py          # 분류 결과에서 그룹별 심볼 추출
└── fetch_log.py         # 마지막 fetch 시점 기록

backtest/
├── engine/              # 시그널 → 체결 → 포지션 → 성과
├── strategies/          # 한 파일 = 한 전략 (전략별 .md 리포트 동거)
├── runs/                # 런 결과 (런별 디렉터리, gitignore)
├── batch_runner.py      # 다중 전략·심볼 일괄 실행
└── compare.py           # 런 비교 (skill 백엔드)

research/                # KR 종목 종합 리서치 (옛 stock_research 흡수)
├── collect.py           # FDR 일봉 단일 종목 헬퍼
├── analyze.py           # 정량 지표 (자산 무관)
├── broker_report.py     # 한경 컨센서스 크롤
├── pdf_parse.py         # PDF에서 목표주가/투자의견 추출
├── dart.py              # DART OpenAPI
├── financials.py        # PDF 추정치 표 파싱
├── industry.py          # KSIC 업종/피어
├── report.py            # 종합 리포트 통합 (CLI)
├── reports/             # 산출 마크다운 리포트 (gitignore)
├── cache/               # 한경 PDF·DART JSON 캐시 (gitignore)
└── analysis/            # 정량 분석 결과 JSON (gitignore)

dashboards/              # Streamlit 멀티페이지
├── app.py               # 엔트리
├── charts.py            # 차트 빌더 (Plotly)
├── _cache.py / _lib.py / _stock_grid.py
├── _precompute.py       # KR/US 지표·추천 디스크 캐시 (refs/recs.parquet writer/reader)
└── pages/
    ├── 1_Backtest.py    # 단일 런 뷰어
    ├── 2_Compare.py     # 멀티 런 비교
    ├── 3_Bitget.py      # 크립토 표
    ├── 4_KOSPI.py       # KR 표
    ├── 5_NASDAQ.py      # US 표
    └── 6_Mobile.py      # 모바일 보기

scripts/                 # 단발/배치 스크립트 (자세히: scripts/README.md)
├── quiet_bottom/        # quiet_bottom 전략 분석·검증·플롯 (서로 import)
├── spring/              # spring 패턴 스캔 (실험)
├── misc/                # 수집·마이그레이션·스모크·벤치 등
├── out/                 # 결과물 (CSV·PNG·log, git tracked)
└── README.md

docs/                    # 영구 문서
├── classification.md    # 크립토 4그룹 분류 규칙
├── results/             # 분석 결과 artifact (보존용)
└── reference/           # 외부 자료 정리 (e.g. 단테 검색기)

notebooks/               # 임시 탐색용 (.py 모듈로 옮긴 뒤 비움)
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

## KR/US 대시보드 데이터 흐름 (3-단)

라이브 탭(`pages/3_Live.py`)의 KOSPI / NASDAQ 표는 **3개 인풋을 머지**한다:

1. **실시간 스냅샷** — `data/cache/{asset}/_live_snapshot.parquet`
   - Naver 비공식 endpoint (`naver_kr` / `naver_us`)로 가격·거래대금·시총만 1회 fetch
   - "라이브 가격 갱신" 버튼이 백그라운드 subprocess로 갱신
2. **지표 (refs/recs)** — `data/cache/{asset}/_refs.parquet`, `_recs.parquet`
   - **`dashboards/_precompute.py`** 가 일봉 캐시 parquet 들을 읽어 한 번 계산해 저장
   - refs = 이동평균(MA10/20 × 1d/1w/1M) + 윈도우 High/Low(7d/28d/90d/1y/5y) + prev_Nd
   - recs = 5 전략(trend_chase d/w, trend_pullback d/w, quiet_bottom w) 점수 최강 1개
   - 각 행마다 `data_mtime` 컬럼이 있어 **변경된 종목만 증분 재계산**
   - "지표 계산" 버튼 또는 자동 트리거 (FDR fetch 성공 시 자동 chaining)
   - CLI: `.venv/Scripts/python.exe -m dashboards._precompute --asset {kr|us} [--force]`
3. **일봉 OHLCV** — `data/cache/{asset}/{symbol}.parquet`
   - FDR 로 받은 원본 일봉. 차트(`render_tv_chart_stock`)와 precompute 의 입력
   - "KOSPI/NASDAQ 데이터 받기" 가 백그라운드 subprocess 로 증분 갱신

대시보드는 (1)+(2)를 cheap merge 하고 라이브 가격을 `apply_current_prices` 로 덧입혀 표시. 무거운 계산은 절대 탭 진입 시점에 일어나지 않는다 — 항상 `_precompute.py` 가 미리 디스크에 써둔다.

## Python 환경 (venv 필수)

이 프로젝트의 **모든 파이썬 실행은 프로젝트 루트의 `.venv` 를 경유**한다. 시스템(anaconda/global) 파이썬으로 실행 금지 — 의존성 격리와 재현성을 위해.

- 인터프리터: `.venv/Scripts/python.exe` (Windows) / `.venv/bin/python` (POSIX)
- streamlit / pip 등 entry-point: `.venv/Scripts/streamlit.exe`, `.venv/Scripts/pip.exe`
- venv 가 없으면 먼저 생성: `python -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.txt`
  - 이 한 줄의 `python -m venv .venv` 는 **유일하게** 허용되는 비-venv 호출 (venv 가 아직 없으므로 시스템 python 사용). 그 외 모든 곳은 항상 `.venv/Scripts/python.exe`.
- 모든 SKILL.md 와 docs 의 예시 명령은 `.venv/Scripts/python.exe -m ...` 형태로 작성.
- Claude 가 Bash 로 파이썬을 호출할 때도 반드시 `.venv/Scripts/python.exe` 사용 (그냥 `python` 금지).
- **`streamlit run ...` 처럼 entry-point 만 부르는 형태 금지** — PATH 우선순위에 따라 anaconda 의 옛 streamlit (pandas 1.5) 이 잡혀 `Invalid frequency: ME` 같이 깨진다. 항상 `.venv/Scripts/streamlit.exe run ...` 처럼 절대경로로.
- VSCode 는 `.vscode/settings.json` 으로 인터프리터·통합 터미널이 자동 venv. 다른 IDE 사용 시 동일하게 설정.

### 점검 (의심될 때)

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select-Object ProcessId, CommandLine
```

`CommandLine` 에 `anaconda` 또는 venv 외 경로가 보이면 즉시 `Stop-Process -Id <PID> -Force` 후 `.venv` 로 재기동.

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
| `study` | 분석 | scripts/<group>/runs/ 표준 폴더 init/finalize (재현성 보장) |

### 현재 전략 목록 (`backtest/strategies/`)

| 전략 | 라벨 | 자산 | 용도 | 비고 |
|---|---|---|---|---|
| `trend_pullback` | **수렴** | KR / US / Crypto | 추천 시그널 — 1차 상승 후 MA10/MA20 비비적 (눌림목) | Cycle 5 메인. KR 1d Sharpe 24.8 / US 1d 22.1 / Crypto 1h 3.3 (OOS). 청산: trail 0.25 / TP 0.30~0.35 / hold 252d |
| `trend_chase` | **추격** | KR / US / Crypto | 추천 시그널 — 장대양봉 + 거래량 폭증 | Cycle 5 보조. KR 1d Sharpe 16.0 / US 1d 10.1 (게이트 `fresh_big_th=0.08`). 청산: trail 0.15~0.20 / TP 0.30 / hold 252d |
| `quiet_bottom` | **조용한 바닥** | KR / US | 추천 시그널 (자동매매 X) — 1w binary | Cycle 5 보조. KR 1w Sharpe 6.8 / US 1w 6.4 (게이트 `dd_avg_max=-0.40`). 6 조건 (close>MA20, slope/accel 양, avg_dd_104w≤-0.45, path_R²_52w≤0.50, ret_4w≤+60%). 자세히: [QUIET_BOTTOM.md](backtest/strategies/QUIET_BOTTOM.md) |

### 현재 Agent 목록 (`.claude/agents/`)

| agent | 역할 |
|---|---|
| `stock-report` | 종목 종합 리서치 리포트 (다른 agent/skill 조합 후 마크다운 산출) |
| `industry-analysis` | 업황/업계 정성 분석 |
| `broker-consensus` | 한경 컨센서스 수집·요약 (KR) |
| `fundamentals-deep` | DART 분기 실적 (KR) |

## 분석 run 폴더 표준 (scripts/<group>/runs/)

scripts/ 안의 자유 분석은 다음 폴더 규약을 따른다 (재현성 보장).

```
scripts/<group>/                          # 큰 틀 (예: trend_pullback)
├── *.py                                   # 재사용 가능한 분석 모듈
├── README.md                              # 그룹 설명 (선택)
└── runs/                                  # 각 분석 실행 결과 (git tracked)
    └── {YYYYMMDD-HHMM}_{name}/            # KST 타임스탬프 + snake_case 이름
        ├── README.md                      # 사람용: 목적·방법·핵심 결과
        ├── REPRODUCE.md                   # 재현 명령 한 줄
        ├── config.json                    # 기계용: params + git + data + outputs
        ├── env.txt                        # python/pandas/git 버전
        └── output/                        # 산출물 (parquet/csv/png)
```

### 워크플로우

1. **`/study init <group> <name>`** — 폴더 + 골격 파일들 생성 (git commit/branch/dirty 자동 기록)
2. 분석 스크립트는 `--config <path/to/config.json>` 또는 `--out-dir <run_dir>` 로 실행. `output/` 에 저장. config.json 의 `params` / `data` / `results_summary` 자동 갱신
3. **`/study finalize <run_dir>`** — output 스캔 → README 산출물 표 + config.outputs 채움

### 공통 helper

`scripts/_common/run_helper.py`:
- `parse_args(add_args, defaults, description)` → `(out_dir, params, args)` 반환
- `update_config(cfg_path, **updates)` → config.json deep-merge
- `resolve_config_path(args)` → 현재 실행의 config.json 경로

### 분석 모듈 인터페이스

```python
def main():
    global IMPULSE_RET_MIN, ...   # 모듈 상수 덮어쓰기용 (있으면)
    from scripts._common.run_helper import parse_args, update_config, resolve_config_path
    def add_args(ap):
        ap.add_argument("--impulse-min", type=float, default=None)
    out_dir, params, args = parse_args(add_args, {"impulse_min": 0.07}, "...")
    # ... 분석, out_dir 에 저장
    cfg_path = resolve_config_path(args)
    if cfg_path:
        update_config(cfg_path, params={...}, data={...}, results_summary={...})
```

### 원칙

- **`scripts/out/` 단일 폴더에 덮어쓰기 금지** — 항상 run 폴더 격리
- **모든 run 폴더는 git tracked** (`output/*.parquet` 큰 파일이면 gitignore 추가 고려)
- **`git_dirty=true` 면 finalize 시 경고** — 정확한 재현 보장 X
- **KST 타임스탬프** (UTC 아님)
- **분석 history 자동 보존** — 옛 run 폴더는 삭제하지 않음 (참조용)

## 데이터 접근 컨벤션

- **크립토**: 백테스트/대시보드는 항상 `from data.resample import load` 로만. 캐시 직접 read 금지.
- **KR 주식**: `from research.collect import load_daily, fetch_daily` 또는 직접 `data/cache/kr/{ticker}.parquet` parquet read.
- **US 주식**: `data/cache/us/{ticker}.parquet` 직접 read 또는 추후 공통 loader 추가.

자산을 가로지르는 추상 loader: `data.loader.load_ohlcv(asset, symbol, interval)` 사용 가능 (crypto: 1h/4h/1d/1w, kr/us: 1d/1w).
