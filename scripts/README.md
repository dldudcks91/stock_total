# scripts/

자산별 분석·추천·백테스트 스크립트. 최상위는 **자산**, 그 아래는 **strategy** 폴더로 정리.

## 디렉터리

```
scripts/
├── _common/                       # 자산 무관 유틸 (3개 strategy-agnostic 모듈 + run_helper)
│   ├── indicators.py              # compute_indicators + compute_weekly_acc (KR/US df)
│   ├── facts_loader.py            # load_fresh_facts + load_visual_label
│   ├── backtest_runner.py         # run_backtest + analyze_*
│   └── run_helper.py              # /study run 패턴 helper
├── kr/                            # KOSPI
│   ├── recommend_all.py           # 사용자 표준 통합 추천 (pullback+chase, visual label-based)
│   ├── backtest_all.py            # 두 strategy 동시 채점 백테스트 (numeric)
│   ├── v3_score_validation.py     # 백테스트 결과 차별력 검증
│   ├── _common/
│   │   └── top_gainers.py         # 일간 상승률 TOP N (strategy-agnostic)
│   ├── trend_pullback/
│   │   ├── scoring.py             # score_pullback / _v3 (numeric, df-based)
│   │   ├── scoring_label.py       # score_pullback_label (visual+facts)
│   │   ├── backtest.py            # pb 단독 백테스트
│   │   └── recommend.py           # v3 numeric 단독 추천
│   ├── trend_chase/               # 동일 구조 (score_chase ~ v5_1)
│   ├── quiet_bottom/.gitkeep      # 향후 KR quiet_bottom 분석 자리
│   └── cascading_pullback/.gitkeep
├── crypto/                        # Bitget 크립토
│   ├── _common/
│   │   ├── rec_now.py             # 오늘 추천 (entry_score, multi-TF facts)
│   │   ├── scan_facts_all.py      # 전체 코인 facts 갱신 (data writer)
│   │   └── review_rank.py         # visual_review 점수 단순 랭킹
│   ├── trend_pullback/            # 본격 1H 임펄스 → MA 터치 패턴 분석 (18+ 파일)
│   │   ├── angle_study.py / full_grid.py / upper_wick_study.py / ...
│   │   ├── triple_signal.py       # facts + trend_pullback + reviews 합산
│   │   ├── facts_comparison_backtest.py  # facts vs trend_pullback 백테스트
│   │   ├── facts_top10_hit_rate.py
│   │   ├── facts_strat_top10_compare.py
│   │   └── runs/                  # /study run 결과들
│   ├── cascading_pullback/        # cascading_pullback 검증 (multi-TF 1h/4h/1d)
│   │   ├── smoke.py / trace.py / trace_1h.py
│   │   ├── backtest.py            # 1h × 3일 전수 백테스트
│   │   └── table_view.py
│   ├── ma20w_short/               # 주봉 slope_4w<0 숏 패턴
│   ├── trend_chase/.gitkeep       # 향후 crypto chase 분석
│   └── quiet_bottom/.gitkeep
├── nasdaq/                        # NASDAQ — 향후 작업 자리 (모두 빈 폴더)
│   ├── trend_pullback/.gitkeep
│   ├── trend_chase/.gitkeep
│   ├── quiet_bottom/.gitkeep
│   └── cascading_pullback/.gitkeep
└── out/                           # 일회성 결과물 (parquet/csv/log) — runs/ 가 아닌 짧은 산출물
```

## 규약 (모든 자산 폴더 동일)

- **자산 폴더 평면** = strategy-agnostic 유틸 또는 multi-strategy 통합 entry (예: `kr/recommend_all.py`, `kr/backtest_all.py`)
- **자산/strategy/scoring.py** = 점수 함수 (df → Series, numeric)
- **자산/strategy/scoring_label.py** = visual label + facts 점수 (선택적, label 시스템 쓸 때만)
- **자산/strategy/backtest.py** = `_common.backtest_runner.run_backtest(scoring_fns={...})` 호출
- **자산/strategy/recommend.py** = 해당 strategy 단독 추천
- **자산/strategy/runs/{ts}_{name}/** = /study 표준 run 폴더 (분석 history)

## 신규 strategy 추가 시

1. 모든 자산 폴더에 같은 strategy 폴더 미리 깔아둠 (.gitkeep 으로 빈 폴더 OK)
2. 한 자산에서 본격 작업 시작하면 그 자산의 strategy 폴더에 scoring/backtest/recommend 작성
3. 점수 함수만 strategy 폴더, 백테스트 harness 는 `_common.backtest_runner` 재사용

## 워크플로우 (/study)

1. **`/study init <group> <name>`** — `scripts/<asset>/<strategy>/runs/{ts}_{name}/` + 골격 파일들
2. 분석 모듈 실행 (config 모드 권장):
   ```bash
   .venv/Scripts/python.exe -m scripts.<asset>.<strategy>.<module> \
       --config scripts/<asset>/<strategy>/runs/{ts}_{name}/config.json
   ```
3. **`/study finalize <run_dir>`** — output 스캔, README 산출물 섹션 + config.outputs 자동 채움

## 운영 표준 (사용자 표준 명령)

- KR 추천 (pb+ch 분리): `.venv/Scripts/python.exe -m scripts.kr.recommend_all --cutoff <YYYY-MM-DD>`
- KR 백테스트 (양쪽 비교): `.venv/Scripts/python.exe -m scripts.kr.backtest_all --start <date> --end <date>`
- KR 상승률 TOP: `.venv/Scripts/python.exe -m scripts.kr._common.top_gainers --date <date>`

## 원칙

- **`scripts/out/` 단일 폴더 사용 가능** — 일회성 짧은 산출물 (백테스트 parquet, recommend CSV 등). 본격 분석은 `runs/{ts}_{name}/output/` 로 격리
- 분석 history 자동 보존 (옛 run 폴더 삭제 X)
- 다른 컴퓨터에서 `--config` 만으로 동일 결과 재현 가능
