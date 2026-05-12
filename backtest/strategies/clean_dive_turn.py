"""Deprecated alias — use ``quiet_bottom`` 대신.

이전 이름. 동일 시그널 함수를 그대로 노출하므로 기존 스크립트는 동작하지만,
신규 코드는 ``backtest.strategies.quiet_bottom`` 을 사용할 것.
"""
from backtest.strategies.quiet_bottom import (  # noqa: F401
    NAME as _NAME, LABEL_KR, DEFAULT_PARAMS, signal,
)

# 구 이름 보존
NAME = "clean_dive_turn"
