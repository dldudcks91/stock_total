# scripts/

분석·일회성 작업 모음. **`/study` 스킬** 기반의 run 폴더 표준을 따른다 (자세히: [CLAUDE.md](../CLAUDE.md) "분석 run 폴더 표준" 섹션).

## 디렉터리

```
scripts/
├── _common/                    # 공통 helper (run_helper.py)
├── trend_pullback/             # trend_pullback 전략 관련 분석
│   ├── *.py                    # 분석 모듈
│   └── runs/                   # 분석 run 결과 (각 run = 폴더 1개)
└── support_touch/              # 지지 테스트 (이평선 박치기 후 반등) 패턴 스캔
    ├── scan.py
    └── runs/                   # (마이그레이션 후 생성)
```

## 워크플로우

1. **`/study init <group> <name>`** — `scripts/<group>/runs/{ts}_{name}/` + 골격 파일들 (config.json, README.md, REPRODUCE.md, env.txt)
2. 분석 모듈 실행 (config 모드 권장):
   ```bash
   .venv/Scripts/python.exe -m scripts.<group>.<module> \
       --config scripts/<group>/runs/{ts}_{name}/config.json
   ```
   결과는 `<run_dir>/output/` 에 저장
3. **`/study finalize <run_dir>`** — output 스캔, README 산출물 섹션 + config.outputs 자동 채움

## 공통 helper (`_common/run_helper.py`)

```python
from scripts._common.run_helper import parse_args, update_config, resolve_config_path

def main():
    def add_args(ap):
        ap.add_argument("--my-param", type=float, default=None)
    out_dir, params, args = parse_args(add_args, {"my_param": 0.5}, "module_name")
    # ... 분석, out_dir 에 결과 저장
    cfg_path = resolve_config_path(args)
    if cfg_path:
        update_config(cfg_path, params=params, data={...}, results_summary={...})
```

## 그룹

### `trend_pullback/`
1H 임펄스 후 MA10/MA20 터치 / 미터치 패턴의 forward returns 분석.

| 모듈 | 역할 |
|---|---|
| `angle_study.py` | 이벤트 수집 — 임펄스 + 게이트 + MA 터치 추적 → `events.parquet` |
| `full_grid.py` | wick × bars × angle 3축 cross-tab (MA10 기준) → `full_grid_summary.csv` |
| `full_grid_ma20.py` | 동일 cross-tab (MA20 기준) |
| `upper_wick_study.py` | 윗꼬리 bin 별 forward returns |
| `btc_regime.py` | BTC 1D 강세/약세 × 임펄스 사이즈 분석 |
| `size_table.py` | 임펄스 사이즈 (1% bins) × horizon forward returns |
| `monthly_dist.py` | 임펄스 월별 분포 |
| `visualize.py` | wick × bars × angle 단일 cell 의 케이스들을 candle 차트로 |

모두 `--config <run_dir>/config.json` 으로 실행.

### `support_touch/`
이평선에 위에서 닿고 다시 반등하는 (지지 테스트 성공) 패턴 스캐너. 아직 새 패턴 마이그레이션 안 됨.

## 원칙

- **`scripts/out/` 단일 폴더 사용 금지** — 항상 `runs/{ts}_{name}/output/` 로 격리
- 분석 history 자동 보존 (옛 run 폴더 삭제 X)
- 다른 컴퓨터에서 `--config` 만으로 동일 결과 재현 가능
- `git_dirty=true` 면 finalize 시 경고 — 정확한 재현 보장 X
