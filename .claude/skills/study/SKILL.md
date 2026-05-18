---
name: study
description: 분석 run 폴더를 생성·마감하는 단일 스킬. `init` 으로 표준 폴더(scripts/<group>/runs/{ts}_{name}/) + config.json + README.md + REPRODUCE.md + env.txt 골격을 만들고, `finalize` 로 output 디렉터리 스캔 후 README 산출물 섹션과 config.outputs 자동 채움. **모든 전략(group)은 사용자와 논의 후 `scripts/<group>/PLAN.md` 가 먼저 존재해야 init 가능** — 계획 없이 run 만 찍는 것 금지. 어디서든 동일 결과 재현 가능하도록 모든 메타(git commit, python/pandas 버전, params, data range)를 기록. 사용자가 "/study init", "/study finalize", "분석 폴더 만들기", "run 폴더" 라고 할 때 발동.
---

# /study — 분석 run 폴더 표준화

분석 결과를 표준 폴더 (`scripts/<group>/runs/{YYYYMMDD-HHMM}_{name}/`) 에 저장하고, 다른 컴퓨터에서도 그대로 재현 가능하도록 메타 데이터·재현 명령을 함께 기록한다.

## 트리거 예시

- `/study init trend_pullback 1W_slope_imp10`
- `/study init trend_pullback W_mid_1to3_Q4 --module scripts.trend_pullback.full_grid`
- `/study finalize scripts/trend_pullback/runs/20260518-1925_1W_slope_imp10/`

## 사전 단계 — PLAN.md (모든 전략 / 그룹 필수)

**규칙**: 어떤 group 이든 첫 `/study init` 전에 사용자와 논의해 `scripts/<group>/PLAN.md` 를 먼저 작성한다. PLAN.md 없이 run 폴더만 만드는 것은 금지 — 계획 없는 run 은 재현 가치도, 비교 가치도 없음.

**PLAN.md 위치**: `scripts/<group>/PLAN.md` (group 루트). 개별 run 폴더 안 X — 여러 run 에 걸친 마스터 플랜이므로.

**작성 절차**:

1. 사용자가 새 전략/연구 주제를 꺼내면, **Claude 는 곧바로 init 하지 말고** 먼저 다음을 사용자와 합의:
   - 큰 질문 (가설 한 줄)
   - "성공/실패 판정" 의 조작적 정의 (어떤 메트릭이 어떻게 나오면 통과·폐기인가)
   - Layer 분해 (baseline → entry → exit → OOS → stability 류로 여러 run 이 묶이면 명시)
   - 데이터 범위·자산·표본 가드
   - 폐기 조건 (어떤 결과가 나오면 그만두는가)
2. 합의된 내용을 `scripts/<group>/PLAN.md` 에 Write. 템플릿:

   ```markdown
   # {group} 연구 계획

   > 작성: {KST 일시} · 마스터 플랜 (모든 후속 run 의 상위 계약)

   ## 0. 큰 질문
   (한 줄 가설 + "안전/성공" 의 조작적 정의)

   ## 1. Run 구조 (Layer)
   - Layer 0 — {run 이름}: 목적
   - Layer 1 — {run 이름}: 목적
   - ...

   ## 2. 데이터 / 표본 가드
   | 항목 | 값 |

   ## 3. 폐기 조건
   (어떤 결과가 나오면 가설을 버리는가)

   ## 4. 다음 즉시 액션
   ```
3. `init` 진입 시 Claude 는 `scripts/<group>/PLAN.md` 존재 여부를 확인 (검증 단계). 없으면 **init 거부** 후 사용자에게 "먼저 PLAN.md 를 함께 작성하자" 고 요청.

**예외 없음**: 단발 탐색이라도 PLAN.md 한 줄(목적·판정·폐기) 은 반드시 둔다. PLAN.md 작성 자체는 1~3분 안에 끝낼 수 있는 분량이어도 됨 — 핵심은 "사용자 합의를 거쳤다" 는 사실.

## 서브커맨드 두 개

### `init` — 새 run 폴더 생성

**입력**:
- `group` (필수): 큰 틀 폴더 이름 (예: `trend_pullback`). `scripts/<group>/` 가 없으면 생성한다.
- `name` (필수): run 식별자. `^[a-z0-9_]+$`, 길이 ≤ 50. 예: `1W_slope_imp10_volX`.
- `module` (선택): 메인 분석 모듈 경로 (예: `scripts.trend_pullback.angle_study`). 생략하면 빈 문자열.
- `description` (선택): 한 줄 설명. 생략하면 README "목적" 섹션의 자리 표시자를 그대로 두고, finalize 전에 직접 채우게 한다 (스킬 도중 별도 prompt 없음).

