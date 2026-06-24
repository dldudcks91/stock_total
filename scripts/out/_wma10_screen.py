"""코인 weekly MA10 기울기 양수 + 현재가가 wMA10 에 가까운 순 스크리닝 (일회성)."""
import sys, warnings
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
from data.resample import load
from scripts.crypto._common.mtf_recs import BLACKLIST

CACHE_1D = ROOT / "data" / "cache" / "crypto" / "1d"
syms = sorted(p.stem for p in CACHE_1D.glob("*.parquet") if p.stem not in BLACKLIST)

rows = []
for s in syms:
    try:
        w = load(s, "1w")
        d = load(s, "1d")
    except Exception:
        continue
    if w is None or len(w) < 12:
        continue
    w = w.sort_index()
    ma10 = w["close"].rolling(10).mean()
    if ma10.isna().iloc[-1] or ma10.isna().iloc[-2]:
        continue
    slope = ma10.iloc[-1] - ma10.iloc[-2]
    if slope <= 0:
        continue  # 기울기 양수만
    close = float(w["close"].iloc[-1])
    wma10 = float(ma10.iloc[-1])
    dist = (close - wma10) / wma10 * 100.0
    slope_pct = slope / float(ma10.iloc[-2]) * 100.0
    amt = float(d.sort_index()["amount"].iloc[-30:].mean()) if "amount" in d.columns else np.nan
    rows.append((s, close, wma10, dist, slope_pct, amt))

df = pd.DataFrame(rows, columns=["sym", "close", "wMA10", "dist%", "wMA10_slope%", "avg_amt_30d_USDT"])
df = df[df["avg_amt_30d_USDT"] > 1e6]          # 최소 유동성 (일평균 거래대금 > 100만 USDT)
df["abs_dist"] = df["dist%"].abs()
df = df.sort_values("abs_dist").drop(columns="abs_dist").reset_index(drop=True)

pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 120)
print(f"# weekly MA10 기울기 양수 & 유동성>100만USDT: {len(df)}개 (현재가-wMA10 근접순)\n")
fmt = df.copy()
fmt["close"] = fmt["close"].map(lambda x: f"{x:,.4g}")
fmt["wMA10"] = fmt["wMA10"].map(lambda x: f"{x:,.4g}")
fmt["dist%"] = fmt["dist%"].map(lambda x: f"{x:+.2f}")
fmt["wMA10_slope%"] = fmt["wMA10_slope%"].map(lambda x: f"{x:+.2f}")
fmt["avg_amt_30d_USDT"] = fmt["avg_amt_30d_USDT"].map(lambda x: f"{x/1e6:,.1f}M")
print(fmt.to_string())
