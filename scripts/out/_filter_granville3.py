"""ma_touch 통과 종목 중 그랜빌 3법칙 (MA 안 깨고 위에서 지지) 만 추출.

3법칙: 정배열 + slope+ + low가 MA20 위에 있으면서 MA20 근처 (|low - MA20| ≤ th)
2법칙: 정배열 + slope+ + low가 MA20 아래로 살짝 내려갔다 회복

핵심 차이는 `low >= ma20` 인지 여부.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

K_DIST = 0.2
N_WIN = 7

def evaluate_asset(asset: str, top: int = 30):
    cache_dir = Path(f"data/cache/{asset}")
    files = sorted(cache_dir.glob("*.parquet"))
    files = [f for f in files if not f.stem.startswith("_")]
    if asset == "kr":
        files = [f for f in files if f.stem.isdigit() and len(f.stem) == 6]

    rows = []
    for fp in files:
        try:
            df = pd.read_parquet(fp)
            df.columns = [c.lower() for c in df.columns]
            df = df.sort_index()
            if len(df) < 30:
                continue
            # 일봉 ma
            close = df["close"]
            ma10 = close.rolling(10).mean()
            ma20 = close.rolling(20).mean()
            range_7 = (df["high"] - df["low"]).rolling(N_WIN).mean()

            last = df.iloc[-1]
            last_close = float(last["close"])
            today_low = float(last["low"])
            today_high = float(last["high"])
            ma10_v = float(ma10.iloc[-1])
            ma20_v = float(ma20.iloc[-1])
            th = float(K_DIST * range_7.iloc[-1])

            # slope (10봉 전 대비)
            if len(ma10) >= 11:
                slope10 = (ma10.iloc[-1] / ma10.iloc[-3] - 1) * 100 if ma10.iloc[-3] > 0 else 0
                slope20 = (ma20.iloc[-1] / ma20.iloc[-3] - 1) * 100 if ma20.iloc[-3] > 0 else 0
            else:
                continue

            if any(np.isnan([ma10_v, ma20_v, th, slope10, slope20])):
                continue

            # 게이트
            gate_align = (ma10_v > ma20_v) and (last_close > ma20_v)
            gate_slope = (slope10 > 0) and (slope20 > 0)

            # 3법칙: low >= MA AND |low - MA| ≤ th
            dist10 = today_low - ma10_v
            dist20 = today_low - ma20_v
            # 3법칙 = MA20 안 깨고 지지
            granville3 = (
                gate_align and gate_slope and
                today_low >= ma20_v * 0.999 and  # 약간 여유
                abs(dist20) <= th
            )
            # 2법칙 = MA20 아래로 깬 자리
            granville2_only = (
                gate_align and gate_slope and
                today_low < ma20_v * 0.999 and
                abs(dist20) <= th
            )

            if granville3 or granville2_only:
                rows.append({
                    "symbol": fp.stem,
                    "close": last_close,
                    "today_low": today_low,
                    "ma10": ma10_v,
                    "ma20": ma20_v,
                    "low_vs_ma20_pct": (today_low / ma20_v - 1) * 100,
                    "th_pct": (th / ma20_v) * 100,
                    "slope_ma20_pct": slope20,
                    "kind": "3법칙(MA20 위지지)" if granville3 else "2법칙(MA20 아래cross)",
                })
        except Exception as e:
            continue

    df_out = pd.DataFrame(rows)
    if df_out.empty:
        print(f"[{asset}] 없음")
        return df_out

    granville3 = df_out[df_out["kind"].str.startswith("3")].copy()
    granville2 = df_out[df_out["kind"].str.startswith("2")].copy()

    print(f"\n========== {asset.upper()} ==========")
    print(f"  ma_touch 통과 (일봉): {len(df_out)}개")
    print(f"  └ 3법칙 (MA 안 깸):  {len(granville3)}개  ← 더 강한 자리")
    print(f"  └ 2법칙 (MA 깨고 회복): {len(granville2)}개")

    if asset == "kr":
        # 이름 매핑
        try:
            n1 = pd.read_csv("data/cache/kr/_names.csv", dtype={"Code": str})
            n2 = pd.read_csv("data/cache/kr/_names_kosdaq.csv", dtype={"Code": str})
            names = pd.concat([n1, n2]).drop_duplicates("Code").set_index("Code")["Name"].to_dict()
            granville3["name"] = granville3["symbol"].map(names)
            granville2["name"] = granville2["symbol"].map(names)
        except:
            pass

    print(f"\n=== {asset.upper()} 3법칙 상위 (slope_MA20 강한 순) ===")
    g3 = granville3.sort_values("slope_ma20_pct", ascending=False).head(top)
    if not g3.empty:
        cols_show = ["symbol", "name", "close", "today_low", "ma20", "low_vs_ma20_pct", "slope_ma20_pct"] if "name" in g3.columns else ["symbol", "close", "today_low", "ma20", "low_vs_ma20_pct", "slope_ma20_pct"]
        print(g3[cols_show].to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    return df_out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="all", choices=["kr", "us", "all"])
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    if args.asset == "all":
        for a in ["kr", "us"]:
            evaluate_asset(a, args.top)
    else:
        evaluate_asset(args.asset, args.top)

if __name__ == "__main__":
    main()
