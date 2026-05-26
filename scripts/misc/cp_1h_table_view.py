"""cp_1h_3d.parquet 결과를 행=1시간 단위 압축 표로 재가공.

각 1시간 행마다: 종목수, 상위 N개 종목 (score 순), avg next-ret.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

TOP_N = 5  # 행마다 상위 N 종목만
SRC = Path("scripts/out/cp_1h_3d.parquet")

df = pd.read_parquet(SRC)
df["utc"] = df["ts"] - pd.Timedelta(hours=9)
df["utc_str"] = df["utc"].dt.strftime("%m-%d %H:%M")

print("=" * 165)
print(f"  1H 그리드 시그널 표 (cascading_pullback score >= 120, 최근 72h, 행=1시간)")
print(f"  상위 {TOP_N} 종목 / 시간 (전체 종목수와 avg next-ret 함께)")
print("=" * 165)

header = (f"{'UTC 시각':12s} {'n':>4s} | "
          f"{'avg_1h':>7s} {'avg_4h':>7s} {'avg_24h':>8s} | "
          f"{'TOP 5 (symbol[score] - next 24h)':<120s}")
print(header)
print("-" * 165)

# 시간별 그룹화
for utc_ts, grp in df.groupby("utc"):
    top = grp.nlargest(TOP_N, "score")
    avg_1h = grp.ret_1h.mean()
    avg_4h = grp.ret_4h.mean()
    avg_24h_vals = grp.ret_24h.dropna()
    avg_24h = avg_24h_vals.mean() if len(avg_24h_vals) > 0 else float("nan")

    parts = []
    for _, r in top.iterrows():
        r24 = f"{r.ret_24h:+.1%}" if not pd.isna(r.ret_24h) else "n/a"
        # 종목명에서 USDT 제거
        sym_short = r.symbol.replace("USDT", "")
        parts.append(f"{sym_short}({r.score:.0f},{r.pull_ma}/{r24})")

    utc_str = utc_ts.strftime("%m-%d %H:%M")
    a24_str = f"{avg_24h:+7.2%}" if not pd.isna(avg_24h) else "    n/a"
    print(f"{utc_str:12s} {len(grp):>4d} | "
          f"{avg_1h:>+7.2%} {avg_4h:>+7.2%} {a24_str:>8s} | "
          f"{' '.join(parts)}")

print("-" * 165)
# 종합
valid = df.dropna(subset=["ret_24h"])
print(f"\n전체 시그널: {len(df):,}  (24h 측정가능: {len(valid):,})")
print(f"평균 next ret  1h: {df.ret_1h.mean():+.3%}  /  4h: {df.ret_4h.mean():+.3%}  /  24h: {valid.ret_24h.mean():+.3%}")
print(f"24h 승률 (>0): {(valid.ret_24h > 0).mean():.1%}")
print(f"24h 분포 — q25: {valid.ret_24h.quantile(0.25):+.2%}  median: {valid.ret_24h.median():+.2%}  "
      f"q75: {valid.ret_24h.quantile(0.75):+.2%}")

# 최고 next-24h 시그널 TOP 15
print("\n" + "=" * 165)
print("  Next-24h 가장 좋은 시그널 TOP 15")
print("=" * 165)
print(valid.nlargest(15, "ret_24h")[
    ["utc_str", "symbol", "score", "tier", "imp_tf", "pull_ma", "closest_atr", "react_bull",
     "ret_1h", "ret_4h", "ret_24h"]
].to_string(index=False, formatters={
    "score": "{:.1f}".format,
    "closest_atr": "{:.2f}".format,
    "ret_1h": "{:+.2%}".format,
    "ret_4h": "{:+.2%}".format,
    "ret_24h": "{:+.2%}".format,
}))

# 최악 next-24h
print("\n" + "=" * 165)
print("  Next-24h 가장 나쁜 시그널 TOP 15")
print("=" * 165)
print(valid.nsmallest(15, "ret_24h")[
    ["utc_str", "symbol", "score", "tier", "imp_tf", "pull_ma", "closest_atr", "react_bull",
     "ret_1h", "ret_4h", "ret_24h"]
].to_string(index=False, formatters={
    "score": "{:.1f}".format,
    "closest_atr": "{:.2f}".format,
    "ret_1h": "{:+.2%}".format,
    "ret_4h": "{:+.2%}".format,
    "ret_24h": "{:+.2%}".format,
}))
