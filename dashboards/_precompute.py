"""Precompute & persist dashboard views (refs + recs) to disk.

The KOSPI / NASDAQ / Bitget live tabs used to recompute reference levels
(``compute_reference_levels``) and recommendations (``compute_recommendations``)
on every cold load — each cycle iterates 600–4000 symbols × full parquet reads
× per-strategy passes, which Streamlit's ``@st.cache_data`` only papered over
while the process was alive.

This module replaces the in-memory cache with a **disk cache** per asset:

  data/cache/{asset}/_refs.parquet   ← compute_reference_levels output
  data/cache/{asset}/_recs.parquet   ← compute_recommendations output (kr/us/crypto)

Each file carries two staleness markers:

  - ``data_mtime``  (per row) — the underlying ``{symbol}.parquet`` mtime when
    this row was computed. Per-symbol incremental: only rows whose source
    parquet has changed get recomputed.
  - ``anchor_ms``   (uniform per file) — the wall-clock anchor the file was
    computed for (stock: today midnight in ms; crypto: hour bucket in ms).
    When this changes (next day for stock, next hour for crypto) **all** rows
    are recomputed since prev_Nd / MA / HL are anchored to wall-clock now.

Both triggers feed into ``_stale_symbols`` — a row is stale if either
``data_mtime`` advanced for that symbol or ``anchor_ms`` changed file-wide.

CLI::

    .venv/Scripts/python.exe -m dashboards._precompute --asset kr [--force]
    .venv/Scripts/python.exe -m dashboards._precompute --asset us [--force]
    .venv/Scripts/python.exe -m dashboards._precompute --asset crypto [--force]

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

from dashboards._recommendation import compute_recommendations
from dashboards._stock_grid import (
    CACHE_TAIL_N,
    compute_reference_levels,
    load_cache_tails,
)

# All three assets ship _refs + _recs. Stock uses 1d/1w/1m specs; crypto uses
# 1h/4h/1d/1w specs (see _recommendation._STRATEGY_SPECS_STOCK / _CRYPTO).
SUPPORTED_ASSETS: tuple[str, ...] = ("kr", "us", "crypto")


def _cache_dir(asset: str) -> Path:
    """Cache root for ``asset``. Crypto symbol parquets live under ``1d/``
    (the per-symbol files for 1d candles); the asset root holds the
    precompute outputs (_refs.parquet, _live_snapshot.parquet)."""
    return _ROOT / "data" / "cache" / asset


def _symbol_cache_dir(asset: str) -> Path:
    """Directory holding per-symbol parquets (where ``{SYMBOL}.parquet`` lives).

    For crypto this is ``cache/crypto/1d/`` — symbol discovery uses the 1D
    cache (1h is fetched alongside 1d, so 1d's mtime is the canonical signal).
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
    """All cached symbols for ``asset`` (parquet stems, ``_``-prefixed excluded)."""
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
    """Today midnight (local time, naive) in ms since epoch.

    Stock anchors are day-bucketed: refs are valid until the date rolls over.
    """
    if now_ts is None:
        now_ts = pd.Timestamp.now().normalize()
    return int(pd.Timestamp(now_ts).value // 1_000_000)


def _crypto_anchor_ms(now_ms: Optional[int] = None) -> int:
    """Current hour bucket in ms since epoch (UTC).

    Crypto anchors are hour-bucketed since the 1H cache ticks every hour.
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    HOUR_MS = 3_600_000
    return (int(now_ms) // HOUR_MS) * HOUR_MS


# ---------------------------------------------------------------------------
# Read path (used by dashboard tabs)
# ---------------------------------------------------------------------------

def load_refs(asset: str) -> Optional[pd.DataFrame]:
    """Read precomputed reference levels. Returns ``None`` if file is missing."""
    p = refs_path(asset)
    if not p.exists():
        return None
    try:
        return pd.read_parquet(p)
    except Exception:
        return None


def load_recs(asset: str) -> Optional[pd.DataFrame]:
    """Read precomputed recommendations. Returns ``None`` if file is missing."""
    p = recs_path(asset)
    if not p.exists():
        return None
    try:
        return pd.read_parquet(p)
    except Exception:
        return None


def precompute_status(asset: str) -> dict:
    """File mtime + row counts for the dashboard caption.

    Returns: ``{refs_mtime: float|None, recs_mtime: float|None, n_symbols: int}``.
    All values are best-effort and missing files yield ``None`` mtimes / 0 counts.
    """
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
    """``df`` → ``path`` via .tmp + ``os.replace`` so concurrent readers always
    see a consistent file (never a half-written parquet)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Compute drivers
# ---------------------------------------------------------------------------

def _stale_symbols(
    existing: Optional[pd.DataFrame],
    current_mtimes: dict[str, float],
    *,
    anchor_ms: Optional[int] = None,
) -> list[str]:
    """Symbols that need recomputation under the current ``(mtime, anchor)`` state.

    Triggers (any one → stale):
      - no existing file / no ``data_mtime`` column (cold start)
      - ``anchor_ms`` was passed but the file lacks ``anchor_ms`` (schema upgrade)
      - file-wide ``anchor_ms`` mismatches current — *all* symbols stale, since
        prev_Nd / MA / HL are anchored to wall-clock now
      - symbol's source parquet mtime > stored ``data_mtime`` for that row
      - symbol not present in ``existing`` at all (new cache)
    """
    if existing is None or existing.empty or "data_mtime" not in existing.columns:
        return list(current_mtimes.keys())

    # File-wide anchor check (any mismatch → recompute everything).
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

    # Per-symbol mtime check.
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
    """Overlay ``fresh`` rows on ``existing`` (drop dropped symbols, add new).

    The merge is keyed on ``symbol``; the resulting frame contains exactly the
    symbols present in ``current_mtimes`` (so removed parquets drop out).
    If ``anchor_ms`` is given, the column is stamped uniformly on every row
    of the merged result.
    """
    fresh = fresh.copy()
    fresh["data_mtime"] = fresh["symbol"].astype(str).map(current_mtimes).astype(float)

    if existing is None or existing.empty:
        merged = fresh.reset_index(drop=True)
    else:
        keep_mask = existing["symbol"].astype(str).isin(current_mtimes.keys())
        keep_mask &= ~existing["symbol"].astype(str).isin(fresh["symbol"].astype(str))
        kept = existing.loc[keep_mask]
        # Align columns (union); pandas concat handles missing columns with NaN.
        merged = pd.concat([kept, fresh], ignore_index=True, sort=False).reset_index(drop=True)

    if anchor_ms is not None and not merged.empty:
        merged["anchor_ms"] = int(anchor_ms)
    return merged


def _stock_recs_loaders(asset: str) -> dict:
    """Return ``{interval: loader(sym)}`` dict for stock ``compute_recommendations``.

    Daily reads ``{Open,High,Low,Close,Volume}`` from the asset's cache; weekly
    resamples to W-FRI and monthly to month-end (ME).

    Holds AT MOST one symbol's daily df in the closure scope: same-symbol
    1d/1w/1m calls reuse the read (the original optimization), but switching
    to a new symbol evicts the prior one. Without this eviction the cache
    accumulated all symbols' OHLCV for the full precompute run (~660MB for
    US 3849 symbols).
    """
    cache = _cache_dir(asset)
    _daily_cache: dict[str, Optional[pd.DataFrame]] = {}

    def _daily(sym: str):
        if sym in _daily_cache:
            return _daily_cache[sym]
        _daily_cache.clear()
        path = cache / f"{sym}.parquet"
        if not path.exists():
            _daily_cache[sym] = None
            return None
        try:
            df = pd.read_parquet(path, columns=["Open", "High", "Low", "Close", "Volume"])
        except Exception:
            _daily_cache[sym] = None
            return None
        _daily_cache[sym] = df if not df.empty else None
        return _daily_cache[sym]

    _agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}

    def _weekly(sym: str):
        df = _daily(sym)
        if df is None:
            return None
        return df.resample("W-FRI").agg(_agg).dropna()

    def _monthly(sym: str):
        df = _daily(sym)
        if df is None:
            return None
        return df.resample("ME").agg(_agg).dropna()

    return {"1d": _daily, "1w": _weekly, "1m": _monthly}


def _crypto_recs_loaders() -> dict:
    """Return ``{interval: loader(sym)}`` dict for crypto ``compute_recommendations``.

    Wraps :func:`data.resample.load` so 1h/4h/1d/1w each get their own callable.

    Holds AT MOST one symbol's worth across all granularities. Same-sym
    1h/4h/1d/1w calls reuse reads (1w from 1d cache, 4h from 1h cache);
    switching to a new symbol evicts the prior one's 4 entries.
    Symbols whose parquet is missing return None — recs spec will skip them.
    """
    from data.resample import load as _crypto_load

    _cache: dict[tuple, Optional[pd.DataFrame]] = {}
    _current_sym: list[Optional[str]] = [None]

    def _make(iv: str):
        def _loader(sym: str):
            if _current_sym[0] != sym:
                _cache.clear()
                _current_sym[0] = sym
            key = (sym, iv)
            if key in _cache:
                return _cache[key]
            try:
                df = _crypto_load(sym, iv)
            except (FileNotFoundError, KeyError):
                _cache[key] = None
                return None
            except Exception:
                _cache[key] = None
                return None
            _cache[key] = df if df is not None and not df.empty else None
            return _cache[key]
        return _loader

    return {iv: _make(iv) for iv in ("1h", "4h", "1d", "1w")}


def _refs_loader(asset: str):
    """Return ``cache_loader(sym, n)`` for stock ``compute_reference_levels``."""
    cache = _symbol_cache_dir(asset)

    def _loader(sym: str, n: int):
        return load_cache_tails(cache / f"{sym}.parquet", n)

    return _loader


def _crypto_refs_loader():
    """Return ``cache_loader(sym, gran, n)`` for crypto ``compute_reference_levels``.

    Imported lazily so this module doesn't pull in the crypto compute layer
    when only stock paths are exercised.
    """
    from dashboards.live._crypto_compute import (
        DAILY_CANDLE_LIMIT, HOURLY_CANDLE_LIMIT,
        load_cache_tails as _crypto_load_tails,
    )

    def _loader(sym: str, gran: str, n: int):
        limit = HOURLY_CANDLE_LIMIT if gran == "1h" else DAILY_CANDLE_LIMIT
        return _crypto_load_tails(sym, gran, max(n, limit))

    return _loader


def precompute(
    asset: str,
    *,
    force: bool = False,
    verbose: bool = True,
    now_ts: Optional[pd.Timestamp] = None,
) -> dict:
    """Refresh ``_refs.parquet`` (and ``_recs.parquet`` for stock assets).

    Incremental by default — a symbol's row is recomputed only when its
    source parquet has been modified since the stored ``data_mtime`` OR the
    file-wide ``anchor_ms`` has changed (date roll for stock, hour roll for
    crypto). ``force=True`` recomputes every symbol regardless.

    Returns a stats dict for CLI / log consumption::

        {asset, n_total, refs_refreshed, recs_refreshed, refs_kept, recs_kept,
         took_s, refs_path, recs_path, anchor_ms}

    For crypto, ``recs_*`` fields are 0 and ``recs_path`` is None — the
    strategy recommendation module is stock-only.
    """
    if asset not in SUPPORTED_ASSETS:
        raise ValueError(f"unsupported asset {asset!r} — must be one of {SUPPORTED_ASSETS}")

    is_crypto = asset == "crypto"

    t0 = time.perf_counter()
    symbols = list_symbols(asset)
    n_total = len(symbols)

    # Wall-clock anchor (day bucket for stock, hour bucket for crypto).
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
            "recs_path": None if is_crypto else str(recs_path(asset)),
            "anchor_ms": anchor_ms,
        }

    mtimes = _symbol_mtimes(asset, symbols)

    # ── REFS ──
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
                compute_reference_levels as _crypto_compute,
            )
            crypto_loader = _crypto_refs_loader()
            fresh_refs = _crypto_compute(
                stale_refs, cache_loader=crypto_loader, now_ms=anchor_ms,
            )
        else:
            stock_now_ts = (
                pd.Timestamp(anchor_ms, unit="ms")  # back-convert anchor → naive ts
                if anchor_ms is not None else None
            )
            loader = _refs_loader(asset)
            fresh_refs = compute_reference_levels(
                stale_refs, cache_loader=loader, now_ts=stock_now_ts,
            )
        merged_refs = _merge_rows(existing_refs, fresh_refs, mtimes, anchor_ms=anchor_ms)
    else:
        merged_refs = existing_refs if existing_refs is not None else pd.DataFrame()
        # Stamp anchor on the file even when nothing was recomputed (covers the
        # cold-skip path where existing already has the right anchor — keeps it
        # explicit on disk after every successful run).
        if anchor_ms is not None and not merged_refs.empty:
            merged_refs = merged_refs.copy()
            merged_refs["anchor_ms"] = int(anchor_ms)

    # Keep order canonical (symbol asc) so the parquet is stable diff-wise.
    if not merged_refs.empty:
        merged_refs = merged_refs.sort_values("symbol").reset_index(drop=True)
        _write_atomic(merged_refs, refs_path(asset))

    refs_kept = (len(merged_refs) - len(stale_refs)) if (stale_refs and not merged_refs.empty) else len(merged_refs)

    # ── RECS (kr/us/crypto) ──
    # Recs are NOT wall-clock anchored — they read the cache as-is. Only mtime
    # drives staleness here (no anchor arg passed to _stale_symbols).
    existing_recs = None if force else load_recs(asset)
    stale_recs = symbols if force else _stale_symbols(existing_recs, mtimes)
    if verbose:
        print(f"[precompute][{asset}] recs: {len(stale_recs)}/{n_total} symbols to compute")
    if stale_recs:
        loaders = _crypto_recs_loaders() if is_crypto else _stock_recs_loaders(asset)
        fresh_recs = compute_recommendations(asset, stale_recs, loaders)
        merged_recs = _merge_rows(existing_recs, fresh_recs, mtimes)
    else:
        merged_recs = existing_recs if existing_recs is not None else pd.DataFrame()

    if not merged_recs.empty:
        merged_recs = merged_recs.sort_values("symbol").reset_index(drop=True)
        _write_atomic(merged_recs, recs_path(asset))

    recs_kept = (len(merged_recs) - len(stale_recs)) if (stale_recs and not merged_recs.empty) else len(merged_recs)
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
    sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(
        description="Precompute dashboard views (refs + recs) — kr / us / crypto"
    )
    ap.add_argument("--asset", choices=list(SUPPORTED_ASSETS) + ["all"], default="all",
                    help="kr / us / crypto / all (default: all)")
    ap.add_argument("--force", action="store_true",
                    help="Recompute every symbol, ignoring data_mtime + anchor_ms tracking")
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
