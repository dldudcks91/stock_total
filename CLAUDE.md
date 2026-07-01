# research_lab (옛 crypto_backtest)

크립토 + KOSPI + NASDAQ 통합 리서치 / 추천 시그널 / 대시보드 (개인 연구용).

> 프로젝트 디렉터리 이름은 추후 리네임 예정. 코드/문서상 명칭은 자유롭게 사용.

## 구성 요약

- **데이터 수집** — Bitget(crypto 1H/1D), FinanceDataReader(KR/US 1D), 한경 컨센서스(KR 정성), DART(KR 펀더멘털)
- **추천 시그널** — `ma_touch` 단일 룰 (KR / Crypto / NASDAQ 공통). 자세한 룰: `docs/strategies_v2_design.md`
- **리서치 리포트** — KR 종목 종합 리서치 (정량+정성 통합 마크다운 리포트)
- **대시보드** — Streamlit 멀티페이지 (Live / Map / Mobile)

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
│   ├── kr/              # {6자리코드}.parquet + _refs.parquet + _recs.parquet + _ma_touch.parquet + _live_snapshot.parquet
│   └── us/              # {TICKER}.parquet + _refs.parquet + _recs.parquet + _ma_touch.parquet + _live_snapshot.parquet
├── loader.py            # 자산·인터벌 무관 load_ohlcv()
├── resample.py          # 1h/1d 캐시 우선, 4h/1w/1M는 메모리 리샘플
├── classification.py    # 크립토 분류 (`tier_final` 6그룹 + benchmark/stable)
├── universe.py          # 분류 결과에서 그룹별 심볼 추출
└── fetch_log.py         # 마지막 fetch 시점 기록

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
├── live/                # 자산별 라이브 렌더러 (bitget.py / kospi.py / nasdaq.py + 헬퍼)
└── pages/
    ├── 3_Live.py        # 라이브: Bitget / KOSPI / NASDAQ 탭
    ├── 4_Map.py         # 시장 지도 (히트맵)
    └── 6_Mobile.py      # 모바일 보기

scripts/                 # 자산별 분석·추천 (자세히: scripts/README.md)
├── _common/             # 자산 무관 유틸 (signals / mtf_* / recommend_runner / build_recs_table)
├── kr/ma_touch/         # KOSPI: recommend.py
├── crypto/ma_touch/     # Bitget: recommend.py + universe filter
├── nasdaq/ma_touch/     # NASDAQ: recommend.py
└── README.md