**Claude 단계**:

1. **검증**:
   - `name` 정규식 + 길이 확인
   - `scripts/<group>/runs/` 디렉터리 보장
   - **`scripts/<group>/PLAN.md` 존재 여부 확인 — 없으면 init 거부**. 사용자에게 "이 그룹의 PLAN.md 가 아직 없습니다. 먼저 함께 작성하시죠" 하고 위의 "사전 단계 — PLAN.md" 섹션 절차를 따르도록 안내. 절대 PLAN.md 를 임의로 작성한 뒤 init 하지 말 것 — 반드시 사용자와 합의 후 작성.
2. **타임스탬프**: `datetime.now(timezone(timedelta(hours=9)))` (KST) → `YYYYMMDD-HHMM` 형식. 같은 분 안에 충돌하면 `_2` 같이 suffix.
3. **폴더 생성**:
   ```
   scripts/<group>/runs/{ts}_{name}/
   ├── output/          # 빈 폴더
   ├── README.md
   ├── config.json
   ├── REPRODUCE.md
   └── env.txt
   ```
4. **`config.json` 골격** (Claude 가 직접 Write):
   ```json
   {
     "group": "<group>",
     "name": "<name>",
     "created_at": "<KST ISO 8601>",
     "module": "<module or empty>",
     "git_commit": "<git rev-parse --short HEAD>",
     "git_dirty": <true if uncommitted changes>,
     "git_branch": "<git rev-parse --abbrev-ref HEAD>",
     "params": {},
     "data": {
       "asset": "",
       "interval": "",
       "cache_dir": "",
       "symbol_count": null,
       "data_until": null
     },
     "results_summary": {},
     "outputs": []
   }
   ```
   - `git_commit` / `git_branch`: `git rev-parse --short HEAD`, `git rev-parse --abbrev-ref HEAD`.
   - `git_dirty`: `git status --porcelain` 의 출력이 비어있지 않으면 `true`. (`wc -l > 0` 같은 비교 X — Bash 면 `[ -n "$(git status --porcelain)" ]`, PowerShell 이면 `(git status --porcelain) -ne $null` 식.)
   - `params` / `data` / `results_summary` 는 빈 칸으로 두고 분석 모듈이 `update_config` 로 채운다.

5. **`README.md` 템플릿**:
   ```markdown
   # {name}

   - 생성: {ts_kst}
   - Group: {group}
   - Module: {module or "—"}
   - Git: {commit} ({branch}, {clean or dirty})

   ## 목적
   {description or "(이 분석의 의도를 적으세요)"}

   ## 방법
   (어떤 게이트·필터를 적용했는지, params 핵심 한 줄 요약)

   ## 핵심 결과
   (분석 완료 후 채움 — `/study finalize` 이후 직접 손으로)

   ## 산출물
   (`/study finalize` 가 자동 채움)

   ## 재현
   `REPRODUCE.md` 참조.
   ```

6. **`REPRODUCE.md` 템플릿** (`module` 있을 때):
   ```markdown
   # 재현 방법

   ## 1. 환경
   - Python ≥ 3.9, `requirements.txt` 설치
   - 필요 캐시: (config.data.cache_dir 참조)
   - venv: `.venv/Scripts/python.exe` (Windows) / `.venv/bin/python` (POSIX)

   ## 2. 같은 결과 받기
   ```bash
   cd <project_root>
   .venv/Scripts/python.exe -m {module} --config <THIS_DIR>/config.json
   ```

   ## 3. 검증
   - `output/` 의 parquet/csv row 수와 hash 비교
   - 핵심 메트릭 (e.g. baseline mean / median / win) 일치 여부 확인
   ```

7. **`env.txt` 자동 작성**: Bash 로 다음 수집:
   ```
   python: <python --version 출력>
   pandas: <pip show pandas | grep Version>
   numpy: <pip show numpy | grep Version>
   git_commit: <short hash>
   git_branch: <branch>
   git_dirty: <true/false>
   created_at_kst: <KST ISO>
   data_last_fetch: <data/last_fetch.json 의 해당 자산 timestamp, 있으면>
   ```

