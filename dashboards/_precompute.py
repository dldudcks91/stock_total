"""Precompute & persist dashboard views (refs + recs) to disk.

The KOSPI / NASDAQ / Bitget live tabs recompute reference levels
(``compute_reference_levels``) and ma_touch recommendations on every cold
load — each cycle iterates 600~4000 symbols × full parquet reads × per-TF
resamples, which Streamlit's ``@st.cache_data`` only papered over while the
process was alive.

This module replaces the in-memory cache with a **disk cache** per asset:

  data/cache/{asset}/_refs.parquet   ← compute_reference_levels output
  data/cache/{asset}/_recs.parquet   ← ma_touch evaluator output

Each file carries two staleness markers:

  - ``data_mtime``  (per row) — the underlying ``{symbol}.parquet`` mtime when
    this row was computed. Per-symbol incremental: only rows whose source
    parquet has changed get recomputed.
  - ``anchor_ms``   (uniform per file) — the wall-clock anchor the file was
    computed for (stock: today midnight KST in ms; crypto: hour bucket UTC).
    When this changes (next day for stock, next hour for crypto) **all** rows
    are recomputed since prev_Nd / MA / HL are anchored to wall-clock now.

Both triggers feed into ``_stale_symbols`` — a row is stale if either
``data_mtime`` advanced for that symbol or ``anchor_ms`` changed file-wide.

CLI::

    .venv/Scripts/python.exe -m dashboards._precompute --asset kr [--force]
    .venv/Scripts/python.exe -m dashboards._precompute --asset us [--force]
    .venv/Scripts/python.exe -m dashboards._precompute --asset crypto [--force]
    .venv/Scripts/python.exe -m dashboards._precompute --asset all

Dashboard usage::

    refs = load_refs("kr")          # parquet read, <500ms
    recs = load_recs("kr")          # parquet read, <500ms (None if file missing)
    # ... apply_current_prices(refs, current_prices) for live overlay
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboards._stock_grid import (
    CACHE_TAIL_N,
    compute_reference_levels,
    load_cache_tails,
)

SUPPORTED_ASSETS: tuple[str, ...] = ("kr", "us", "crypto")


def _cache_dir(asset: str) -> Path:
    """Asset cache root (where ``_refs.parquet`` / ``_recs.parquet`` live)."""
    return _ROOT / "data" / "cache" / asset


def _symbol_cache_dir(asset: str) -> Path:
    """Directory holding per-symbol parquets.

    For crypto this is ``cache/crypto/1d/`` — the 1d cache is the canonical
    source for ma_touch and resampled higher TFs.
    """
    if asset == "crypto":
        return _cache_dir(asset) / "1d"
    return _cache_dir(asset)


def refs_path(asset: str) -> Path:
    return _cache_dir(asset) / "_refs.parquet"


def recs_path(asset: str) -> Path:
    return _cache_dir(asset) / "_recs.parquet"


# ---------------------------------------------------------------------------
# Symbol discovery
# ---------------------------------------------------------------------------

def list_symbols(asset: str) -> list[str]:
    """All cached symbols for ``asset`` (``_``-prefixed files excluded)."""
    cache = _symbol_cache_dir(asset)
    if not cache.exists():
        return []
    return sorted(
        p.stem for p in cache.glob("*.parquet")
        if not p.stem.startswith("_")
    )


def _symbol_mtimes(asset: str, symbols: list[str]) -> dict[str, float]:
    """Filesystem mtime for each symbol's parquet (missing → 0.0)."""
    cache = _symbol_cache_dir(asset)
    out: dict[str, float] = {}
    for sym in symbols:
        p = cache / f"{sym}.parquet"
        try:
            out[sym] = p.stat().st_mtime
        except FileNotFoundError:
            out[sym] = 0.0
    return out


# ---------------------------------------------------------------------------
# Wall-clock anchor
# ---------------------------------------------------------------------------

