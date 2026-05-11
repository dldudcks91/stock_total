"""분류 결과(classification.parquet)에서 그룹별 심볼 집합을 뽑는 유틸.

사용:
    from data.universe import load_groups, sample_group
    groups = load_groups()                    # {tier: [symbols]}
    syms   = sample_group("trend", limit=30)  # 관측치 많은 순으로 30개
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

CLASSIFICATION_PATH = Path(__file__).parent / "cache" / "crypto" / "classification.parquet"

VALID_TIERS = ("trend", "follower", "whale", "junk")


def _load_df() -> pd.DataFrame:
    if not CLASSIFICATION_PATH.exists():
        raise FileNotFoundError(
            f"{CLASSIFICATION_PATH} not found. Run /classify-coins first."
        )
    return pd.read_parquet(CLASSIFICATION_PATH)


def load_groups(min_obs: int = 300) -> Dict[str, List[str]]:
    """Return {tier: [symbol, ...]} for the four target tiers, filtered by min_obs."""
    df = _load_df()
    df = df[df["n_obs"] >= min_obs]
    out: Dict[str, List[str]] = {}
    for tier in VALID_TIERS:
        sub = df[df["tier_final"] == tier].sort_values("n_obs", ascending=False)
        out[tier] = sub["symbol"].tolist()
    return out


def sample_group(
    tier: str,
    limit: Optional[int] = None,
    min_obs: int = 300,
) -> List[str]:
    """Return up to ``limit`` symbols from a tier, ordered by listing length desc."""
    if tier not in VALID_TIERS:
        raise ValueError(f"tier must be one of {VALID_TIERS}, got {tier}")
    syms = load_groups(min_obs=min_obs)[tier]
    if limit is not None:
        syms = syms[:limit]
    return syms


if __name__ == "__main__":
    groups = load_groups()
    for k, v in groups.items():
        print(f"{k}: {len(v)} symbols (top 5: {v[:5]})")
