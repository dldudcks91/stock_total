# 재현 방법

## 1. 환경

- Python 3.12.10
- pandas 2.2.3, numpy 1.26.4
- venv: `.venv/Scripts/python.exe` (Windows) / `.venv/bin/python` (POSIX)
- 필요 캐시:
  - `data/cache/crypto/1d/*.parquet` (Bitget USDT-M 일봉)
  - `data/cache/crypto/classification.parquet` (4그룹 분류)

## 2. 같은 결과 받기

```powershell
cd c:\Users\82109\Desktop\LYC\git\stock_total
.venv\Scripts\python.exe -m scripts.crypto.ma20w_short.baseline --config scripts/crypto/ma20w_short/runs/20260528-2236_baseline/config.json
```

## 3. 검증

- `output/trades.parquet` row 수와 hash 비교
- `output/summary.json` 의 그룹별 `mean_ret`, `var_adj_ex` 일치 여부
- `output/summary_by_group.csv` 4 행 (trend/follower/whale/junk) 모두 존재
