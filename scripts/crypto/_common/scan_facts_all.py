"""전체 코인 facts 갱신 + entry score 계산.

출력:
  data/cache/crypto/visual_review/_scan_facts.parquet   — 5TF flat facts (563 symbols)
  data/cache/crypto/visual_review/_scan_entry_v2.parquet — 1d/4h/1h entry score (전체)
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.stdout.reconfigure(encoding="utf-8")

import warnings
warnings.filterwarnings("ignore")

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

from research.visual_review.facts import compute_facts_all_tfs

CACHE_1D = Path("data/cache/crypto/1d")
OUT_DIR  = Path("data/cache/crypto/visual_review")
WORKERS  = 8
ALL_TFS  = ["1m", "1w", "1d", "4h", "1h"]
ENTRY_TFS = ["1d", "4h", "1h"]


# ── flatten helpers ──────────────────────────────────────────────────────────

def _flat_tf(tf_key: str, tf_dict: dict) -> dict:
    """한 TF facts → flat dict (prefix={tf}_)."""
    p = tf_key + "_"
    rsb = tf_dict.get("recent_strong_bull") or {}
    nma = tf_dict.get("nearest_ma") or {}
    lc  = tf_dict.get("last_candle") or {}
    dma = tf_dict.get("dist_from_ma_atr") or {}
    nma_key = nma.get("ma", "ma10")

    return {
        p + "close":            tf_dict.get("last_close"),
        p + "near_ma":          nma.get("ma"),
        p + "near_dist":        nma.get("dist_pct"),
        p + "stack":            tf_dict.get("ma_stack"),
        p + "ma20_slope":       (tf_dict.get("ma_slopes") or {}).get("ma20"),
        p + "bull_ago":         rsb.get("bars_ago"),
        p + "bull_body":        rsb.get("body_pct"),
        p + "bull_volr":        rsb.get("vol_rank"),
        # entry 전용 컬럼
        p + "atr_pct":          tf_dict.get("atr_pct"),
        p + "adx":              tf_dict.get("adx"),
        p + "range_pos":        tf_dict.get("range_position"),
        p + "near_atr":         dma.get(f"{nma_key}_atr"),
        p + "bull_holding":     rsb.get("holding"),
        p + "bull_max_retrace": rsb.get("max_retrace_pct"),
        p + "acc_score":        lc.get("accumulation_candle_score", 0.0),
        p + "dist_score":       lc.get("distribution_candle_score", 0.0),
    }


def flatten_facts(facts: dict) -> dict:
    row: dict = {"symbol": facts["symbol"]}
    for tf in ALL_TFS:
        tf_dict = facts.get(f"tf_{tf}")
        if tf_dict:
            row.update(_flat_tf(tf, tf_dict))
        else:
            p = tf + "_"
            for sfx in ["close","near_ma","near_dist","stack","ma20_slope",
                        "bull_ago","bull_body","bull_volr",
                        "atr_pct","adx","range_pos","near_atr",
                        "bull_holding","bull_max_retrace","acc_score","dist_score"]:
                row[p + sfx] = None
    gnm = facts.get("global_nearest_ma") or {}
    row["gnm_tf"]   = gnm.get("tf")
    row["gnm_ma"]   = gnm.get("ma")
    row["gnm_dist"] = gnm.get("dist_pct")
    row["risks"]    = ",".join(facts.get("auto_risk_flags") or [])
    return row


# ── entry score (rec_now.py 동일 로직) ──────────────────────────────────────

def entry_score(facts: dict) -> float:
    f1d = facts.get("tf_1d") or {}
    f4h = facts.get("tf_4h") or {}
    f1h = facts.get("tf_1h") or {}
    if not f1d:
        return float("nan")

    s = 0.0
    if f1d.get("ma_stack") == "정배열": s += 0.30
    elif f1d.get("ma_stack") == "역배열": s -= 0.30
    if (f1d.get("ma_slopes") or {}).get("ma20") == "up": s += 0.20
    elif (f1d.get("ma_slopes") or {}).get("ma20") == "down": s -= 0.20

    nma = f1d.get("nearest_ma") or {}
    dma = f1d.get("dist_from_ma_atr") or {}
    nma_key = nma.get("ma", "ma10")
    atr_dist = abs(dma.get(f"{nma_key}_atr") or 99)
    if nma.get("ma") in ("ma10", "ma20") and atr_dist < 1.0:
        s += 0.40 * (1.0 - atr_dist)
    elif nma.get("ma") == "ma50" and atr_dist < 0.5:
        s += 0.20 * (0.5 - atr_dist)

    rsb_1d = f1d.get("recent_strong_bull") or {}
    if rsb_1d.get("holding"):
        bars = rsb_1d.get("bars_ago") or 99
        if bars <= 5: s += 0.40
        elif bars <= 10: s += 0.20

    lc = f1d.get("last_candle") or {}
    s += (lc.get("accumulation_candle_score") or 0.0) * 0.30
    s -= (lc.get("distribution_candle_score") or 0.0) * 0.30

    adx = f1d.get("adx") or 0
    if 25 <= adx <= 50: s += 0.15
    elif adx > 75: s -= 0.15

    for tf_facts, w in ((f4h, 0.10), (f1h, 0.05)):
        if not tf_facts: continue
        if (tf_facts.get("ma_slopes") or {}).get("ma20") == "up": s += w
        if tf_facts.get("ma_stack") == "정배열": s += w * 0.5

    rsb_1h = (f1h or {}).get("recent_strong_bull") or {}
    if rsb_1h.get("holding") and (rsb_1h.get("bars_ago") or 99) <= 12:
        s += 0.10

    return s


# ── worker ───────────────────────────────────────────────────────────────────

def process(symbol: str) -> tuple[str, dict | None]:
    try:
        facts = compute_facts_all_tfs(symbol, asset="crypto", tfs=ALL_TFS)
        return symbol, facts
    except Exception as e:
        return symbol, None


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    symbols = sorted(p.stem for p in CACHE_1D.glob("*.parquet"))
    total = len(symbols)
    print(f"{total} symbols → computing facts (workers={WORKERS}) ...")

    t0 = time.time()
    flat_rows: list[dict] = []
    err_syms: list[str] = []
    done = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(process, sym): sym for sym in symbols}
        for fut in as_completed(futures):
            sym, facts = fut.result()
            done += 1
            if facts is None:
                err_syms.append(sym)
            else:
                row = flatten_facts(facts)
                row["entry_score"] = entry_score(facts)
                flat_rows.append(row)
            if done % 50 == 0 or done == total:
                elapsed = time.time() - t0
                print(f"  [{done}/{total}] {elapsed:.0f}s elapsed, {len(err_syms)} errors")

    df = pd.DataFrame(flat_rows)

    # ── _scan_facts.parquet (5TF flat, 기존 스키마 호환) ──
    scan_cols = ["symbol"]
    for tf in ALL_TFS:
        p = tf + "_"
        scan_cols += [p+s for s in ["close","near_ma","near_dist","stack","ma20_slope",
                                    "bull_ago","bull_body","bull_volr"]]
    scan_cols += ["gnm_tf","gnm_ma","gnm_dist","risks"]
    scan_cols = [c for c in scan_cols if c in df.columns]
    df[scan_cols].to_parquet(OUT_DIR / "_scan_facts.parquet", index=False)
    print(f"\n_scan_facts.parquet  saved: {len(df)} rows")

    # ── _scan_entry_v2.parquet (1d/4h/1h entry facts + score, 전체) ──
    entry_cols = ["symbol"]
    for tf in ENTRY_TFS:
        p = tf + "_"
        entry_cols += [p+s for s in ["close","atr_pct","adx","range_pos","near_ma","near_dist",
                                     "near_atr","stack","ma20_slope","bull_ago","bull_body",
                                     "bull_holding","bull_max_retrace","acc_score","dist_score"]]
    entry_cols += ["risks","entry_score"]
    entry_cols = [c for c in entry_cols if c in df.columns]
    df_entry = df[entry_cols].dropna(subset=["entry_score"]).sort_values("entry_score", ascending=False)
    df_entry.to_parquet(OUT_DIR / "_scan_entry_v2.parquet", index=False)
    print(f"_scan_entry_v2.parquet saved: {len(df_entry)} rows")

    if err_syms:
        print(f"\nErrors ({len(err_syms)}): {err_syms[:10]}")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print("\n=== TOP 20 entry_score ===")
    print(df_entry[["symbol","entry_score","risks"]].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
