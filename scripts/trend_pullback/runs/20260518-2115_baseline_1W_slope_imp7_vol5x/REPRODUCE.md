# 재현 방법

## 1. 환경

- Python ≥ 3.9, `requirements.txt` 설치
- 필요 캐시: `data/cache/crypto/1h/*.parquet` (Bitget USDT-M 1H)
- venv: `.venv/Scripts/python.exe` (Windows) / `.venv/bin/python` (POSIX)

## 2. 같은 결과 받기

프로젝트 루트에서:

```bash
.venv/Scripts/python.exe -m scripts.trend_pullback.angle_study \
    --config scripts/trend_pullback/runs/20260518-2115_baseline_1W_slope_imp7_vol5x/config.json
```

`--config` 만 넘기면 모든 params 와 출력 위치 (`<RUN_DIR>/output/`) 가 자동 결정.

## 3. 검증

- `output/events.parquet` 의 row 수가 같은지 확인 (코드/데이터 동일 시점이면 정확히 같아야 함)
- `output/angle_study_summary.csv` 의 baseline `MA10 touched within 10 (fr touch close)` row 의 168h_mean / 168h_win 비교
- git commit 다르면 코드 변경에 의한 차이 가능 — `git_commit` 필드 확인
- `git_dirty=true` 였으면 정확한 재현 보장 X (커밋 후 init 권장)
