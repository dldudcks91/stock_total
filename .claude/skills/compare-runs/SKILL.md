---
name: compare-runs
description: 두 백테스트 런 디렉터리의 metrics.json, config.yaml, equity 곡선을 나란히 비교해 콘솔 표(+옵션 CSV)로 출력. 디렉터리 이름만 줘도 backtest/runs/ 하위에서 자동으로 찾고, 모든 metric에 대해 delta(B-A)를 계산. strategy/symbol/interval이 다르면 경고 후 진행.
---

# /compare-runs

두 백테스트 런을 비교하는 워크플로우.

## 트리거

```
/compare-runs <RUN_A> <RUN_B>
```

`<RUN_A>` / `<RUN_B>` 는 다음 둘 다 허용:

- 디렉터리 **이름**만 (예: `20260510-120000_sma_cross_BTCUSDT`)
  -> `backtest/runs/<이름>/` 에서 자동으로 찾음
- 절대/상대 **경로** (예: `backtest/runs/20260510-...` 또는 `D:/runs/foo`)

## 사용 예

```bash
# 디렉터리 이름만 (backtest/runs/ 아래에서 검색)
python -m backtest.compare 20260510-120000_sma_cross_BTCUSDT 20260510-130000_sma_cross_BTCUSDT

# 경로 직접
python -m backtest.compare ./backtest/runs/20260510-120000_sma_cross_BTCUSDT D:/snapshots/run_x

# CSV 동시 저장
python -m backtest.compare RUN_A RUN_B --csv compare.csv
```

## 옵션

| 옵션 | 설명 |
|---|---|
| `RUN_A`, `RUN_B` (positional) | 비교할 두 런. 디렉터리 이름 또는 경로 |
| `--csv PATH` | 비교 결과를 CSV로 저장. section / metric / A / B / delta 컬럼 |

## 출력 섹션

1. **경고** — `strategy`, `symbol`, `interval` 중 하나라도 다르면 경고 라인 출력 후 진행
2. **metrics.json** — `metrics.json` 의 모든 키를 그대로 출력. `delta = B - A` (숫자만)
3. **config diff** — `config.yaml` 의 평탄화된 키 중 값이 다른 키만 (params 깊이까지 포함)
4. **equity** — 두 런의 `equity.parquet` 을 동일 timestamp 교집합으로 잘라 정렬한 뒤 다음을 재계산:
   - `final_equity`
   - `max_drawdown`
   - `sharpe_recalc` (interval에 맞는 연환산: 1h=24*365, 4h=6*365, 1d=365, 1w=52)
   - `n_points`

## 출력 예시

```
== metrics.json ==
metric             A=20260510-120000_sma_cross_BTCUSDT  B=20260510-130000_sma_cross_BTCUSDT  delta
total_return       0.1234                               0.2345                               +0.1111
sharpe             1.20                                 1.85                                 +0.65
mdd                -0.15                                -0.10                                +0.05
n_trades           42                                   58                                   +16
win_rate           0.55                                 0.60                                 +0.05

== config diff (different keys only) ==
key                A=...                                B=...
params.fast        10                                   20
params.slow        50                                   100

== equity (intersection: 8760 points) ==
metric             A=...                                B=...                                delta
final_equity       11234.0                              12345.0                              +1111
max_drawdown       -0.15                                -0.10                                +0.05
sharpe_recalc      1.21                                 1.84                                 +0.63
n_points           8760                                 8760                                 0
```

## 에러 처리

- `metrics.json` / `config.yaml` / `equity.parquet` 누락 시 `FileNotFoundError` 와 친절한 메시지 (어느 런 디렉터리의 어떤 파일이 없는지)
- 디렉터리 이름이 `backtest/runs/` 아래에도 없고 경로로도 없으면 `FileNotFoundError`

## 호출 절차 (Claude가 사용자에게 안내할 때)

1. 사용자가 두 런을 명시했는지 확인. 없으면 `ls backtest/runs/` 로 후보 보여주기
2. `python -m backtest.compare RUN_A RUN_B [--csv ...]` 실행
3. 경고가 떴으면(strategy/symbol/interval 불일치) 사용자에게 의도된 비교인지 한 번 확인
