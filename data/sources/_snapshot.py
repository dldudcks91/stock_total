"""Shared snapshot persistence helpers for live-ticker fetchers.

Pattern: each market (NASDAQ / KOSPI / Bitget) has a runnable fetcher module
under ``data/sources/`` that pulls live ticker data and writes a merged
parquet snapshot. Dashboards read the snapshot directly — they don't trigger
the fetch themselves. Refresh is opt-in via a sidebar button that spawns the
fetcher as a background subprocess.

Snapshot semantics:
- Each row gets a ``fetched_at`` timestamp (KST ISO).
- Tickers absent from a new fetch (response failure / network blip) retain
  their previous row + ``fetched_at`` — so a snapshot never *shrinks* due
  to a partial failure.
- Writes are atomic: write to ``{stem}.tmp{suffix}``, then ``os.replace``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pandas as pd


def load_snapshot(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def merge_snapshot(
    new_df: pd.DataFrame,
    path: Path,
    *,
    symbol_col: str,
) -> pd.DataFrame:
    """Merge ``new_df`` into the snapshot at ``path``.

    Tickers absent from ``new_df`` retain their existing values + previous
    ``fetched_at``. Tickers present overwrite, with ``fetched_at`` set to
    now (KST).
    """
    now_iso = pd.Timestamp.now(tz="Asia/Seoul").isoformat(timespec="seconds")
    new_df = new_df.copy()
    new_df["fetched_at"] = now_iso

    old = load_snapshot(path)
    if old is None or old.empty:
        return new_df.reset_index(drop=True)

    old_idx = old.set_index(symbol_col)
    new_idx = new_df.set_index(symbol_col)

    # Column union — accommodate schema drift between versions.
    for col in new_idx.columns:
        if col not in old_idx.columns:
            old_idx[col] = None
    for col in old_idx.columns:
        if col not in new_idx.columns:
            new_idx[col] = None
    new_idx = new_idx[old_idx.columns]

    merged = old_idx.copy()
    merged.update(new_idx)
    new_only = new_idx[~new_idx.index.isin(merged.index)]
    if not new_only.empty:
        merged = pd.concat([merged, new_only])

    return merged.reset_index()


def write_atomic(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f"{path.stem}.tmp{path.suffix}"
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
