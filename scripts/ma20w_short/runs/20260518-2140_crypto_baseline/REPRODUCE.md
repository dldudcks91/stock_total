# 재현 방법

## 1. 환경
- Python 3.9.13, `requirements.txt` 설치
- 필요 캐시: `data/cache/crypto/1d/*.parquet` (553 심볼, 2026-05-18 17:00 KST 기준)
- venv: `.venv/Scripts/python.exe` (Windows) / `.venv/bin/python` (POSIX)

## 2. 같은 결과 받기
분석 모듈이 아직 미정 (탐색 단계). 결정되면 아래 형식으로 갱신:

```bash
cd <project_root>
.venv/Scripts/python.exe -m scripts.ma20w_short.<module> --config <THIS_DIR>/config.json
```

## 3. 검증
- `output/` 의 parquet/csv row 수와 hash 비교
- 핵심 메트릭 (그룹별 mean/median short return, 승률, Sharpe) 일치 여부 확인
- 그룹 분류 파일이 동일 commit 이어야 함 (`data/cache/crypto/classification.parquet`)
