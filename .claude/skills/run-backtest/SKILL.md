---
name: run-backtest
description: 단일 전략을 단일 심볼·인터벌에 대해 벡터화 백테스트로 실행하고, 표준 런 디렉터리(config.yaml / equity.parquet / trades.parquet / metrics.json)를 생성한다. 룩어헤드 금지(시그널 t -> 체결 t+1), 수수료·슬리피지 명시, 1h/4h/1d/1w 지원.
---

# /run-backtest

벡터화 크립토 백테스트 워크플로우.

## 전제

- 데이터는 `data.resample.load(symbol, interval)`로 로드 (1H 캐시에서 즉석 리샘플)
- 전략 모듈은 `backtest/strategies/<NAME>.py`, 인터페이스: `NAME`, `DEFAULT_PARAMS`, `signal(df, params) -> pd.Series` (값 in {-1, 0, 1})
- 시그널은 `t`까지의 정보만 사용. 엔진이 자동으로 `t+1`로 shift (전략에서 직접 shift 금지)
- 수수료/슬리피지는 bps 단위. 기본값에 의존하지 말고 항상 명시할 것

## 사용 예

```bash
# 기본 실행 (수수료 5bps, 슬리피지 5bps, 초기자본 10000)
python -m backtest.engine.runner     --strategy sma_cross --symbol BTCUSDT --interval 1h     --start 2023-01-01 --params '{"fast":10,"slow":30}'

# 4H 봉, 명시적 수수료/슬리피지
python -m backtest.engine.runner     --strategy sma_cross --symbol ETHUSDT --interval 4h     --start 2022-01-01 --end 2024-12-31     --fee-bps 4 --slippage-bps 2 --init-capital 10000     --params '{"fast":20,"slow":60}'
```

## 옵션

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--strategy` | (필수) | `backtest/strategies/<name>.py` |
| `--symbol` | (필수) | 예: `BTCUSDT` |
| `--interval` | `1h` | `1h` / `4h` / `1d` / `1w` |
| `--start` | None | UTC 시작 (`YYYY-MM-DD` 또는 ISO) |
| `--end` | None | UTC 종료 |
| `--params` | `{}` | JSON dict. DEFAULT_PARAMS 위에 머지됨 |
| `--fee-bps` | 5.0 | bar별 `\|Δpos\| * (fee+slip)/10000` 차감 |
| `--slippage-bps` | 5.0 | 동일 |
| `--init-capital` | 10000.0 | equity 시작값 |
| `--out-root` | `backtest/runs` | 런 부모 디렉터리 (테스트용 override) |
| `--run-name` | 자동 | `{YYYYMMDD-HHMMSS}_{strategy}_{symbol}` 자동 생성 |

## 산출물 포맷

런 디렉터리: `backtest/runs/{YYYYMMDD-HHMMSS}_{strategy}_{symbol}/`

### `config.yaml`
```yaml
strategy: sma_cross
symbol: BTCUSDT
interval: 1h
start: 2023-01-01
end: null
params: {fast: 10, slow: 30}
fee_bps: 5.0
slippage_bps: 5.0
init_capital: 10000.0
```

### `equity.parquet`
| 컬럼 | dtype | 설명 |
|---|---|---|
| `timestamp` | int64 | UTC ms |
| `equity` | float64 | 누적 자본 (init_capital * cumprod(1+net_ret)) |
| `ret` | float64 | bar 순수익률 (수수료/슬리피지 차감 후) |
| `position` | int8 | ±1 / 0 (시그널 shift(1) 후) |

### `trades.parquet`
한 행 = 한 라운드트립. `side`(±1, int8), `entry_ts`, `exit_ts`(int64 UTC ms), `entry_price`, `exit_price`(float64), `bars`(int32, 보유 봉 수), `pnl_pct`(float64, **gross**, 수수료 제외).

### `metrics.json`
정확히 9개 키:
`total_return`, `cagr`, `sharpe`, `mdd`(음수), `n_bars`, `n_trades`, `win_rate`(0~1), `avg_pnl_pct`, `avg_holding_bars`.

샤프 연율화 봉 수: 1h=8760, 4h=2190, 1d=365, 1w=52.

## 자주 하는 실수

1. **전략에서 직접 shift 하기** — 엔진이 한 번 더 shift 하면 t+2가 됨. 전략은 t시점 close 기준으로 시그널만 반환.
2. **수수료를 빠뜨리기** — 첫 bar의 0→±1 진입에도 비용이 든다. 엔진은 첫 bar의 `|pos[0] - 0|`까지 합산해서 차감함.
3. **start/end를 ms epoch으로 넘기기** — CLI는 `YYYY-MM-DD` 문자열을 받는다.
4. **시그널에 NaN** — 모멘텀/볼린저 워밍업 구간은 0으로 채울 것 (`fillna(0)`).
5. **데이터 캐시 없음** — 먼저 `/fetch-history`로 다운로드.
6. **run dir 이름 충돌** — 자동 타임스탬프는 초 단위. 같은 초에 두 번 호출하면 충돌하므로 테스트는 `--run-name` 로 명시.

## 호출 절차

1. 데이터 캐시 존재 확인 (없으면 `/fetch-history` 안내)
2. 전략 파라미터 확정 (전략의 `DEFAULT_PARAMS`가 시작점)
3. 위 CLI 실행
4. 표준 출력에 찍힌 런 디렉터리 경로를 사용자에게 안내
5. 다음 단계로 `/launch-dashboard` 또는 `/compare-runs` 추천
