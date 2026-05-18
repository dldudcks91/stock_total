# 재현 방법

## 1. 환경

- Python ≥ 3.9, `requirements.txt` 설치
- venv: `.venv/Scripts/python.exe` (Windows) / `.venv/bin/python` (POSIX)
- 필요 캐시: `data/cache/crypto/1h/{SYMBOL}.parquet` (553 종목)
- 캐시 갱신 시점: 2026-05-18T17:01:18+09:00 (`data/last_fetch.json` 의 `crypto_1h`)

## 2. 같은 결과 받기

```bash
cd <project_root>
.venv/Scripts/python.exe -m scripts.trend_pullback.ma20_touch_entry \
    --config scripts/trend_pullback/runs/20260518-2140_1W_ma20_touch_slope_up/config.json
```

## 3. 검증

- `output/events.parquet` row 수와 다음 메트릭 일치 확인:
  - `n_touches` (config.results_summary)
  - `n_unique_symbols`
  - forward return baseline mean/median/win @ 4w, 8w
- BTC regime 슬라이스 (있을 경우) 합산 = 전체 표본 수
