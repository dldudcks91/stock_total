"""Crypto cache compute: parquet tails → reference levels → pct columns.

Mirrors the stock-side ``dashboards/_stock_grid`` module but for the Bitget
1H + 1D parquet schema (lowercase OHLC, int64 UTC ms ``timestamp`` column).

Anchoring model
---------------
Stock caches are anchored to the cache's last bar — values are valid for as
long as the underlying parquet doesn't change. Crypto caches are anchored to
*wall-clock now* so a stale cache yields ``None`` instead of mislabeling. The
caller buckets ``now_ms`` to the hour for caching:

    now_bucket_h = now_ms // HOUR_MS
    refs = compute_reference_levels(symbols, now_ms=now_bucket_h * HOUR_MS)

Within one hour, the bar-at-or-before lookups don't change, so the cache key
``(symbols, now_bucket_h)`` is correct and lets live-price refreshes hit cache.

Two-stage pattern
-----------------
``compute_reference_levels`` is the *heavy* pass (1H + 1D parquet read per
symbol, MA / HL math). It is price-independent — caching it without prices
in the key is what makes live-price refresh O(n_symbols) instead of O(n × W).

``apply_current_prices`` is the *cheap* per-rerun pass that combines the
reference levels with the latest mark prices into pct columns. Pure pandas,
~10ms for ~1000 symbols.

The legacy ``compute_from_cache`` composes both for backward compatibility
with ``scripts/misc/bench_bitget_table.py``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Constants — windows, periods, granularities
# ---------------------------------------------------------------------------

PERIODS_H: list[int] = [1, 4]            # hourly fixed period columns
PERIODS_D: list[int] = [3, 7, 14, 28]    # daily fixed period columns
MA_PERIODS: tuple[int, int] = (10, 20)   # short / long MA

# MA Interval — bar size for MA10/MA20 columns. ("1h" / "4h" stride-sample the
# 1H cache; "1d" / "1w" use the 1D cache.)
MA_INTERVAL_OPTIONS_CRYPTO: list[str] = ["1h", "4h", "1d", "1w"]
DEFAULT_MA_INTERVAL_CRYPTO: str = "1d"

# HL Lookback — calendar window for max(High) / min(Low) Δ%. "24h" reads from
# the 1H cache; everything else uses the 1D cache.
HL_LOOKBACK_OPTIONS_CRYPTO: list[str] = ["24h", "7d", "28d", "90d", "1y"]
DEFAULT_HL_LOOKBACK_CRYPTO: str = "28d"

# (granularity, stride): "1w" stride=7 on the 1D cache, etc.
MA_INTERVAL_SPECS: dict[str, tuple[str, int]] = {
    "1h": ("1h", 1),
    "4h": ("1h", 4),
    "1d": ("1d", 1),
    "1w": ("1d", 7),
}

# (granularity, num_bars): "24h" = 24 bars of 1H cache; "1y" = 365 bars of 1D.
HL_LOOKBACK_SPECS: dict[str, tuple[str, int]] = {
    "24h": ("1h", 24),
    "7d": ("1d", 7),
    "28d": ("1d", 28),
    "90d": ("1d", 90),
    "1y": ("1d", 365),
}

HOUR_MS = 3_600_000
DAY_MS = 86_400_000

# Default cache-tail sizes for the per-symbol loader. ≥ longest derived window.
HOURLY_CANDLE_LIMIT = 30   # ≥ MA20·stride for hourly MA + 24h lookback + PERIODS_H
DAILY_CANDLE_LIMIT = 380   # ≥ 1y lookback (365) + 20·7 (1w MA20)

CANDLE_FETCH_CAP = 1000    # safety cap on number of visible symbols per compute pass


# ---------------------------------------------------------------------------
# Cache tail loader (lowercase OHLC — Bitget schema)
# ---------------------------------------------------------------------------

_CACHE_ROOT = Path(__file__).resolve().parents[2] / "data" / "cache" / "crypto"


def load_cache_tails(
    symbol: str, gran: str, n: int,
    *,
    cache_root: Optional[Path] = None,
) -> Optional[dict[str, np.ndarray]]:
    """Read the last ``n`` rows of (timestamp, close, high, low) from a parquet.

    Returns ``None`` on miss / error. Arrays are oldest→newest. ``timestamp``
    is int64 UTC ms (matches the on-disk schema); ``close/high/low`` are
    float64. May be shorter than ``n`` if the cache has fewer rows.

    The single source of truth wrapped by the dashboard's ``@st.cache_data``
    layer — keep this pure (no streamlit imports) so unit tests can call it
    directly.
    """
    root = cache_root or _CACHE_ROOT
    path = root / gran / f"{symbol}.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path, columns=["timestamp", "close", "high", "low"])
    except Exception:
        return None
    if df.empty:
        return None
    tail = df.tail(n) if n and n < len(df) else df
    return {
        "timestamp": tail["timestamp"].to_numpy(dtype=np.int64, copy=False),
        "close": tail["close"].to_numpy(dtype=np.float64, copy=False),
        "high": tail["high"].to_numpy(dtype=np.float64, copy=False),
        "low": tail["low"].to_numpy(dtype=np.float64, copy=False),
    }


# ---------------------------------------------------------------------------
# Bar-at-or-before lookup
# ---------------------------------------------------------------------------

def _close_at_or_before(
    ts: np.ndarray, closes: np.ndarray, target_ms: int, tol_ms: int,
) -> Optional[float]:
    """Return close of the bar whose timestamp is ≤ target_ms, within tolerance.

    Used for wall-clock-anchored lookups: ``target_ms`` is the wall-clock
    instant we want a price for, and the bar at-or-before it must be no more
    than ``tol_ms`` (typically 1 bar interval) older — otherwise the cache
    doesn't actually cover that point in time and we return ``None``.
    """
    if ts.size == 0:
        return None
    idx = int(np.searchsorted(ts, target_ms, side="right")) - 1
    if idx < 0:
        return None
    if target_ms - int(ts[idx]) > tol_ms:
        return None
    val = float(closes[idx])
    if not np.isfinite(val):
        return None
    return val


# ---------------------------------------------------------------------------
# Reference levels (heavy pass, price-independent)
# ---------------------------------------------------------------------------

def compute_reference_levels(
    symbols: list[str],
    *,
    ma_intervals: list[str] = MA_INTERVAL_OPTIONS_CRYPTO,
    hl_lookbacks: list[str] = HL_LOOKBACK_OPTIONS_CRYPTO,
    periods_h: list[int] = PERIODS_H,
    periods_d: list[int] = PERIODS_D,
    ma_periods: tuple[int, int] = MA_PERIODS,
    cache_loader=load_cache_tails,
    now_ms: Optional[int] = None,
) -> pd.DataFrame:
    """Price-independent reference levels for the crypto cache table.

    Returns one row per symbol with:
      - ``prev_{n}h`` / ``prev_{n}d`` — close of the wall-clock-anchored bar
        at lag n (None if stale / out of range)
      - ``ma{short|long}__{label}`` — SMA of stride-sampled closes for each
        MA Interval label in ``MA_INTERVAL_SPECS``
      - ``high__{label}`` / ``low__{label}`` — max/min over each HL Lookback
        window in ``HL_LOOKBACK_SPECS``

    Pair with ``apply_current_prices`` to derive pct_* columns. Splitting the
    two lets the heavy parquet-read pass be cached without live-price tuples
    in the cache key — only the cheap apply pass runs each rerun.
    """
    import time as _time
    if now_ms is None:
        now_ms = int(_time.time() * 1000)

    short, long_ = ma_periods
    max_ma = max(short, long_)

    parsed_ma = [(iv, *MA_INTERVAL_SPECS[iv]) for iv in ma_intervals]
    parsed_hl = [(lb, *HL_LOOKBACK_SPECS[lb]) for lb in hl_lookbacks]

    # How many tail bars do we need from each granularity?
    need_h = max(periods_h) + 2
    need_d = max(periods_d) + 2
    for (_, gran, stride) in parsed_ma:
        req = max_ma * stride + 2
        if gran == "1h":
            need_h = max(need_h, req)
        else:
            need_d = max(need_d, req)
    for (_, gran, num_bars) in parsed_hl:
        req = num_bars + 2
        if gran == "1h":
            need_h = max(need_h, req)
        else:
            need_d = max(need_d, req)

    prev_keys_h = [f"prev_{n}h" for n in periods_h]
    prev_keys_d = [f"prev_{n}d" for n in periods_d]

    ma_cols: list[str] = []
    for (label, _, _) in parsed_ma:
        ma_cols.extend([f"ma{short}__{label}", f"ma{long_}__{label}"])
    hl_cols: list[str] = []
    for (label, _, _) in parsed_hl:
        hl_cols.extend([f"high__{label}", f"low__{label}"])
    none_cols = prev_keys_h + prev_keys_d + ma_cols + hl_cols

    rows = []
    for sym in symbols:
        row: dict[str, Any] = {"symbol": sym}
        for k in none_cols:
            row[k] = None

        arrs_h = cache_loader(sym, "1h", need_h)
        arrs_d = cache_loader(sym, "1d", need_d)

        # ── Prev close per fixed period (wall-clock anchored) ──
        if arrs_h is not None and arrs_h["close"].size:
            ts_h, cl_h = arrs_h["timestamp"], arrs_h["close"]
            for n, key in zip(periods_h, prev_keys_h):
                prev = _close_at_or_before(ts_h, cl_h, now_ms - (n + 1) * HOUR_MS, HOUR_MS)
                if prev:
                    row[key] = prev
        if arrs_d is not None and arrs_d["close"].size:
            ts_d, cl_d = arrs_d["timestamp"], arrs_d["close"]
            for n, key in zip(periods_d, prev_keys_d):
                prev = _close_at_or_before(ts_d, cl_d, now_ms - (n + 1) * DAY_MS, DAY_MS)
                if prev:
                    row[key] = prev

        # ── MA per MA Interval (raw average, price-free) ──
        for (label, gran, stride) in parsed_ma:
            arrs = arrs_h if gran == "1h" else arrs_d
            bar_ms = HOUR_MS if gran == "1h" else DAY_MS
            if arrs is None or arrs["close"].size == 0:
                continue
            ts = arrs["timestamp"]
            closes = arrs["close"]
            if now_ms - int(ts[-1]) > 2 * bar_ms:
                continue
            sampled: list[float] = []
            for k in range(max_ma):
                target = now_ms - k * stride * bar_ms - bar_ms
                val = _close_at_or_before(ts, closes, target, bar_ms)
                if val is None:
                    break
                sampled.append(val)
            if len(sampled) >= short:
                ma_s = sum(sampled[:short]) / short
                if ma_s:
                    row[f"ma{short}__{label}"] = ma_s
            if len(sampled) >= long_:
                ma_l = sum(sampled[:long_]) / long_
                if ma_l:
                    row[f"ma{long_}__{label}"] = ma_l

        # ── HL per HL Lookback (raw max/min, price-free) ──
        for (label, gran, num_bars) in parsed_hl:
            arrs = arrs_h if gran == "1h" else arrs_d
            bar_ms = HOUR_MS if gran == "1h" else DAY_MS
            if arrs is None or arrs["close"].size == 0:
                continue
            ts = arrs["timestamp"]
            highs = arrs["high"]
            lows = arrs["low"]
            if now_ms - int(ts[-1]) > 2 * bar_ms:
                continue
            mask = ts > now_ms - (num_bars + 1) * bar_ms
            if not mask.any():
                continue
            row[f"high__{label}"] = float(highs[mask].max())
            row[f"low__{label}"] = float(lows[mask].min())

        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Apply current prices (cheap pass, runs every rerun)
# ---------------------------------------------------------------------------

def apply_current_prices(
    refs: pd.DataFrame,
    current_prices: dict[str, float],
    *,
    ma_intervals: list[str] = MA_INTERVAL_OPTIONS_CRYPTO,
    hl_lookbacks: list[str] = HL_LOOKBACK_OPTIONS_CRYPTO,
    periods_h: list[int] = PERIODS_H,
    periods_d: list[int] = PERIODS_D,
    ma_periods: tuple[int, int] = MA_PERIODS,
) -> pd.DataFrame:
    """Vectorized: refs (prev/ma/high/low) + live prices → pct_* columns.

    Output schema matches the legacy ``compute_from_cache``:
      ``pct_{n}h``, ``pct_{n}d``, ``pct_ma{p}__{label}``,
      ``high__{label}``, ``low__{label}``,
      ``pct_off_high__{label}``, ``pct_off_low__{label}``.
    """
    short, long_ = ma_periods
    out = pd.DataFrame({"symbol": refs["symbol"].astype(str)})

    cur = refs["symbol"].astype(str).map(current_prices).astype(float)
    cur = cur.where(np.isfinite(cur))

    def _pct(ref_col: str) -> pd.Series:
        if ref_col not in refs.columns:
            return pd.Series([None] * len(refs), index=refs.index, dtype="float64")
        r = pd.to_numeric(refs[ref_col], errors="coerce")
        r = r.where((r != 0) & np.isfinite(r))
        return (cur - r) / r

    for n in periods_h:
        out[f"pct_{n}h"] = _pct(f"prev_{n}h")
    for n in periods_d:
        out[f"pct_{n}d"] = _pct(f"prev_{n}d")
    for label in ma_intervals:
        out[f"pct_ma{short}__{label}"] = _pct(f"ma{short}__{label}")
        out[f"pct_ma{long_}__{label}"] = _pct(f"ma{long_}__{label}")
    for label in hl_lookbacks:
        hi_col, lo_col = f"high__{label}", f"low__{label}"
        if hi_col in refs.columns:
            out[hi_col] = refs[hi_col].values
            out[f"pct_off_high__{label}"] = _pct(hi_col)
        if lo_col in refs.columns:
            out[lo_col] = refs[lo_col].values
            out[f"pct_off_low__{label}"] = _pct(lo_col)
    return out


# ---------------------------------------------------------------------------
# Legacy one-shot compute (preserved for bench script)
# ---------------------------------------------------------------------------

def compute_from_cache(
    current_prices: dict[str, float],
    symbols: list[str],
    *,
    ma_intervals: list[str] = MA_INTERVAL_OPTIONS_CRYPTO,
    hl_lookbacks: list[str] = HL_LOOKBACK_OPTIONS_CRYPTO,
    periods_h: list[int] = PERIODS_H,
    periods_d: list[int] = PERIODS_D,
    ma_periods: tuple[int, int] = MA_PERIODS,
    cache_loader=load_cache_tails,
    now_ms: Optional[int] = None,
) -> pd.DataFrame:
    """One-shot: reference levels + apply prices in a single call.

    Equivalent to ``apply_current_prices(compute_reference_levels(...), prices)``.
    Kept for ``scripts/misc/bench_bitget_table.py``; the dashboard uses the
    two-stage form so live-price refreshes only invalidate the cheap pass.
    """
    refs = compute_reference_levels(
        symbols,
        ma_intervals=ma_intervals,
        hl_lookbacks=hl_lookbacks,
        periods_h=periods_h,
        periods_d=periods_d,
        ma_periods=ma_periods,
        cache_loader=cache_loader,
        now_ms=now_ms,
    )
    return apply_current_prices(
        refs, current_prices,
        ma_intervals=ma_intervals,
        hl_lookbacks=hl_lookbacks,
        periods_h=periods_h,
        periods_d=periods_d,
        ma_periods=ma_periods,
    )
