# 재현 방법

## 1. 환경
- Python ≥ 3.9 (실제 3.12), `requirements.txt` 설치
- venv: `.venv/Scripts/python.exe`
- 필요 캐시: `data/cache/crypto/1d/*.parquet` (또는 1H 캐시에서 자동 리샘플)

## 2. 같은 결과 받기

```bash
.venv/Scripts/python.exe -m scripts.trend_pullback.slope_cross_event \
    --config scripts/trend_pullback/runs/20260519-0007_slope_cross_event/config.json
```

## 3. 검증
- `output/events.parquet` row 수 = `n_events`
- `output/horizon_curve.csv` 의 horizon × {n, mean, median, win, std}