def _stock_anchor_ms(now_ts: Optional[pd.Timestamp] = None) -> int:
    """Today midnight KST (naive) in ms since epoch.

    KOSPI / NASDAQ refs are day-bucketed: valid until the date rolls over.
    KST is used as the dashboard wall clock (matches user-facing labels).
    """
    if now_ts is None:
        now_ts = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None).normalize()
    return int(pd.Timestamp(now_ts).value // 1_000_000)


def _crypto_anchor_ms(now_ms: Optional[int] = None) -> int:
    """Current hour bucket in ms since epoch (UTC).

    Crypto anchors are hour-bucketed since the 1H cache ticks every hour and
    refs that reference recent High/Low can roll within a single day.
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    HOUR_MS = 3_600_000
    return (int(now_ms) // HOUR_MS) * HOUR_MS


# ---------------------------------------------------------------------------
# Read path (used by dashboard tabs)
# ---------------------------------------------------------------------------

def load_refs(asset: str) -> Optional[pd.DataFrame]:
    """Read precomputed reference levels. Returns ``None`` if missing."""
    p = refs_path(asset)
    if not p.exists():
        return None
    try:
        return pd.read_parquet(p)
    except Exception:
        return None


def load_recs(asset: str) -> Optional[pd.DataFrame]:
    """Read precomputed ma_touch recommendations. Returns ``None`` if missing."""
    p = recs_path(asset)
    if not p.exists():
        return None
    try:
        return pd.read_parquet(p)
    except Exception:
        return None


def precompute_status(asset: str) -> dict:
    """File mtime + row counts for the dashboard caption."""
    out: dict = {"refs_mtime": None, "recs_mtime": None, "n_symbols": 0}
    rp, cp = refs_path(asset), recs_path(asset)
    if rp.exists():
        out["refs_mtime"] = rp.stat().st_mtime
        try:
            out["n_symbols"] = len(pd.read_parquet(rp, columns=["symbol"]))
        except Exception:
            pass
    if cp.exists():
        out["recs_mtime"] = cp.stat().st_mtime
    return out


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

def _write_atomic(df: pd.DataFrame, path: Path) -> None:
    """``df`` → ``path`` via .tmp + ``os.replace`` for crash-safe reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Staleness + merge
# ---------------------------------------------------------------------------

def _stale_symbols(
    existing: Optional[pd.DataFrame],
    current_mtimes: dict[str, float],
    *,
    anchor_ms: Optional[int] = None,
) -> list[str]:
    """Symbols that need recomputation under the current ``(mtime, anchor)`` state.

    Stale if ANY of:
      - no existing file / no ``data_mtime`` column (cold start)
      - ``anchor_ms`` arg passed but file lacks ``anchor_ms`` column
      - file-wide ``anchor_ms`` mismatches current (date/hour roll → all stale)
      - per-symbol parquet mtime advanced past stored ``data_mtime``
      - symbol new (not in existing at all)
    """
    if existing is None or existing.empty or "data_mtime" not in existing.columns:
        return list(current_mtimes.keys())

    if anchor_ms is not None:
        if "anchor_ms" not in existing.columns:
            return list(current_mtimes.keys())
        anchor_col = existing["anchor_ms"].dropna()
        if anchor_col.empty:
            return list(current_mtimes.keys())
        try:
            stored_anchor = int(anchor_col.iloc[0])
        except (ValueError, TypeError):
            return list(current_mtimes.keys())
        if stored_anchor != anchor_ms:
            return list(current_mtimes.keys())

    have = dict(zip(existing["symbol"].astype(str), existing["data_mtime"].astype(float)))
    stale: list[str] = []
    for sym, mt in current_mtimes.items():
        prev = have.get(sym)
        if prev is None or mt > prev:
            stale.append(sym)
    return stale


def _merge_rows(
    existing: Optional[pd.DataFrame],
    fresh: pd.DataFrame,
    current_mtimes: dict[str, float],
    *,
    anchor_ms: Optional[int] = None,
) -> pd.DataFrame:
    """Overlay ``fresh`` on ``existing`` (drop removed symbols, add new).

    Keyed on ``symbol``. ``data_mtime`` of fresh rows is stamped from the
    current_mtimes snapshot; ``anchor_ms`` if given is stamped uniformly.
    """
    fresh = fresh.copy()
    if not fresh.empty:
        fresh["data_mtime"] = fresh["symbol"].astype(str).map(current_mtimes).astype(float)

    if existing is None or existing.empty:
        merged = fresh.reset_index(drop=True)
    else:
        keep_mask = existing["symbol"].astype(str).isin(current_mtimes.keys())
        keep_mask &= ~existing["symbol"].astype(str).isin(fresh["symbol"].astype(str))
        kept = existing.loc[keep_mask]
        merged = pd.concat([kept, fresh], ignore_index=True, sort=False).reset_index(drop=True)

    if anchor_ms is not None and not merged.empty:
        merged["anchor_ms"] = int(anchor_ms)
    return merged


# ---------------------------------------------------------------------------
# REFS loaders (per asset)
# ---------------------------------------------------------------------------

def _refs_loader_stock(asset: str):
    """Return ``cache_loader(sym, n)`` for stock ``compute_reference_levels``."""
    cache = _symbol_cache_dir(asset)

    def _loader(sym: str, n: int):
        return load_cache_tails(cache / f"{sym}.parquet", n)

    return _loader


def _refs_loader_crypto():
    """Return ``cache_loader(sym, gran, n)`` for crypto refs.

    Lazy import so the stock-only path doesn't pull in crypto deps.
    """
    from dashboards.live._crypto_compute import (
        DAILY_CANDLE_LIMIT, HOURLY_CANDLE_LIMIT,
        load_cache_tails as _crypto_load_tails,
    )

    def _loader(sym: str, gran: str, n: int):
        limit = HOURLY_CANDLE_LIMIT if gran == "1h" else DAILY_CANDLE_LIMIT
        return _crypto_load_tails(sym, gran, max(n, limit))

    return _loader


# ---------------------------------------------------------------------------
# RECS — ma_touch evaluator wrapper (replaces old gate_pass-only recs)
# ---------------------------------------------------------------------------

def _compute_recs(asset: str, symbols: list[str]) -> pd.DataFrame:
    """Per-symbol ma_touch eval → DataFrame.

    Wraps ``scripts._common.recommend_runner._row_for_symbol`` (the same engine
    that ``scripts/{asset}/ma_touch/recommend.py`` and ``/recs`` skill use).
    Each row gets per-TF signal flags, MA prices/distances/angles, and the
    aggregated ``count_signal_ma_touch_total`` / ``signal_ma_touch_timeframes_passed``
    columns. The dashboard tables merge this in by ``symbol``.

    Failures on individual symbols are silently dropped (returns None upstream).
    """
    from scripts._common.recommend_runner import _row_for_symbol

    rows: list[dict] = []
    for sym in symbols:
        try:
            row = _row_for_symbol(asset, sym)
        except Exception:
            row = None
        if row is not None:
            rows.append(row)
    if not rows:
        # Even with no passing rows we return an empty frame with the symbol
        # column so the merge schema is stable.
        return pd.DataFrame({"symbol": pd.Series([], dtype=str)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

def precompute(
    asset: str,
    *,
    force: bool = False,
    verbose: bool = True,
    now_ts: Optional[pd.Timestamp] = None,
) -> dict:
    """Refresh ``_refs.parquet`` and ``_recs.parquet`` for ``asset``.

    Incremental by default: a symbol's row is recomputed only when its source
    parquet mtime advanced past the stored ``data_mtime`` OR the file-wide
    ``anchor_ms`` rolled (date for stock, hour for crypto). ``force=True``
    bypasses both checks and recomputes every symbol.

    Returns stats::
      {asset, n_total, refs_refreshed, recs_refreshed, refs_kept, recs_kept,
       took_s, refs_path, recs_path, anchor_ms}
    """
    if asset not in SUPPORTED_ASSETS:
        raise ValueError(f"unsupported asset {asset!r} — must be one of {SUPPORTED_ASSETS}")

    is_crypto = asset == "crypto"

    t0 = time.perf_counter()
    symbols = list_symbols(asset)
    n_total = len(symbols)

    if is_crypto:
        anchor_ms = _crypto_anchor_ms(
            now_ms=int(pd.Timestamp(now_ts).value // 1_000_000) if now_ts is not None else None
        )
    else:
        anchor_ms = _stock_anchor_ms(now_ts=now_ts)

    if not symbols:
        if verbose:
            print(f"[precompute] no cached symbols under data/cache/{asset}/ — nothing to do")
        return {
            "asset": asset, "n_total": 0,
            "refs_refreshed": 0, "recs_refreshed": 0,
            "refs_kept": 0, "recs_kept": 0,
            "took_s": 0.0,
            "refs_path": str(refs_path(asset)),
            "recs_path": str(recs_path(asset)),
            "anchor_ms": anchor_ms,
        }

    mtimes = _symbol_mtimes(asset, symbols)

    # ── REFS ────────────────────────────────────────────────────────────
    existing_refs = None if force else load_refs(asset)
    stale_refs = (
        symbols if force
        else _stale_symbols(existing_refs, mtimes, anchor_ms=anchor_ms)
    )
    if verbose:
        print(f"[precompute][{asset}] refs: {len(stale_refs)}/{n_total} symbols to compute "
              f"({'force' if force else 'incremental'}, anchor_ms={anchor_ms})")
    if stale_refs:
        if is_crypto:
            from dashboards.live._crypto_compute import (
                compute_reference_levels as _crypto_compute_refs,
            )
            crypto_loader = _refs_loader_crypto()
            fresh_refs = _crypto_compute_refs(
                stale_refs, cache_loader=crypto_loader, now_ms=anchor_ms,
            )
        else:
            stock_now_ts = (
                pd.Timestamp(anchor_ms, unit="ms")
                if anchor_ms is not None else None
            )
            loader = _refs_loader_stock(asset)
            fresh_refs = compute_reference_levels(
                stale_refs, cache_loader=loader, now_ts=stock_now_ts,
            )
        merged_refs = _merge_rows(existing_refs, fresh_refs, mtimes, anchor_ms=anchor_ms)
    else:
        fresh_refs = pd.DataFrame()
        merged_refs = existing_refs if existing_refs is not None else pd.DataFrame()
        if anchor_ms is not None and not merged_refs.empty:
            merged_refs = merged_refs.copy()
            merged_refs["anchor_ms"] = int(anchor_ms)

    if not merged_refs.empty:
        merged_refs = merged_refs.sort_values("symbol").reset_index(drop=True)
        _write_atomic(merged_refs, refs_path(asset))

    # kept = 기존 파일에서 그대로 살아남은 행 수 = merged - fresh.
    # (fresh 가 stale 보다 적을 수 있음 — 평가 실패 종목은 drop 됨.)
    refs_kept = max(0, len(merged_refs) - len(fresh_refs))

    # ── RECS (ma_touch) ─────────────────────────────────────────────────
    # ma_touch evaluates "today's bar" against MA10/MA20 — same wall-clock
    # anchor logic applies (yesterday's signal is stale on a new day). Use
    # the same anchor_ms trigger as refs.
    existing_recs = None if force else load_recs(asset)
    stale_recs = (
        symbols if force
        else _stale_symbols(existing_recs, mtimes, anchor_ms=anchor_ms)
    )
    if verbose:
        print(f"[precompute][{asset}] recs: {len(stale_recs)}/{n_total} symbols to compute")
    if stale_recs:
        fresh_recs = _compute_recs(asset, stale_recs)
        merged_recs = _merge_rows(existing_recs, fresh_recs, mtimes, anchor_ms=anchor_ms)
    else:
        fresh_recs = pd.DataFrame()
        merged_recs = existing_recs if existing_recs is not None else pd.DataFrame()
        if anchor_ms is not None and not merged_recs.empty:
            merged_recs = merged_recs.copy()
            merged_recs["anchor_ms"] = int(anchor_ms)

    if not merged_recs.empty:
        merged_recs = merged_recs.sort_values("symbol").reset_index(drop=True)
        _write_atomic(merged_recs, recs_path(asset))

    recs_kept = max(0, len(merged_recs) - len(fresh_recs))
    took = time.perf_counter() - t0

    stats = {
        "asset": asset,
        "n_total": n_total,
        "refs_refreshed": len(stale_refs),
        "recs_refreshed": len(stale_recs),
        "refs_kept": refs_kept,
        "recs_kept": recs_kept,
        "took_s": round(took, 2),
        "refs_path": str(refs_path(asset)),
        "recs_path": str(recs_path(asset)),
        "anchor_ms": anchor_ms,
    }
    if verbose:
        print(f"[precompute][{asset}] done in {took:.2f}s — "
              f"refs refreshed {stats['refs_refreshed']}, kept {stats['refs_kept']}; "
              f"recs refreshed {stats['recs_refreshed']}, kept {stats['recs_kept']}")
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from data._venv_guard import require_project_venv
    require_project_venv()

    ap = argparse.ArgumentParser(
        description="Precompute dashboard views (refs + recs) — kr / us / crypto"
    )
    ap.add_argument("--asset", choices=list(SUPPORTED_ASSETS) + ["all"], default="all",
                    help="kr / us / crypto / all (default: all)")
    ap.add_argument("--force", action="store_true",
                    help="Recompute every symbol, ignoring data_mtime + anchor_ms")
    args = ap.parse_args()

    assets = list(SUPPORTED_ASSETS) if args.asset == "all" else [args.asset]
    all_stats = []
    for a in assets:
        stats = precompute(a, force=args.force)
        all_stats.append(stats)
    print(json.dumps(all_stats, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
