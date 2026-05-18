# trend_pullback (분석)

`backtest/strategies/trend_pullback` 전략의 기초가 되는 이벤트 스터디 / 분포 분석 모음.

## 핵심 가설

1H 봉에서 **임펄스** (큰 양봉) 가 발생한 후, 가격이 MA10 또는 MA20 으로 **눌림** (pullback) 하고 다시 반등하는 패턴. 진입 후 168h(1주) 까지의 forward returns 분포로 어떤 sub-pattern 이 robust 한지 발견.

## 분석 모듈

전부 `/study` 스킬 + `--config <run_dir>/config.json` 패턴 사용.

| 모듈 | 입력 | 출력 |
|---|---|---|
| `angle_study.py` | 1H 캐시 + 1W MA20 slope > 0 게이트 + 임펄스/거래량 필터 | `events.parquet`, `angle_study_summary.csv` |
| `full_grid.py` | `events.parquet` | `full_grid_summary.csv` (wick×bars×angle, MA10) |
| `full_grid_ma20.py` | `events.parquet` | `full_grid_ma20_summary.csv` (MA20) |
| `upper_wick_study.py` | `events.parquet` | `upper_wick_summary.csv` |
| `btc_regime.py` | `events.parquet` + BTC 1D | 콘솔 표 |
| `size_table.py` | (자체 collect) | `size_table_events.parquet`, `size_table_summary.csv` |
| `monthly_dist.py` | `events.parquet` | `monthly_dist.csv` |
| `visualize.py` | `events.parquet` + 1H 캐시 | `<label>_visualize.png` (cell candle 차트) |

## 표준 워크플로우

```bash
# 1. 새 run 폴더 생성
/study init trend_pullback {name}

# 2. config.json 의 params 채우기 (impulse_min, vol_mult_min, touch_pad 등)

# 3. 이벤트 수집 (이게 다른 분석의 입력)
.venv/Scripts/python.exe -m scripts.trend_pullback.angle_study \
    --config scripts/trend_pullback/runs/{ts}_{name}/config.json

# 4. cross-tab 분석들
.venv/Scripts/python.exe -m scripts.trend_pullback.full_grid \
    --config scripts/trend_pullback/runs/{ts}_{name}/config.json
.venv/Scripts/python.exe -m scripts.trend_pullback.upper_wick_study \
    --config scripts/trend_pullback/runs/{ts}_{name}/config.json
# ... 등

# 5. 시각화 (특정 cell)
.venv/Scripts/python.exe -m scripts.trend_pullback.visualize \
    --out-dir scripts/trend_pullback/runs/{ts}_{name}/ \
    --bars-lo 1 --bars-hi 3 \
    --angle-lo -0.0773 --angle-hi -0.0345 \
    --wick-lo -1.0 --wick-hi 0.01 \
    --label "W_low_bars1-3_Q4" --title "W_low × bars 1-3 × Q4" --all

# 6. 마감
/study finalize scripts/trend_pullback/runs/{ts}_{name}/
```

## runs/

각 run 폴더는 그 시점의 게이트·임펄스 임계값으로 만든 분석 1세트. 옛 run 도 보존 (재현용).

자세한 표준: [CLAUDE.md](../../CLAUDE.md) "분석 run 폴더 표준" 섹션.
