"""Visual review 차트 렌더.

표준 출력 경로: `data/cache/crypto/visual_review/charts/{SYMBOL}/{YYYYMMDD}/{SYMBOL}_{tf}.png`

사용 예 (모듈):

    from research.visual_review.render import render_charts
    render_charts(["BTCUSDT", "TRXUSDT"], tfs=["1m", "1w", "1d"])

CLI:

    .venv/Scripts/python.exe -m research.visual_review.render BTCUSDT TRXUSDT --tfs 1m,1w,1d
"""
from __future__ import annotations
import argparse, sys, time
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

import pandas as pd
import mplfinance as mpf

from data.loader import load_ohlcv

ROOT = Path(__file__).resolve().parents[2]
CHARTS_ROOT = ROOT / "data" / "cache" / "crypto" / "visual_review" / "charts"
KST = ZoneInfo("Asia/Seoul")
BARS = 200
RULE_MAP = {"1d": None, "1w": "W-MON", "1m": "ME"}


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for need in ("open", "high", "low", "close", "volume"):
        if need in cols:
            rename[cols[need]] = need.capitalize()
    df = df.rename(columns=rename)
    if "timestamp" in df.columns:
        idx = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
        df = df.set_index(idx)
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    return df[["Open", "High", "Low", "Close", "Volume"]]


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    return df.resample(rule).agg(agg).dropna()


def _render_one(df_full: pd.DataFrame, symbol: str, tf_label: str, out_path: Path, bars: int = BARS) -> tuple[int, str]:
    ma10 = df_full["Close"].rolling(10).mean()
    ma20 = df_full["Close"].rolling(20).mean()
    ma50 = df_full["Close"].rolling(50).mean()
    df = df_full.tail(bars)
    addplots = []
    for ma, color in ((ma10, "gold"), (ma20, "red"), (ma50, "blue")):
        s = ma.tail(bars)
        if s.notna().any():
            addplots.append(mpf.make_addplot(s, color=color, width=0.8))
    span = f"{df.index[0].date()} ~ {df.index[-1].date()}"
    mpf.plot(
        df,
        type="candle",
        style="charles",
        volume=True,
        addplot=addplots,
        title=f"{symbol} - {tf_label} ({len(df)} bars - {span})  MA10/20/50",
        figsize=(14, 8),
        warn_too_much_data=10**7,
        savefig=dict(fname=str(out_path), dpi=110, bbox_inches="tight"),
    )
    return len(df), span


def render_symbol(symbol: str, tfs: Sequence[str], date_str: str, bars: int = BARS, asset: str = "crypto", verbose: bool = True) -> dict[str, Path]:
    """단일 종목, 여러 TF 렌더.

    Returns: {tf: Path}
    """
    df_1d = _normalize(load_ohlcv(asset, symbol, "1d"))
    out_dir = CHARTS_ROOT / symbol / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_paths: dict[str, Path] = {}
    if verbose:
        print(f"[{symbol}]")
    for tf in tfs:
        tf_l = tf.lower()
        if tf_l not in RULE_MAP:
            raise ValueError(f"unsupported tf: {tf}")
        rule = RULE_MAP[tf_l]
        df_full = df_1d if rule is None else _resample(df_1d, rule)
        if len(df_full) < 10:
            if verbose:
                print(f"  {tf_l}: SKIP (only {len(df_full)} bars)")
            continue
        out = out_dir / f"{symbol}_{tf_l}.png"
        t0 = time.perf_counter()
        n, span = _render_one(df_full, symbol, tf_l.upper(), out, bars=bars)
        dt = time.perf_counter() - t0
        if verbose:
            print(f"  {tf_l.upper()}: {n} bars ({span}) ({dt:.2f}s) -> {out.relative_to(ROOT)}")
        out_paths[tf_l] = out
    return out_paths


def render_charts(
    symbols: Iterable[str],
    tfs: Sequence[str] = ("1m", "1w", "1d"),
    date_str: Optional[str] = None,
    bars: int = BARS,
    asset: str = "crypto",
    warmup: bool = True,
    verbose: bool = True,
) -> dict[str, dict[str, Path]]:
    """여러 종목 일괄 렌더.

    Args:
        symbols: 종목 리스트 (예: ["BTCUSDT", "TRXUSDT"])
        tfs: TF 리스트, default ("1m", "1w", "1d")
        date_str: YYYYMMDD, default = 오늘 KST
        bars: 한 차트당 봉 수 (default 200)
        asset: 자산 prefix ("crypto" 만 현재 지원)
        warmup: 첫 mpf.plot 호출 비용 흡수용 사전 호출 (기본 True)
        verbose: 진행 로그 출력

    Returns:
        {symbol: {tf: png_path}}
    """
    if date_str is None:
        date_str = datetime.now(KST).strftime("%Y%m%d")
    if warmup:
        # 첫 mpf.plot 호출은 1~3초 더 걸림 — 워밍업으로 본 작업 시간 정확화
        sym0 = next(iter(symbols))
        df_w = _normalize(load_ohlcv(asset, sym0, "1d"))
        tmp = CHARTS_ROOT / "_warmup.png"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        _render_one(df_w, sym0, "1D", tmp, bars=50)
    t_all = time.perf_counter()
    results: dict[str, dict[str, Path]] = {}
    for s in symbols:
        results[s] = render_symbol(s, tfs, date_str, bars=bars, asset=asset, verbose=verbose)
    if verbose:
        print(f"\nDONE - {len(results)} symbols x {len(tfs)} TFs in {time.perf_counter() - t_all:.1f}s")
        print(f"Out: {CHARTS_ROOT}/<SYMBOL>/{date_str}/")
    return results


def _cli():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Render visual_review charts.")
    ap.add_argument("symbols", nargs="+", help="symbols (e.g. BTCUSDT TRXUSDT)")
    ap.add_argument("--tfs", default="1m,1w,1d", help="comma list, default 1m,1w,1d")
    ap.add_argument("--date", default=None, help="YYYYMMDD (default: today KST)")
    ap.add_argument("--bars", type=int, default=BARS)
    ap.add_argument("--no-warmup", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    tfs = [t.strip() for t in a.tfs.split(",") if t.strip()]
    render_charts(
        a.symbols,
        tfs=tfs,
        date_str=a.date,
        bars=a.bars,
        warmup=not a.no_warmup,
        verbose=not a.quiet,
    )


if __name__ == "__main__":
    _cli()
