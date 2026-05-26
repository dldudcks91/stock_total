"""NIL/ONDO/FIDA: 1h 그리드 cascading_pullback 추적.

매 1h candle close 시점에:
  - tier / impulse_tf / pull_ma / score 계산 (룩어헤드 회피: index < ts)
  - next 1h return + next 24h return 측정

진입 시그널 (score >= 100) 시점만 추출해서 보여줌.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
from research.visual_review.facts import _normalize
from backtest.strategies import cascading_pullback as cp

SYMS = ["NILUSDT", "ONDOUSDT", "FIDAUSDT"]
HOURS = 240  # 최근 10일 = 240시간
SCORE_TH = 100.0  # 활성 시그널 임계 (50 대기, 100+ 풀백 자리)

for sym in SYMS:
    df_1h = _normalize(pd.read_parquet(f"data/cache/crypto/1h/{sym}.parquet"))
    df_1d = _normalize(pd.read_parquet(f"data/cache/crypto/1d/{sym}.parquet"))

    # 최근 HOURS 시간만 평가
    eval_ts_list = list(df_1h.index[-HOURS:])

    print(f"\n{'='*135}")
    print(f"=== {sym}  (1h 그리드 추적, score>={SCORE_TH:.0f} 만 표시)")
    print(f"{'='*135}")
    print(f"{'KST candle ts':19s} {'price':>10s} {'ret_1h':>7s} {'ret_24h':>8s} | "
          f"{'tier':>4s} {'imp':>4s} {'pull':>5s} {'atr':>5s} {'rct':>4s} {'score':>6s} | "
          f"{'imp1h':>5s} {'imp4h':>5s} {'imp1d':>5s}")
    print("-" * 135)

    last_signal_ts = None
    n_signals = 0
    for ts in eval_ts_list:
        df_1h_hist = df_1h[df_1h.index < ts]
        df_1d_hist = df_1d[df_1d.index < ts]
        if len(df_1h_hist) < 200 or len(df_1d_hist) < 60:
            continue
        if len(df_1h[df_1h.index == ts]) == 0:
            continue

        close_now = float(df_1h_hist["Close"].iloc[-1])
        close_1h_later = float(df_1h[df_1h.index == ts]["Close"].iloc[0])
        ret_1h = (close_1h_later / close_now - 1)

        # next 24h: ts +24h 후 close (있으면)
        fut_24 = df_1h[df_1h.index >= ts].head(24)
        if len(fut_24) >= 24:
            close_24h_later = float(fut_24["Close"].iloc[-1])
            ret_24h = (close_24h_later / close_now - 1)
        else:
            ret_24h = float("nan")

        res = cp.compute_cascade(df_1h_hist, df_1d_hist)
        score = res.get("score", 0.0)
        if score < SCORE_TH:
            continue

        # 같은 시그널이 1h마다 반복되니, 6시간 이상 간격으로 묶어서 표시
        if last_signal_ts is not None and (ts - last_signal_ts) < pd.Timedelta(hours=6):
            continue
        last_signal_ts = ts
        n_signals += 1

        ca = res.get("pullback_closest_atr")
        ca_str = f"{ca:.2f}" if ca is not None else "  -"
        ret24_str = f"{ret_24h:+7.2%}" if not pd.isna(ret_24h) else "    n/a"
        print(f"{ts.strftime('%Y-%m-%d %H:%M'):19s} {close_now:>10.5f} {ret_1h:>+7.2%} {ret24_str:>8s} | "
              f"{res.get('tier'):>4} {res.get('impulse_tf') or '-':>4s} "
              f"{res.get('pullback_ma') or '-':>5s} {ca_str:>5s} "
              f"{'Y' if res.get('react_bull') else '-':>4s} {score:>6.1f} | "
              f"{str(res.get('impulse_1h_bars_ago') or '-'):>5s} "
              f"{str(res.get('impulse_4h_bars_ago') or '-'):>5s} "
              f"{str(res.get('impulse_1d_bars_ago') or '-'):>5s}")
    print(f"\n  활성 시그널 (6h 묶음): {n_signals}건")
