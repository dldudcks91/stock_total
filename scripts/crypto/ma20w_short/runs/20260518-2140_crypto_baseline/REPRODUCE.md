# 재현 방법

## 1. 환경
- Python 3.9.13, `requirements.txt` 설치
- 필요 캐시: `data/cache/crypto/1d/*.parquet` (553 심볼, 2026-05-18 17:00 KST 기준)
- 분류 캐시: `data/cache/crypto/classification.parquet` (`tier_final` 컬럼)
- venv: `.venv/Scripts/python.exe` (Windows) / `.venv/bin/python` (POSIX)

## 2. 같은 결과 받기
```bash
cd <project_root>
.venv/Scripts/python.exe -m scripts.ma20w_short.baseline \
    --config scripts/ma20w_short/runs/20260518-2140_crypto_baseline/config.json
```

(스모크 5심볼만: 위 명령에 `--limit-symbols 5` 추가)

## 3. 검증
- `output/trades.parquet` row 수: **1,173**
- `output/summary.json` 의 `overall.mean ≈ -0.0049`, `var95 ≈ -0.929`
- 그룹 합계 (`output/summary_by_tier.csv`):
  - follower n=379, mean +0.0428
  - trend n=461, mean -0.0264
- 그룹 분류 파일이 동일 commit 이어야 함 (`data/cache/crypto/classification.parquet`)

## 4. 알려진 변동 원인
- crypto 캐시가 갱신되면 (1d parquet 의 새 row) trade 수가 늘어남.
- `classification.parquet` 의 `tier_final` 재분류 시 by-tier 결과가 바뀜.
- 두 파일의 `mtime` 을 README 핵심결과 옆에 적어두면 비교 시 명확.
