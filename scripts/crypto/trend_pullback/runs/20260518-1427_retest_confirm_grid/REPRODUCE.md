# 재현 방법

## 1. 환경
- Python ≥ 3.9 (실제 3.12), `requirements.txt` 설치
- venv: `.venv/Scripts/python.exe` (Windows) / `.venv/bin/python` (POSIX)
- 필요 캐시: `data/cache/crypto/1h/*.parquet` (Bitget USDT-M 1H, ~553 심볼)

## 2. 같은 결과 받기

```bash
cd <project_root>
.venv/Scripts/python.exe -m scripts.trend_pullback.retest_confirm_grid \
    --config scripts/trend_pullback/runs/20260518-1427_retest_confirm_grid/config.json
```

## 3. 검증
- `output/events_confirm.parquet` row 수 = `n_events`
- `output/grid_1d.csv` 의 (`feature` × `quantile` × `horizon_h`) row 수
- baseline (`20260518-2147_1H_touch_1W_ma20_slope_up`) 의 4w win 32.5% 와 일치하는지 — 확인봉 필터 없는 전체 평균 비교
