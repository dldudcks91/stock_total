"""NIL/ONDO/FIDA 에 대해 최근 10일 cascading_pullback 상태 추적."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
from research.visual_review.facts import _normalize
from backtest.strategies import cascading_pullback as cp

SYMS = ["NILUSDT", "ONDOUSDT", "FIDAUSDT"]
N_DAYS = 12  # 좀 더 길게

for sym in SYMS:
    df_1h = _normalize(pd.read_parquet(f"data/cache/crypto/1h/{sym}.parquet"))
    df_1d = _normalize(pd.read_parquet(f"data/cache/crypto/1d/{sym}.parquet"))

    btc = _normalize(pd.read_parquet("data/cache/crypto/1d/BTCUSDT.parquet"))
    dates = list(btc.index[-N_DAYS:])

    print(f"\n=== {sym} ===")
    print(f"{'UTC date':12s} {'close':>10s} {'ret_day':>9s} | "
          f"{'tier':>4s} {'imp_tf':>6s} {'pull_ma':>8s} {'closest_atr':>11s} {'react':>5s} {'score':>7s} | "
          f"{'1h_ago':>6s} {'4h_ago':>6s} {'1d_ago':>6s}")
    print("-" * 130)

    for d_ts in dates:
        df_1h_hist = df_1h[df_1h.index < d_ts]
        df_1d_hist = df_1d[df_1d.index < d_ts]
        if len(df_1d_hist) < 60 or len(df_1h_hist) < 200:
            continue
        utc_date = (d_ts - pd.Timedelta(hours=9)).date()

        # 실제 return
        df_d = df_1d[df_1d.index == d_ts]
        close_start = float(df_1d_hist["Close"].iloc[-1])
        close_end = float(df_d["Close"].iloc[0]) if len(df_d) > 0 else None
        ret = (close_end / close_start - 1) if close_end and close_start > 0 else float("nan")

        res = cp.compute_cascade(df_1h_hist, df_1d_hist)
        ca = res.get("pullback_closest_atr")
        ca_str = f"{ca:.2f}" if ca is not None else "    -"
        print(f"{str(utc_date):12s} {close_start:>10.5f} {ret:>+9.2%} | "
              f"{res.get('tier'):>4} {res.get('impulse_tf') or '-':>6s} "
              f"{res.get('pullback_ma') or '-':>8s} {ca_str:>11s} "
              f"{'Y' if res.get('react_bull') else '-':>5s} {res.get('score'):>7.1f} | "
              f"{str(res.get('impulse_1h_bars_ago') or '-'):>6s} "
              f"{str(res.get('impulse_4h_bars_ago') or '-'):>6s} "
              f"{str(res.get('impulse_1d_bars_ago') or '-'):>6s}")
