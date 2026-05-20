"""Visual review 저장 헬퍼.

- `reviews/{SYMBOL}/{YYYYMMDD}.json` 로드/저장
- `coin_state.parquet` upsert (특정 날짜 reviews 를 모아 한 줄/symbol 갱신)

사용 예 (모듈):

    from research.visual_review.store import aggregate_state, load_review
    aggregate_state("20260519")
    review = load_review("BTCUSDT", "20260519")

CLI:

    .venv/Scripts/python.exe -m research.visual_review.store aggregate 20260519
"""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
VR = ROOT / "data" / "cache" / "crypto" / "visual_review"
REVIEWS = VR / "reviews"
STATE = VR / "coin_state.parquet"
KST = ZoneInfo("Asia/Seoul")


def load_review(symbol: str, date_str: str) -> Optional[dict]:
    """단일 review JSON 읽기 (없으면 None)."""
    p = REVIEWS / symbol / f"{date_str}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_review(symbol: str, date_str: str, payload: dict) -> Path:
    """단일 review JSON 저장."""
    p = REVIEWS / symbol / f"{date_str}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _review_to_row(d: dict, date_str: str) -> dict:
    tf_1m = d.get("tf_1m") or {}
    tf_1w = d.get("tf_1w") or {}
    tf_1d = d.get("tf_1d") or {}
    charts = d.get("charts") or {}
    return {
        "symbol": d["symbol"],
        "last_review_date": pd.to_datetime(date_str, format="%Y%m%d").date(),
        "state_1m": tf_1m.get("state"),
        "state_1w": tf_1w.get("state"),
        "state_1d": tf_1d.get("state"),
        "micro_action_1m": tf_1m.get("micro_action"),
        "micro_action_1w": tf_1w.get("micro_action"),
        "micro_action_1d": tf_1d.get("micro_action"),
        "volume_flag_1m": tf_1m.get("volume_flag"),
        "volume_flag_1w": tf_1w.get("volume_flag"),
        "volume_flag_1d": tf_1d.get("volume_flag"),
        "tf_consistency": d.get("tf_consistency"),
        "verdict": d.get("verdict"),
        "verdict_reason": d.get("verdict_reason", ""),
        "note": (tf_1d.get("note") or tf_1w.get("note") or tf_1m.get("note") or ""),
        "chart_path_1m": charts.get("1m"),
        "chart_path_1w": charts.get("1w"),
        "chart_path_1d": charts.get("1d"),
    }


def aggregate_state(date_str: Optional[str] = None, verbose: bool = True) -> pd.DataFrame:
    """해당 날짜의 모든 reviews 를 모아 coin_state.parquet upsert.

    Returns: 전체 merged DataFrame
    """
    if date_str is None:
        date_str = datetime.now(KST).strftime("%Y%m%d")
    rows = []
    for sym_dir in sorted(REVIEWS.iterdir()) if REVIEWS.exists() else []:
        if not sym_dir.is_dir():
            continue
        p = sym_dir / f"{date_str}.json"
        if not p.exists():
            continue
        rows.append(_review_to_row(json.loads(p.read_text(encoding="utf-8")), date_str))
    new_df = pd.DataFrame(rows)
    if verbose:
        print(f"Loaded {len(new_df)} reviews from {date_str}")
    if STATE.exists():
        old = pd.read_parquet(STATE)
        for c in new_df.columns:
            if c not in old.columns:
                old[c] = None
        old = old[~old["symbol"].isin(new_df["symbol"])] if not new_df.empty else old
        merged = pd.concat([old, new_df], ignore_index=True).sort_values("symbol").reset_index(drop=True)
    else:
        merged = new_df.sort_values("symbol").reset_index(drop=True)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(STATE, index=False)
    if verbose:
        print(f"Saved {len(merged)} rows -> {STATE.relative_to(ROOT)}")
    return merged


def _cli():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="visual_review store helpers")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_agg = sub.add_parser("aggregate", help="reviews/<sym>/<date>.json -> coin_state.parquet")
    p_agg.add_argument("date", nargs="?", default=None, help="YYYYMMDD (default: today KST)")
    p_agg.add_argument("--quiet", action="store_true")
    p_show = sub.add_parser("show", help="print current coin_state.parquet")
    p_show.add_argument("--cols", default="symbol,state_1m,state_1w,state_1d,tf_consistency,verdict",
                         help="comma-separated columns to show")
    a = ap.parse_args()
    if a.cmd == "aggregate":
        merged = aggregate_state(a.date, verbose=not a.quiet)
        cols = ["symbol", "state_1m", "state_1w", "state_1d", "tf_consistency", "verdict"]
        if not a.quiet:
            print("\n" + merged[cols].to_string(index=False))
            print("\nVerdict counts:")
            print(merged["verdict"].value_counts())
    elif a.cmd == "show":
        df = pd.read_parquet(STATE)
        cols = [c.strip() for c in a.cols.split(",") if c.strip()]
        print(df[cols].to_string(index=False))


if __name__ == "__main__":
    _cli()
