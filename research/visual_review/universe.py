"""Visual review 대상 종목 선정 (universe).

거래대금(amount, USDT) 상위 N 으로 시총 상위 proxy. classification 의 junk tier 는 제외 가능.

사용 예 (모듈):

    from research.visual_review.universe import top_by_volume
    syms = top_by_volume(100, lookback_days=30, exclude_junk=True)

CLI:

    .venv/Scripts/python.exe -m research.visual_review.universe top 100
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CRYPTO_1D = ROOT / "data" / "cache" / "crypto" / "1d"
CLASSIFICATION = ROOT / "data" / "cache" / "crypto" / "classification.parquet"


def _avg_dollar_volume(symbol: str, lookback_days: int) -> Optional[float]:
    p = CRYPTO_1D / f"{symbol}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p, columns=["amount"])
    if df.empty:
        return None
    tail = df["amount"].tail(lookback_days)
    if tail.empty:
        return None
    return float(tail.mean())


def avg_dollar_volume_table(
    lookback_days: int = 30,
    min_listing_days: int = 0,
    exclude_junk: bool = True,
    classification_path: Path = CLASSIFICATION,
) -> pd.DataFrame:
    """모든 1d 캐시의 평균 거래대금 + classification tier 결합 테이블.

    Returns: columns = [symbol, avg_amount, tier_final, listing_days]
    """
    cls = pd.read_parquet(classification_path) if classification_path.exists() else None
    rows = []
    for p in sorted(CRYPTO_1D.glob("*.parquet")):
        sym = p.stem
        av = _avg_dollar_volume(sym, lookback_days)
        if av is None:
            continue
        rows.append({"symbol": sym, "avg_amount": av})
    df = pd.DataFrame(rows)
    if cls is not None:
        df = df.merge(
            cls[["symbol", "tier_final", "listing_days"]],
            on="symbol", how="left",
        )
    else:
        df["tier_final"] = None
        df["listing_days"] = None
    if exclude_junk:
        df = df[df["tier_final"] != "junk"]
    if min_listing_days > 0:
        df = df[(df["listing_days"].fillna(0)) >= min_listing_days]
    df = df.sort_values("avg_amount", ascending=False).reset_index(drop=True)
    return df


def top_by_volume(
    n: int = 100,
    lookback_days: int = 30,
    min_listing_days: int = 0,
    exclude_junk: bool = True,
) -> list[str]:
    """거래대금 상위 N 종목 리스트."""
    df = avg_dollar_volume_table(
        lookback_days=lookback_days,
        min_listing_days=min_listing_days,
        exclude_junk=exclude_junk,
    )
    return df["symbol"].head(n).tolist()


def split_chunks(symbols: list[str], n_chunks: int) -> list[list[str]]:
    """대략 균등 분할 (앞 chunk 가 1개씩 더 가질 수 있음)."""
    out: list[list[str]] = [[] for _ in range(n_chunks)]
    for i, s in enumerate(symbols):
        out[i % n_chunks].append(s)
    return out


def _cli():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="universe selection")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_top = sub.add_parser("top", help="top N by dollar volume")
    p_top.add_argument("n", type=int, default=100, nargs="?")
    p_top.add_argument("--lookback", type=int, default=30)
    p_top.add_argument("--min-listing-days", type=int, default=0)
    p_top.add_argument("--include-junk", action="store_true")
    p_top.add_argument("--show-table", action="store_true")
    a = ap.parse_args()
    if a.cmd == "top":
        df = avg_dollar_volume_table(
            lookback_days=a.lookback,
            min_listing_days=a.min_listing_days,
            exclude_junk=not a.include_junk,
        )
        head = df.head(a.n)
        if a.show_table:
            print(head.to_string(index=True))
        else:
            print(" ".join(head["symbol"].tolist()))


if __name__ == "__main__":
    _cli()
