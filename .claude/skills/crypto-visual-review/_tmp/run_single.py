"""single 모드 실행: 1종목 1W + 1D 차트 렌더링 → 정식 저장 위치."""
from __future__ import annotations
import sys, time, argparse, json
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import mplfinance as mpf
from data.loader import load_ohlcv

KST = timezone(timedelta(hours=9))
ROOT = Path("data/cache/crypto/visual_review")
BARS = 200

def normalize(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for need in ("open","high","low","close","volume"):
        if need in cols: rename[cols[need]] = need.capitalize()
    df = df.rename(columns=rename)
    if "timestamp" in df.columns:
        idx = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
        df = df.set_index(idx)
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    return df[["Open","High","Low","Close","Volume"]]

def resample(df, rule):
    agg = {"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}
    return df.resample(rule).agg(agg).dropna()

def render(df_full, symbol, tf, out_path, bars=BARS):
    ma10 = df_full["Close"].rolling(10).mean()
    ma20 = df_full["Close"].rolling(20).mean()
    ma50 = df_full["Close"].rolling(50).mean()
    df = df_full.tail(bars)
    addplots = [
        mpf.make_addplot(ma10.tail(bars), color="gold", width=0.8),
        mpf.make_addplot(ma20.tail(bars), color="red",  width=0.8),
        mpf.make_addplot(ma50.tail(bars), color="blue", width=0.8),
    ]
    span = f"{df.index[0].date()} ~ {df.index[-1].date()}"
    mpf.plot(
        df, type="candle", style="charles", volume=True, addplot=addplots,
        title=f"{symbol} · {tf} ({len(df)} bars · {span})  MA10/20/50",
        figsize=(14,8), warn_too_much_data=10**7,
        savefig=dict(fname=str(out_path), dpi=110, bbox_inches="tight"),
    )
    return len(df), span

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    args = ap.parse_args()
    symbol = args.symbol

    now_kst = datetime.now(KST)
    yyyymmdd = now_kst.strftime("%Y%m%d")
    chart_dir = ROOT / "charts" / symbol / yyyymmdd
    chart_dir.mkdir(parents=True, exist_ok=True)
    review_dir = ROOT / "reviews" / symbol
    review_dir.mkdir(parents=True, exist_ok=True)

    t_total = time.perf_counter()

    # 1. Load + render
    t0 = time.perf_counter()
    df_1d = normalize(load_ohlcv("crypto", symbol, "1d"))
    t_load = time.perf_counter() - t0

    # TF 세트 결정: 1M 24봉+ 가능하면 추가, 1W 충분하면 1W 추가, 항상 1D
    df_w = resample(df_1d, "W-MON")
    df_m = resample(df_1d, "ME")
    tfs = []
    if len(df_m) >= 24:  # 2년+ monthly
        tfs.append("1m")
    if len(df_w) >= 26:  # 6개월+ weekly
        tfs.append("1w")
    tfs.append("1d")
    print(f"  TF 세트: {tfs}")

    paths = {}
    for tf in tfs:
        t0 = time.perf_counter()
        df_full = {"1d": df_1d, "1w": df_w, "1m": df_m}[tf]
        out_p = chart_dir / f"{symbol}_{tf}.png"
        n, span = render(df_full, symbol, tf.upper(), out_p)
        dt = time.perf_counter() - t0
        paths[tf] = str(out_p.relative_to(ROOT)).replace("\\", "/")
        print(f"  {tf}: {n} bars  ({span})  render={dt:.2f}s")

    # 2. Prepare meta (no judgment yet — Claude does that next)
    meta = {
        "symbol": symbol,
        "reviewed_at": now_kst.isoformat(),
        "data_until": df_1d.index[-1].isoformat(),
        "chart_paths": paths,
        "chart_dir_abs": str(chart_dir.resolve()),
    }
    meta_path = chart_dir / "_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    total = time.perf_counter() - t_total
    print(f"\n[{symbol}] total={total:.2f}s  load={t_load:.2f}s")
    print(f"\ncharts: {chart_dir}")
    print(f"  1W: {paths['1w']}")
    print(f"  1D: {paths['1d']}")

if __name__ == "__main__":
    main()
