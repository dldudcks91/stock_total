"""프로젝트 .venv 강제 가드 — 데이터 fetcher 모듈 진입점에서 호출.

CLAUDE.md 의 venv 규칙: "이 프로젝트의 모든 파이썬 실행은 프로젝트 루트의
``.venv`` 를 경유한다". 시스템(anaconda) 파이썬으로 ``data.sources.bitget`` 같은
모듈을 직접 호출하면, aiohttp 동작 차이로 ``Event loop is closed`` 같은 잡음
예외가 발생하고 의존성 버전이 어긋날 수 있다.

이 가드는 ``sys.executable`` 이 프로젝트 ``.venv`` 안인지 확인하고, 아니면
즉시 종료해 사용자에게 정확한 명령을 안내한다.

환경변수 ``STOCK_TOTAL_SKIP_VENV_GUARD=1`` 로 우회 가능 (CI / 디버깅용).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _venv_dir() -> Path:
    """프로젝트 루트의 ``.venv`` 디렉터리 경로."""
    # data/_venv_guard.py → parents[1] = 프로젝트 루트.
    return Path(__file__).resolve().parents[1] / ".venv"


def require_project_venv() -> None:
    """현재 실행이 프로젝트 ``.venv`` 안이 아니면 명확한 메시지로 종료.

    pip-install 시점 등 모듈 import 만 일어나는 환경도 안전하게 통과시키기 위해
    ``__main__`` 컨텍스트 (CLI 실행) 일 때만 검증한다.
    """
    if os.environ.get("STOCK_TOTAL_SKIP_VENV_GUARD") == "1":
        return

    exe = Path(sys.executable).resolve()
    venv = _venv_dir().resolve()
    try:
        exe.relative_to(venv)
        return  # exe 가 .venv 안 → OK
    except ValueError:
        pass

    # cp949 PowerShell 에서 한글 깨짐 방지 — stderr 도 utf-8 로 reconfigure.
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # 권장 명령: `python -m pkg.mod arg1 arg2` 형태로 재구성.
    # ``__main__`` 으로 호출된 모듈 이름은 ``sys.argv[0]`` 가 아니라
    # 프로세스의 ``__main__.__spec__.name`` 에 있음. 없으면 path 로 fallback.
    main_spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    mod_name = main_spec.name if main_spec is not None else Path(sys.argv[0]).stem
    rest_args = " ".join(sys.argv[1:])
    cmd_suggest = f"{venv / 'Scripts' / 'python.exe'} -m {mod_name}"
    if rest_args:
        cmd_suggest += f" {rest_args}"

    msg = (
        "[venv-guard] 이 모듈은 프로젝트 .venv 의 파이썬으로만 실행해야 합니다.\n"
        f"  현재 사용 중: {exe}\n"
        f"  프로젝트 venv: {venv}\n"
        "\n"
        "권장 실행 예 (Windows):\n"
        f"  {cmd_suggest}\n"
        "\n"
        "우회가 필요하면: $env:STOCK_TOTAL_SKIP_VENV_GUARD = '1'"
    )
    print(msg, file=sys.stderr)
    sys.exit(2)
