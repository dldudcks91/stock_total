"""TF별 평가 종류 분기 (full / partial / skip).

각 TF 의 봉 수에 따라:
  - 봉 ≥ 20 → 'full'     (MA20 계산 가능 → 정배열 룰 적용)
  - 봉 ≥ 10 → 'partial'  (MA10 만 가능 → 신생주 강한 시작 룰)
  - 봉 <  10 → 'skip'    (그 TF 자체 평가 불가)

사용처: signals.signal_ma_touch 직전 단계.
"""
from __future__ import annotations

from typing import Dict, Literal

import pandas as pd

EvalKind = Literal["full", "partial", "skip"]

MIN_BARS_FULL = 20
MIN_BARS_PARTIAL = 10


def determine_eval_kind(df_tf: pd.DataFrame) -> EvalKind:
    """단일 TF df 에 대한 평가 종류 결정."""
    n = len(df_tf)
    if n >= MIN_BARS_FULL:
        return "full"
    if n >= MIN_BARS_PARTIAL:
        return "partial"
    return "skip"


def determine_all(df_by_tf: Dict[str, pd.DataFrame]) -> Dict[str, EvalKind]:
    """다중 TF dict 의 각 TF 에 대한 평가 종류 결정."""
    return {tf: determine_eval_kind(df) for tf, df in df_by_tf.items()}


def select_eval_tfs(df_by_tf: Dict[str, pd.DataFrame]) -> list:
    """평가할 TF 리스트 결정 (사용자 룰).

    - 월봉 데이터 ≥ 10봉 (= MA10 가능, 약 10개월+ 상장) → 1D 제외
      (큰 흐름 자리만 보고 단기 노이즈 차단)
    - 월봉 < 10 봉 → 1D 포함 (신생주의 단기 자리 catch)

    반환 TF 순서: 작은 TF → 큰 TF.
    """
    m_bars = len(df_by_tf.get("1M", []))
    has_monthly_ma10 = m_bars >= MIN_BARS_PARTIAL
    if has_monthly_ma10:
        return ["1W", "1M", "1Q", "1Y"]
    return ["1D", "1W", "1M", "1Q", "1Y"]
