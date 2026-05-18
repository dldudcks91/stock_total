# support_touch

특정 이평선에 2~3번 닿고 튀어오르는 (= 지지 테스트 성공) 패턴 스캐너.

`QUIET_BOTTOM` 의 "박치기 거름" 과 반대 — 여기서는 **지지 테스트 성공** 케이스를 찾는다.

## 분석 모듈

- `scan.py` — 3개 설정 (1d×MA20 / 4h×MA20 / 1h×MA10) 으로 전 종목 스캔

## 실행

```bash
# 1) 새 run 폴더 생성
/study init support_touch <name>

# 2) 스캔 (config 모드)
.venv/Scripts/python.exe -m scripts.support_touch.scan \
    --config scripts/support_touch/runs/{ts}_{name}/config.json

# 또는 ad-hoc (config 없이)
.venv/Scripts/python.exe -m scripts.support_touch.scan \
    --out-dir scripts/support_touch/runs/{ts}_{name}/ \
    --min-amount-usdt 1e6 --top 30

# 3) 마감
/study finalize scripts/support_touch/runs/{ts}_{name}/
```

## 결과 보관

`scripts/support_touch/runs/{ts}_{name}/output/` 에 config 별 CSV (`support_touch_<label>.csv`) + `support_touch_consensus.csv`.
