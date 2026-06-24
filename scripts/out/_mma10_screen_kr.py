"""KOSPI monthly MA10 기울기 양수 + 현재가가 mMA10 에 가까운 순 스크리닝 (일회성)."""
import sys, warnings
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
from research.collect import load_daily, to_monthly

CACHE_KR = ROOT / "data" / "cache" / "kr"

# 종목명 매핑
names = {}
for enc in ("utf-8-sig", "cp949", "utf-8"):
    try:
        l = pd.read_csv(CACHE_KR / "_listing.csv", dtype={"Symbol": str}, encoding=enc)
        names = dict(zip(l["Symbol"].astype(str).str.zfill(6), l["Name"]))
        break
    except Exception:
        continue

syms = sorted(p.stem for p in CACHE_KR.glob("*.parquet") if p.stem.isdigit())

rows = []
for s in syms:
    try:
        d = load_daily(s)
    except Exception:
        continue
    if d is None or len(d) < 260:   # 월봉 MA10 = 10개월 ≈ 210거래일 + 여유
        continue
    m = to_monthly(d)
    ma10 = m["Close"].rolling(10).mean()
    if len(ma10) < 11 or pd.isna(ma10.iloc[-1]) or pd.isna(ma10.iloc[-2]):
        continue
    slope = ma10.iloc[-1] - ma10.iloc[-2]
    if slope <= 0:
        continue  # 월봉 MA10 기울기 양수만
    close = float(m["Close"].iloc[-1])
    mma10 = float(ma10.iloc[-1])
    dist = (close - mma10) / mma10 * 100.0
    slope_pct = slope / float(ma10.iloc[-2]) * 100.0
    amt = float((d["Close"] * d["Volume"]).iloc[-60:].mean())  # 추정 일평균 거래대금(원)
    low_6m = float(d["Low"].iloc[-126:].replace(0, np.nan).min())  # 최근 6개월(≈126거래일) 저점
    if not (low_6m > 0):
        continue
    from_low = (close - low_6m) / low_6m * 100.0               # 저점 대비 상승률
    rows.append((s, names.get(s, ""), close, mma10, dist, slope_pct, low_6m, from_low, amt))

df = pd.DataFrame(rows, columns=["code", "name", "close", "mMA10", "dist%", "mMA10_slope%", "low6m", "from_low6m%", "avg_amt_60d"])
df = df[df["avg_amt_60d"] > 1e9]               # 최소 유동성: 일평균 거래대금 > 10억원
df["abs_dist"] = df["dist%"].abs()
df = df.sort_values("abs_dist").drop(columns="abs_dist").reset_index(drop=True)

pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 200)
pd.set_option("display.unicode.east_asian_width", True)
print(f"# KOSPI 월봉 MA10 기울기 양수 & 일평균거래대금>10억: {len(df)}개 (현재가-mMA10 근접순)\n")
fmt = df.copy()
fmt["close"] = fmt["close"].map(lambda x: f"{x:,.0f}")
fmt["mMA10"] = fmt["mMA10"].map(lambda x: f"{x:,.0f}")
fmt["dist%"] = fmt["dist%"].map(lambda x: f"{x:+.2f}")
fmt["mMA10_slope%"] = fmt["mMA10_slope%"].map(lambda x: f"{x:+.2f}")
fmt["low6m"] = fmt["low6m"].map(lambda x: f"{x:,.0f}")
fmt["from_low6m%"] = fmt["from_low6m%"].map(lambda x: f"+{x:.1f}")
fmt["avg_amt_60d"] = fmt["avg_amt_60d"].map(lambda x: f"{x/1e8:,.0f}억")
print(fmt.to_string())
