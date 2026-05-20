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
KST = ZoneInfo("Asia/Seoul")


def _vr_root(asset: str) -> Path:
    return ROOT / "data" / "cache" / asset / "visual_review"


def _reviews_root(asset: str) -> Path:
    return _vr_root(asset) / "reviews"


def _state_path(asset: str) -> Path:
    return _vr_root(asset) / "coin_state.parquet"


def load_review(symbol: str, date_str: str, asset: str = "crypto") -> Optional[dict]:
    """단일 review JSON 읽기 (없으면 None)."""
    p = _reviews_root(asset) / symbol / f"{date_str}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_review(symbol: str, date_str: str, payload: dict, asset: str = "crypto") -> Path:
    """단일 review JSON 저장."""
    p = _reviews_root(asset) / symbol / f"{date_str}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _review_to_row(d: dict, date_str: str) -> dict:
    """v1/v2 schema 모두 처리. v2 신규 필드는 v1 review 에선 None."""
    tf_1m = d.get("tf_1m") or {}
    tf_1w = d.get("tf_1w") or {}
    tf_1d = d.get("tf_1d") or {}
    charts = d.get("charts") or {}
    scorer = d.get("scorer") or {}

    # v2: tf 안에 observations.recent_action 가 있고, v1 은 tf.note 가 있음
    def _note(tf_block: dict) -> str:
        if "note" in tf_block and tf_block.get("note"):
            return tf_block["note"]
        obs = tf_block.get("observations") or {}
        return obs.get("recent_action", "")

    risk_flags = d.get("risk_flags") or []
    return {
        "symbol": d["symbol"],
        "asset": d.get("asset"),
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
        "confidence_1m": tf_1m.get("confidence"),
        "confidence_1w": tf_1w.get("confidence"),
        "confidence_1d": tf_1d.get("confidence"),
        "tf_consistency": d.get("tf_consistency"),
        "verdict": d.get("verdict"),
        "verdict_confidence": d.get("verdict_confidence"),
        "verdict_reason": d.get("verdict_reason", ""),
        "risk_flags": ",".join(risk_flags) if risk_flags else "",
        "scorer_model": scorer.get("model"),
        "schema_version": scorer.get("schema_version", 1),
        "note": _note(tf_1d) or _note(tf_1w) or _note(tf_1m),
        "chart_path_1m": charts.get("1m"),
        "chart_path_1w": charts.get("1w"),
        "chart_path_1d": charts.get("1d"),
    }


def aggregate_state(date_str: Optional[str] = None, asset: str = "crypto", verbose: bool = True) -> pd.DataFrame:
    """해당 날짜의 모든 reviews 를 모아 coin_state.parquet upsert.

    Returns: 전체 merged DataFrame
    """
    if date_str is None:
        date_str = datetime.now(KST).strftime("%Y%m%d")
    reviews_root = _reviews_root(asset)
    state_path = _state_path(asset)
    rows = []
    for sym_dir in sorted(reviews_root.iterdir()) if reviews_root.exists() else []:
        if not sym_dir.is_dir():
            continue
        p = sym_dir / f"{date_str}.json"
        if not p.exists():
            continue
        rows.append(_review_to_row(json.loads(p.read_text(encoding="utf-8")), date_str))
    new_df = pd.DataFrame(rows)
    if verbose:
        print(f"Loaded {len(new_df)} reviews from {date_str}")
    if state_path.exists():
        old = pd.read_parquet(state_path)
        for c in new_df.columns:
            if c not in old.columns:
                old[c] = None
        old = old[~old["symbol"].isin(new_df["symbol"])] if not new_df.empty else old
        merged = pd.concat([old, new_df], ignore_index=True).sort_values("symbol").reset_index(drop=True)
    else:
        merged = new_df.sort_values("symbol").reset_index(drop=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(state_path, index=False)
    if verbose:
        print(f"Saved {len(merged)} rows -> {state_path.relative_to(ROOT)}")
    return merged


def _cli():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="visual_review store helpers")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_agg = sub.add_parser("aggregate", help="reviews/<sym>/<date>.json -> coin_state.parquet")
    p_agg.add_argument("date", nargs="?", default=None, help="YYYYMMDD (default: today KST)")
    p_agg.add_argument("--asset", default="crypto", choices=["crypto", "kr", "us"])
    p_agg.add_argument("--quiet", action="store_true")
    p_show = sub.add_parser("show", help="print current coin_state.parquet")
    p_show.add_argument("--asset", default="crypto", choices=["crypto", "kr", "us"])
    p_show.add_argument("--cols", default="symbol,state_1m,state_1w,state_1d,tf_consistency,verdict",
                         help="comma-separated columns to show")
    a = ap.parse_args()
    if a.cmd == "aggregate":
        merged = aggregate_state(a.date, asset=a.asset, verbose=not a.quiet)
        cols = ["symbol", "state_1m", "state_1w", "state_1d", "tf_consistency", "verdict"]
        if not a.quiet:
            print("\n" + merged[cols].to_string(index=False))
            print("\nVerdict counts:")
            print(merged["verdict"].value_counts())
    elif a.cmd == "show":
        df = pd.read_parquet(_state_path(a.asset))
        cols = [c.strip() for c in a.cols.split(",") if c.strip()]
        print(df[cols].to_string(index=False))


if __name__ == "__main__":
    _cli()
