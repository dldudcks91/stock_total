"""KR/US 주봉 시그널 — horizon 확장 (1~52주) peak/trough 분포 확인.

가설: KR/US는 사이클이 길어 8주 윈도우가 너무 짧을 수도. 26주(반년)/52주(1년)까지 확장하면
peak/trough mean이 의미 있게 커지는지 검증.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import ma_slope_turn_up  # noqa: E402
from scripts.quiet_bottom.count_slope_turn_signals import (  # noqa: E402
    load_crypto_weekly, load_stock_weekly, crypto_symbol_from_file,
    CRYPTO_DIR, CRYPTO_1H_DIR, KR_DIR, US_DIR, SINCE,
)
from scripts.quiet_bottom.forward_returns_top200 import (  # noqa: E402
    kr_top_universe, us_top_universe, crypto_top_universe,
)

OUT_DIR = ROOT / "scripts" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HORIZONS = [1, 2, 4, 8, 13, 26, 52]


def collect(asset: str, files: list[Path], loader, universe: set[str]) -> pd.DataFrame:
    rows = []
    for p in files:
        symbol = crypto_symbol_from_file(p) if asset == "crypto" else p.stem
        if symbol not in universe:
            continue
        try:
            df_w = loader(p)
            if df_w is None or df_w.empty or len(df_w) < 120:
                continue
            sig = ma_slope_turn_up.signal(df_w.reset_index(drop=True), {})
            sig.index = df_w.index
            entries = (sig.diff() == 1) & (df_w.index >= SINCE)
            close = df_w["close"].to_numpy()
            for pos in np.where(entries.to_numpy())[0]:
                ec = float(close[pos])
                row = {"asset": asset, "symbol": symbol,
                       "entry_dt": df_w.index[pos].date().isoformat()}
                # 각 horizon에서의 누적 수익률 (위치 pos+h 종가)
                for h in HORIZONS:
                    fp = pos + h
                    row[f"ret_{h}w"] = (close[fp] / ec - 1.0) * 100 if fp < len(close) else np.nan
                # peak/trough 누적 (1~h 사이 max/min)
                for win in [8, 13, 26, 52]:
                    end = min(pos + win, len(close) - 1)
                    if end > pos:
                        seg = close[pos+1:end+1] / ec - 1.0
                        row[f"peak_{win}w"] = float(seg.max()) * 100 if len(seg) else np.nan
                        row[f"trough_{win}w"] = float(seg.min()) * 100 if len(seg) else np.nan
                    else:
                        row[f"peak_{win}w"] = np.nan
                        row[f"trough_{win}w"] = np.nan
                rows.append(row)
        except Exception as e:
            print(f"  ! {symbol}: {e}", flush=True)
    return pd.DataFrame(rows)


def main():
    kr_uni = kr_top_universe()
    us_uni = us_top_universe()
    cr_uni = crypto_top_universe()

    kr_files = [p for p in sorted(KR_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    us_files = [p for p in sorted(US_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    cr_files = sorted(CRYPTO_1H_DIR.glob("*.parquet"))

    df_c = collect("crypto", cr_files, load_crypto_weekly, cr_uni)
    df_k = collect("kr", kr_files, load_stock_weekly, kr_uni)
    df_u = collect("us", us_files, load_stock_weekly, us_uni)
    all_df = pd.concat([df_c, df_k, df_u], ignore_index=True)
    print(f"crypto={len(df_c)}, kr={len(df_k)}, us={len(df_u)}")

    pd.set_option("display.float_format", "{:.1f}".format)
    pd.set_option("display.width", 140)

    # horizon별 통계
    print("\n=== Horizon별 단일 시점 수익률 (mean / median / win%) ===")
    print(f"{'asset':<8s} {'h':>4s} {'n':>4s} {'mean':>7s} {'median':>7s} {'win%':>6s}")
    for asset in ["crypto", "kr", "us"]:
        sub = all_df[all_df.asset==asset]
        for h in HORIZONS:
            s = sub[f"ret_{h}w"].dropna()
            if len(s) == 0: continue
            print(f"{asset:<8s} {h:>3d}w {len(s):>4d} {s.mean():>+7.1f} {s.median():>+7.1f} {(s>0).mean()*100:>5.1f}%")
        print()

    # peak/trough by window
    print("=== Peak / Trough 윈도우 확장 효과 (mean) ===")
    print(f"{'asset':<8s} {'win':>4s} {'n':>4s} {'peak_mean':>10s} {'peak_med':>10s} {'>+20%':>7s} {'>+50%':>7s} {'trough_mean':>12s} {'trough_med':>11s} {'<-20%':>7s}")
    for asset in ["crypto", "kr", "us"]:
        sub = all_df[all_df.asset==asset]
        for win in [8, 13, 26, 52]:
            pk = sub[f"peak_{win}w"].dropna()
            tr = sub[f"trough_{win}w"].dropna()
            if len(pk) == 0: continue
            print(f"{asset:<8s} {win:>3d}w {len(pk):>4d} "
                  f"{pk.mean():>+10.1f} {pk.median():>+10.1f} "
                  f"{(pk>20).mean()*100:>6.1f}% {(pk>50).mean()*100:>6.1f}% "
                  f"{tr.mean():>+12.1f} {tr.median():>+11.1f} {(tr<-20).mean()*100:>6.1f}%")
        print()

    # 결정적 비교: peak8 vs peak26 vs peak52
    print("=== Risk/Reward (peak_mean / |trough_mean|) ===")
    print(f"{'asset':<8s} {'8w':>6s} {'13w':>6s} {'26w':>6s} {'52w':>6s}")
    for asset in ["crypto", "kr", "us"]:
        sub = all_df[all_df.asset==asset]
        row = [asset]
        for win in [8, 13, 26, 52]:
            pk = sub[f"peak_{win}w"].dropna()
            tr = sub[f"trough_{win}w"].dropna()
            if len(pk) and abs(tr.mean()) > 0.01:
                row.append(f"{pk.mean()/abs(tr.mean()):.2f}")
            else:
                row.append("-")
        print(f"{row[0]:<8s} {row[1]:>6s} {row[2]:>6s} {row[3]:>6s} {row[4]:>6s}")

    all_df.to_csv(OUT_DIR / "forward_longh_top200.csv", index=False, encoding="utf-8-sig")
    print(f"\nsaved: {OUT_DIR / 'forward_longh_top200.csv'}")


if __name__ == "__main__":
    main()
