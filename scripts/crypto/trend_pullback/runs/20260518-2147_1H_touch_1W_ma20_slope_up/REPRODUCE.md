# 재현 방법

## 1. 환경
- Python ≥ 3.9, `.venv/Scripts/python.exe`
- 필요 캐시: `data/cache/crypto/1h/{SYMBOL}.parquet` (553 종목)
- 캐시 갱신: 2026-05-18T17:01:18+09:00

## 2. 같은 결과 받기
```bash
cd <project_root>
.venv/Scripts/python.exe -m scripts.trend_pullback.ma20_touch_1h_entry \
    --config scripts/trend_pullback/runs/20260518-2147_1H_touch_1W_ma20_slope_up/config.json
```

## 3. 검증
- `output/events.parquet` row 수 == config.results_summary.n_events
- 1H 단위 진입가는 그 봉의 다음봉 open
- weekly MA20 는 `shift(1)` (no lookahead) 적용 여부 확인
