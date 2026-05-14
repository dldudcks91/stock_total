---
name: new-strategy
description: 새 백테스트 전략 파일을 backtest/strategies/_template.py.txt 템플릿에서 생성한다. 이름/설명을 입력받아 자리표시자를 치환하고 backtest/strategies/<name>.py로 저장. Claude가 직접 수행 (외부 스크립트 X).
---

# /new-strategy

새 전략 모듈을 템플릿에서 스캐폴드한다. Claude가 직접 파일을 생성하는 스킬 — 외부 명령은 호출하지 않는다.

## 트리거 예시

- `/new-strategy rsi_revert`
- `/new-strategy momentum_breakout`
- `/new-strategy vwap_pullback`

## Claude가 따를 단계 (체크리스트)

### 1. 이름 검증
사용자가 준 이름이 다음 조건을 모두 만족하는지 확인:
- 정규식 `^[a-z][a-z0-9_]*$` — snake_case, 영소문자/숫자/언더스코어, 첫 글자는 영문자
- 길이 ≤ 30
- 예약어 회피: `_template`, `__init__`, `base`

어긋나면 사용자에게 다시 받는다. 예:
> "이름은 snake_case로 부탁합니다. 예: `rsi_revert`. 다시 알려주세요."

### 2. 중복 확인
`backtest/strategies/<name>.py` 가 이미 존재하는지 확인:
- 존재하면 사용자에게 **덮어쓸지** 물어본다 (기본: 거부). 덮어쓰면 직전 버전 손실.
- 없으면 다음 단계로.

### 3. 한 줄 설명 받기
사용자에게 전략의 한 줄 설명을 묻는다 (모듈 docstring `{{DESCRIPTION}}` 치환용). 예:
> "한 줄로 어떤 전략인지 알려주세요. 예: `RSI 14 < 30 매수, > 70 매도 (평균회귀)`"

설명이 비어 있으면 `<name> strategy.` 같은 기본값.

### 4. 템플릿 치환 + 파일 생성
- `backtest/strategies/_template.py.txt` 를 Read
- 정확히 다음 두 자리표시자만 치환:
  - `{{NAME}}` → 사용자 입력 이름
  - `{{DESCRIPTION}}` → 사용자 입력 설명 (따옴표로 감싸지 말 것 — 이미 docstring 안에 들어감)
- `backtest/strategies/<name>.py` 로 Write
- 치환 후 자리표시자 `{{` 가 남아 있지 않은지 한 번 더 확인

### 5. 보고
사용자에게 다음을 알린다:
- 생성된 절대경로
- 권장 다음 액션:
  ```
  .venv/Scripts/python.exe -m backtest.engine.runner --strategy <name> --symbol BTCUSDT --interval 1h --start 2024-01-01
  ```
- 전략 작성 시 주의사항 (간단히):
  - 룩어헤드 금지 — `shift`/`ffill` 직접 호출 X (엔진이 t→t+1 처리)
  - `DEFAULT_PARAMS` 에 모든 튜닝 인자 노출
  - 반환은 `int8 ∈ {-1, 0, 1}`, df.index와 동일 길이

## 템플릿 인터페이스 (참고용)

`backtest/strategies/_template.py.txt` 는 다음 모듈 계약을 따른다:
```python
NAME = "{{NAME}}"
DEFAULT_PARAMS = { ... }   # dict[str, Any]
def signal(df: pd.DataFrame, params: dict) -> pd.Series:
    """반환: pd.Series of int8 ∈ {-1, 0, 1}, df.index와 동일 길이."""
```

`df` 컬럼: `timestamp`(UTC ms), `open`, `high`, `low`, `close`, `volume`, `amount`. 오름차순 보장.

## 자주 하는 실수

- 템플릿을 `.py` 로 저장하면 파이썬이 import 시도할 수 있음 → 반드시 `.txt` 유지
- `signal()` 안에서 `shift(-N)` 같은 미래 인덱싱 → 룩어헤드 바이어스
- `params` 인자 사용 안 하고 모듈 상수만 쓰면 파라미터 스윕 불가
- `signal` 결과의 dtype이 float이면 엔진이 비용 계산 시 부정확 — 반드시 int 계열
