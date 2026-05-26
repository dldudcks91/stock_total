import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
from research.visual_review.facts import _normalize
from backtest.strategies import cascading_pullback as cp

for sym in ["NILUSDT", "ONDOUSDT", "FIDAUSDT", "BTCUSDT", "ETHUSDT"]:
    df_1h = _normalize(pd.read_parquet(f"data/cache/crypto/1h/{sym}.parquet"))
    df_1d = _normalize(pd.read_parquet(f"data/cache/crypto/1d/{sym}.parquet"))
    res = cp.compute_cascade(df_1h, df_1d)
    print(f"{sym}: tier={res.get('tier')} score={res.get('score'):.1f} imp_tf={res.get('impulse_tf')} "
          f"pull={res.get('pullback_ma')} dist_atr={res.get('pullback_closest_atr')} "
          f"bull={res.get('react_bull')} | 1h_ago={res.get('impulse_1h_bars_ago')} "
          f"4h_ago={res.get('impulse_4h_bars_ago')} 1d_ago={res.get('impulse_1d_bars_ago')} | "
          f"body_1h={res.get('impulse_1h_body')} body_4h={res.get('impulse_4h_body')} body_1d={res.get('impulse_1d_body')}")