docs/                    # 영구 문서
├── strategies_v2_design.md   # ma_touch 룰 정의 (운영 표준)
├── classification.md         # 크립토 분류 규칙 (tier_final)
├── granville_quadratic_fit.md / ma_converge_exploration.md  # R&D 노트 (탐색 단계)
└── reference/                # 외부 자료 정리
```

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
   - recs = ma_touch 게이트(`symbol, gate_pass`) — `gate_pass` = 오늘 ma_touch 가 ≥1 TF 통과. `/recs` 스킬과 동일 신호(`scripts._common.recommend_runner` 재사용). 그리드의 `터치` ● 컬럼
   - 각 행마다 `data_mtime` 컬럼이 있어 **변경된 종목만 증분 재계산**
   - "지표 계산" 버튼 또는 자동 트리거 (FDR fetch 성공 시 자동 chaining)
   - CLI: `.venv/Scripts/python.exe -m dashboards._precompute --asset {kr|us} [--force]`
3. **일봉 OHLCV** — `data/cache/{asset}/{symbol}.parquet`
   - FDR 로 받은 원본 일봉. 차트(`render_tv_chart`)와 precompute 의 입력
   - "KOSPI/NASDAQ 데이터 받기" 가 백그라운드 subprocess 로 증분 갱신

대시보드는 (1)+(2)를 cheap merge 하고 라이브 가격을 `apply_current_prices` 로 덧입혀 표시. 무거운 계산은 절대 탭 진입 시점에 일어나지 않는다 — 항상 `_precompute.py` 가 미리 디스크에 써둔다.

## 데이터 업데이트 표준

사용자가 **"데이터 업데이트"** / **"데이터 받아와"** / **"오늘 데이터로 갱신"** 같이 일반적인
갱신 요청을 하면, **아래 5단계를 모두** 실행한다. 일부만 받고 멈추지 말 것 — 표/차트가
부분만 최신이 되어 사용자가 혼동한다. 특정 자산만 갱신하라는 명시 요청(예 "KR만 받아",
"라이브만") 일 때만 해당 단계만 실행.

| 순서 | 자산 | 명령 | 비고 |
|---|---|---|---|
| 1 | KR 일봉 | `.venv/Scripts/python.exe -m data.sources.stocks --market KOSPI` | 과거 OHLCV (KST 종가) |
| 1 | US 일봉 | `.venv/Scripts/python.exe -m data.sources.stocks --market NASDAQ` | 과거 OHLCV (EST 종가). KR 과 병렬 OK |
| 1 | Crypto 1d | `.venv/Scripts/python.exe -m data.sources.bitget --granularity 1d` | Stocks 와 다른 API라 병렬 OK |
| 1 | Crypto 1h | `.venv/Scripts/python.exe -m data.sources.bitget --granularity 1h` | 증분 모드에선 1d 와 병렬 OK (cold 모드에선 순차) |
| 2 | KR 라이브 | `.venv/Scripts/python.exe -m data.sources.naver_kr` | `_live_snapshot.parquet` 갱신, ~수초 |
| 2 | US 라이브 | `.venv/Scripts/python.exe -m data.sources.naver_us` | 위와 동일 |
| 2 | Crypto 라이브 | `.venv/Scripts/python.exe -m data.sources.bitget_live` | Bitget tickers + CoinGecko mcap, ~수초 |
| 3 | 지표 precompute | `.venv/Scripts/python.exe -m dashboards._precompute --asset all` | refs + recs (ma_touch). **반드시 1단계 완료 후**. 인크리멘털 자동. |

**주의**:
- 1단계 (과거 OHLCV) 와 2단계 (라이브 스냅샷) 는 의존 관계가 없으므로 병렬로 동시 실행 가능.
- 3단계 (precompute) 는 1단계 결과를 입력으로 쓰므로 **반드시 1단계 완료 후** 실행.
- 라이브 스냅샷은 1회 endpoint 호출로 끝나는 가벼운 작업 (각 ~수초) — 빠지면 표의 현재가/시총
  컬럼이 며칠 전 값으로 굳어진다.
- 자동매매가 아니라 추천만 띄우는 프로젝트 특성상 라이브 스냅샷이 빠지면 의사결정이
  옛 가격 기준으로 일어나므로 위험. 빼놓고 진행 금지.

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
| `crypto-visual-review` | crypto | 차트 PNG 시각 판독 + 사이클/액션/볼륨 채점 (5 TF: 1h/4h/1d/1w/1m, review 채점은 1m+1w+1d, entry 정량은 1d+4h+1h) |
| `kr-fetch` | KR | FDR로 KOSPI 일봉 다운로드 |
| `us-fetch` | US | FDR로 NASDAQ 일봉 다운로드 |
| `plot-chart` | 전 자산 | Bitget 스타일 캔들+MA+거래량+RSI Plotly 차트 |
| `launch-dashboard` | UI | Streamlit 실행 |
| `study` | 분석 | scripts/<group>/runs/ 표준 폴더 init/finalize (재현성 보장) |
| `recs` | 전 자산 | 오늘 기준 ma_touch 통과 종목 표 (KR/Crypto/NASDAQ 분리) — 사용자 지정 12 컬럼 |

### 현재 전략 목록 (`scripts/{kr,crypto,nasdaq}/ma_touch/`)

| 전략 | 라벨 | 자산 | 룰 |
|---|---|---|---|
| `ma_touch` | **MA 터치 (단일 룰)** | KR / Crypto / NASDAQ | 정배열(MA10>MA20 + close>MA20) + slope+ + 롱 부등식 터치 (today_low − MA ≤ 0.2 × range_7) |

자세한 룰: [docs/strategies_v2_design.md](docs/strategies_v2_design.md). 본체 코드: `scripts/_common/signals.py`.

> **trader 신조**: "시작 전 무조건 찍고 간다" — MA10/MA20 터치 자리만 진입. 추격 자리 (`trend_strong`) 와 전환 자리 (`golden_cross`) 는 후순위 (미구현).

### 현재 Agent 목록 (`.claude/agents/`)

| agent | 역할 |
|---|---|
| `stock-report` | 종목 종합 리서치 리포트 (다른 agent/skill 조합 후 마크다운 산출) |
| `industry-analysis` | 업황/업계 정성 분석 |
| `broker-consensus` | 한경 컨센서스 수집·요약 (KR) |
| `fundamentals-deep` | DART 분기 실적 (KR) |
| `crypto-visual-reviewer` | 크립토 차트 PNG batch 를 schema v2.1 로 채점 (Sonnet 4.6 고정, SKILL 경유 호출) |

## 분석 run 폴더 표준 (scripts/<asset>/<strategy>/runs/)

scripts/ 는 최상위가 **자산** (kr / crypto / nasdaq), 그 아래가 **strategy** (현재 `ma_touch` 만 — 추후 `golden_cross`/`trend_strong` 추가 예정).
strategy 폴더 안에서만 `runs/` 가 생성된다.

```
scripts/<asset>/<strategy>/              # 예: scripts/crypto/trend_pullback/
├── scoring.py                            # 점수 함수 (df → Series, numeric)
├── scoring_label.py                      # 선택: visual label + facts 점수
├── backtest.py                           # _common.backtest_runner 호출
├── recommend.py                          # 해당 strategy 단독 추천
├── *.py                                  # 추가 분석 모듈
├── PLAN.md / README.md                   # 그룹 설명 (선택)
└── runs/                                 # 각 분석 실행 결과 (git tracked)
    └── {YYYYMMDD-HHMM}_{name}/           # KST 타임스탬프 + snake_case 이름
        ├── README.md                     # 사람용: 목적·방법·핵심 결과
        ├── REPRODUCE.md                  # 재현 명령 한 줄
        ├── config.json                   # 기계용: params + git + data + outputs
        ├── env.txt                       # python/pandas/git 버전
        └── output/                       # 산출물 (parquet/csv/png)
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
