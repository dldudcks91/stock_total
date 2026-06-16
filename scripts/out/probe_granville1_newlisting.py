"""신규 상장 종목만 — 일봉 1d_MA20 + N=10 기준 그랜빌 1법칙 후보.

신규 상장 정의: 일봉 봉수 < 250 (대략 1년)

기존 룰 1~5 + 갭 필터는 25%로 완화 (신규 상장은 변동성 큼).
"""
import sys
from pathlib import Path
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from typing import Optional
import numpy as np
import pandas as pd

from scripts._common.mtf_loader import load_normalized_daily

ROOT = Path(".").resolve()
OUT = ROOT / "scripts" / "out"

NEW_MAX = 250         # 신규 상장 = 일봉 < 250봉
N_WIN = 10
MA_LEN = 20
A_MIN = 0.10
R2_MIN = 0.85
VERTEX_LO, VERTEX_HI = 0.30, 0.85
PX_GAP_MAX = 25.0     # 신규 상장은 변동성 크므로 25%로 완화


def fit_quadratic(y: np.ndarray) -> dict:
    n = len(y)
    x = np.arange(n, dtype=float)
    a, b, c = np.polyfit(x, y, 2)
    y_pred = a * x * x + b * x + c
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    vertex_x = -b / (2 * a) if abs(a) > 1e-15 else float("nan")
    y_mean = float(y.mean())
    return {
        "a_pct": float(a / y_mean * 100) if y_mean > 0 else float("nan"),
        "b_pct": float(b / y_mean * 100) if y_mean > 0 else float("nan"),
        "vertex_pos": float(vertex_x / (n - 1)) if not np.isnan(vertex_x) else float("nan"),
        "r2": float(r2),
    }


def evaluate(asset: str) -> pd.DataFrame:
    if asset == "kr":
        cache_dir = ROOT / "data" / "cache" / "kr"
        files = sorted(cache_dir.glob("*.parquet"))
        symbols = [p.stem for p in files if len(p.stem) == 6 and p.stem.isdigit()]
    elif asset == "us":
        cache_dir = ROOT / "data" / "cache" / "us"
        symbols = sorted(p.stem for p in cache_dir.glob("*.parquet"))
    else:  # crypto
        cache_dir = ROOT / "data" / "cache" / "crypto" / "1d"
        symbols = sorted(p.stem for p in cache_dir.glob("*.parquet"))

    rows = []
    for sym in symbols:
        try:
            df = load_normalized_daily(asset, sym) if asset != "crypto" else None
            if df is None:
                df = pd.read_parquet(cache_dir / f"{sym}.parquet")
                df = df.copy()
                df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                df = df.set_index("dt").sort_index()
                df = df[["open", "high", "low", "close", "volume"]]
        except Exception:
            continue
        n_rows = len(df)
        if n_rows < MA_LEN + N_WIN:
            continue
        if n_rows >= NEW_MAX:
            continue   # 신규 상장만
        df = df.copy()
        df["MA"] = df["close"].rolling(MA_LEN).mean()
        ma = df["MA"].values[-N_WIN:]
        if np.isnan(ma).any():
            continue
        last_close = float(df["close"].iloc[-1])
        last_ma = float(df["MA"].iloc[-1])
        fit = fit_quadratic(ma)
        ma_slope_3 = (ma[-1] / ma[-3] - 1) * 100
        px_gap = (last_close / last_ma - 1) * 100

        if fit["r2"] < R2_MIN:
            verdict = "low_r2"
        elif fit["a_pct"] < A_MIN:
            verdict = "low_a"
        elif not (VERTEX_LO <= fit["vertex_pos"] <= VERTEX_HI):
            verdict = "vertex_out"
        elif ma[-1] <= ma[-3]:
            verdict = "ma_not_rising"
        else:
            verdict = "pass"

        rows.append({
            "asset": asset, "symbol": sym,
            "first_date": str(df.index[0].date()),
            "last_date": str(df.index[-1].date()),
            "n_days": n_rows,
            "close": last_close, "ma": last_ma, "px_vs_ma_pct": px_gap,
            "ma_slope_last3_pct": ma_slope_3,
            "verdict": verdict, **fit,
        })
    return pd.DataFrame(rows)


def main():
    # 종목명 매핑
    kr = pd.read_csv('data/cache/kr/_names.csv', dtype={'Code': str})
    kd = pd.read_csv('data/cache/kr/_names_kosdaq.csv', dtype={'Code': str})
    name_map = {**dict(zip(kr['Code'], kr['Name'])), **dict(zip(kd['Code'], kd['Name']))}

    all_dfs = []
    for asset in ["kr", "us", "crypto"]:
        df = evaluate(asset)
        if df.empty:
            print(f"[{asset}] no new listings to evaluate"); continue
        n_eval = len(df)
        passed = df[df["verdict"] == "pass"]
        clean = passed[passed["px_vs_ma_pct"].abs() <= PX_GAP_MAX]
        print(f"[{asset}] 신규상장 평가: {n_eval}, pass: {len(passed)}, +gap≤{PX_GAP_MAX}%: {len(clean)}")
        all_dfs.append(df)

    if not all_dfs:
        print("no rows"); return
    full = pd.concat(all_dfs, ignore_index=True)
    full.to_csv(OUT / "_probe_granville1_newlisting.csv", index=False)

    # 종목명 매핑
    full["name"] = full.apply(
        lambda r: name_map.get(r["symbol"], "") if r["asset"] == "kr" else "", axis=1
    )

    # 자산별 pass 표
    for asset, label in [("kr", "KR"), ("us", "US"), ("crypto", "CRYPTO")]:
        sub = full[(full["asset"] == asset) & (full["verdict"] == "pass") &
                   (full["px_vs_ma_pct"].abs() <= PX_GAP_MAX)].copy()
        sub = sub.sort_values("a_pct", ascending=False)
        print(f"\n========= {label} 신규상장 1법칙 후보 (n={len(sub)}, gap≤{PX_GAP_MAX}%) =========")
        if sub.empty:
            print("(none)"); continue
        cols = ["symbol"]
        if asset == "kr": cols.append("name")
        cols += ["first_date", "n_days", "close", "ma", "px_vs_ma_pct",
                 "a_pct", "vertex_pos", "ma_slope_last3_pct", "r2"]
        print(sub.head(30)[cols].to_string(index=False, float_format=lambda v: f"{v:+.4f}"))

    # 전체 통계
    print("\n========= 신규 상장 전체 verdict 분포 =========")
    print(full.groupby(["asset", "verdict"]).size().unstack(fill_value=0).to_string())

    print(f"\nsaved: {OUT / '_probe_granville1_newlisting.csv'}")


if __name__ == "__main__":
    main()