8. **출력**: 만들어진 폴더의 절대경로 + 다음 액션 안내:
   ```
   scripts/trend_pullback/runs/20260518-1925_1W_slope_imp10/

   다음 단계:
   1) config.json 의 params / data 채우기
   2) 분석 모듈을 --out-dir 또는 --config 로 실행해 output/ 에 결과 쓰기
   3) /study finalize <폴더경로> 로 마감
   ```

### `finalize` — run 폴더 마감

**입력**:
- `run_dir` (필수): `init` 으로 만든 run 폴더 경로.

**Claude 단계**:

1. **검증**: `run_dir` 존재 + `config.json` 존재 확인.
2. **`output/` 스캔**:
   - 모든 파일 (recursive) 나열
   - 각 파일에 대해: 상대경로, 크기 (KB/MB), mtime 기록
3. **`config.json` 업데이트**:
   - `outputs` 배열에 `output/` 상대경로 채우기
   - 새 키 `finalized_at` 에 KST ISO 시각 기록
4. **`README.md` 의 "산출물" 섹션 자동 채움**:
   ```markdown
   ## 산출물

   | 파일 | 크기 | 설명 |
   |---|---|---|
   | `output/events.parquet` | 3.2 MB | (분석 모듈에서 정한 의미 — 비어 있으면 사용자 보강 권장) |
   | `output/full_grid.csv` | 12 KB | ... |
   ```
   - 설명은 비어 있어도 OK — finalize 후 사용자가 손으로 채울 수 있게 빈 칸 둠.

5. **`env.txt` 마감 시 추가**: `finalized_at_kst` 한 줄 더.

6. **사용자에게 알림**:
   - finalize 완료 + README 의 **"핵심 결과"** 섹션은 자동 채우지 않으므로 직접 손으로 채워달라고 안내.
   - git status 가 dirty 였으면 경고: "git_dirty=true 이므로 정확한 재현 보장 X. 커밋 후 init 권장".

## 동작 원칙

- **단순 Claude 동작 (외부 스크립트 호출 X)**: Bash 로 git/pip/python 정보 수집 + Read/Write/Edit 로 파일 조작.
- **idempotent finalize**: 같은 폴더에 다시 호출하면 outputs 만 다시 스캔하고 README 산출물 표 재생성 (덮어쓰기). 핵심 결과 섹션은 보존.
- **재현성 우선**: `git_dirty=true` 이면 finalize 시 경고. `git_commit` 은 항상 기록.

## 자주 하는 실수

- **PLAN.md 없이 init 진행 → 금지**. 첫 run 전에 반드시 사용자와 논의해 `scripts/<group>/PLAN.md` 를 먼저 작성.
- **PLAN.md 를 run 폴더 안에 박는 실수**. PLAN 은 group 마스터 플랜이므로 `scripts/<group>/PLAN.md` (group 루트) 위치. 개별 run 폴더 안 X.
- `ts` 를 UTC 로 찍으면 한국 시간대 사용자가 헷갈림 → 항상 KST 로.
- `params` 를 자동 추론하지 말 것 — 분석 모듈마다 의미 다름. 사용자/모듈이 채우게.
- `outputs` 에 `output/` 외 파일 (README, config 등) 포함 X. 데이터 산출물만.
- `name` 에 공백 또는 한글 포함 시 파일 경로 깨질 수 있음 — 영소문자/숫자/언더스코어만.
- 기존 분석 모듈이 단일 `scripts/out/` 에 덮어쓰는 경우, `--out-dir` 인자 지원이 필요 (마이그레이션 별도).

## 분석 모듈 인터페이스 (권장)

```python
# scripts/<group>/<name>.py
import argparse, json
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="config.json from /study init")
    ap.add_argument("--out-dir", help="run 폴더 (config 없을 때)")
    # ... 개별 인자
    args = ap.parse_args()

    if args.config:
        cfg = json.loads(Path(args.config).read_text())
        out_dir = Path(args.config).parent / "output"
        params = cfg["params"]
    else:
        out_dir = Path(args.out_dir) / "output"
        params = {k: v for k, v in vars(args).items() if k not in ("config", "out_dir")}

    out_dir.mkdir(parents=True, exist_ok=True)
    # ... 분석 + 결과를 out_dir 에 저장
```

→ `--config` 만 받으면 모든 파라미터 자동 로드, `--out-dir` + 개별 인자 조합도 지원.
