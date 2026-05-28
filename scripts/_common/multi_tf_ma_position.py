"""심볼 리스트에 대해 1D/4H/1H × MA10/MA20 의 close 대비 위치 % 계산.

용도: 주봉 게이트 통과 종목 등의 MTF 위치 스냅샷.
- 최신 봉(미완성 가능) 기준 — backtest 가 아닌 현재 상태 스냅샷
- 값은 (close / MA - 1) * 100  (양수 = MA 위, 음수 = MA 아래)
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


def position_vs_mas(symbol: str, intervals_mas: dict) -> dict:
    """{symbol: ..., 1D_MA10: %, 1D_MA20: %, 4H_MA10: %, ...} 한 행."""
    from data.resample import load as load_crypto
    row: dict = {"symbol": symbol}
    last_close = None
    for interval, ma_list in intervals_mas.items():
        df = load_crypto(symbol, interval)
        if df.empty:
            for ma in ma_list:
                row[f"{interval}_MA{ma}"] = np.nan
            continue
        close = df["close"]
        last_close = float(close.iloc[-1])
        for ma in ma_list:
            if len(close) < ma:
                row[f"{interval}_MA{ma}"] = np.nan
                continue
            ma_val = close.rolling(ma).mean().iloc[-1]
            if pd.isna(ma_val) or ma_val == 0:
                row[f"{interval}_MA{ma}"] = np.nan
            else:
                row[f"{interval}_MA{ma}"] = (last_close / ma_val - 1.0) * 100.0
    row["last_close"] = last_close
    return row


def build_table(symbols: Iterable[str]) -> pd.DataFrame:
    intervals_mas = {"1d": [10, 20], "4h": [10, 20], "1h": [10, 20]}
    rows = []
    for sym in symbols:
        try:
            rows.append(position_vs_mas(sym, intervals_mas))
        except Exception as e:
            rows.append({"symbol": sym, "error": str(e)})
    df = pd.DataFrame(rows)
    cols = ["symbol", "last_close",
            "1d_MA10", "1d_MA20", "4h_MA10", "4h_MA20", "1h_MA10", "1h_MA20"]
    cols = [c for c in cols if c in df.columns]
    return df[cols + [c for c in df.columns if c not in cols]]


def main():
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    import argparse
    ap = argparse.ArgumentParser(description="멀티 TF MA 위치 표")
    ap.add_argument("--symbols-file", type=str, help="symbol 컬럼 가진 CSV (예: weekly_gate 결과)")
    ap.add_argument("--filter-passed", action="store_true", help="symbols-file 의 pass_gate==True 만")
    ap.add_argument("--symbols", nargs="*", help="직접 심볼 지정")
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()

    if args.symbols:
        syms = args.symbols
    elif args.symbols_file:
        df_in = pd.read_csv(args.symbols_file)
        if args.filter_passed and "pass_gate" in df_in.columns:
            df_in = df_in[df_in["pass_gate"] == True]  # noqa: E712
        syms = df_in["symbol"].tolist()
    else:
        raise SystemExit("--symbols 또는 --symbols-file 필요")

    print(f"\n=== {len(syms)} 종목 MTF MA 위치 (단위: %) ===")
    print("값 = (close / MA - 1) × 100   |   양수: MA 위, 음수: MA 아래\n")

    table = build_table(syms)

    show = table.copy()
    for c in show.columns:
        if c.endswith("MA10") or c.endswith("MA20"):
            show[c] = show[c].round(2)
    show = show.sort_values("1d_MA20", ascending=False)
    print(show.to_string(index=False))

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(args.out, index=False)
        print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
