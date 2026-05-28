"""주봉 추세 게이트 — close > MA20w AND slope_4w(MA20w) >= 0.

strategy_discussion.md §7.1 의 공통 universe filter.

- 룩어헤드 회피: 미완성 주봉 제외 (use_completed_only=True 기본)
- 자산 무관 helper. 입력은 weekly DataFrame (close 컬럼 필요)
- 캐시/스킴은 호출 측에서 결정 (이 모듈은 게이트 로직만)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


# Bitget tokenized stock perpetuals (티커는 그대로 USDT 페어로 상장).
# 신규 발견 시 여기에 추가.
STOCK_TOKEN_BASES = {
    "AAPL", "AMD", "AMZN", "APP", "ARM", "ASML", "AVGO", "BA", "BABA",
    "COIN", "COST", "CRCL", "CSCO", "CVX", "DELL", "DIS", "ESPORTS",
    "GE", "GOOG", "GOOGL", "HOOD", "INTC", "JD", "JPM", "LLY", "MCD",
    "META", "MRVL", "MSFT", "MSTR", "MU", "NFLX", "NIO", "NKE", "NVDA",
    "ORCL", "OXY", "PANW", "PLTR", "PYPL", "QCOM", "QQQ", "RKLB", "ROKU",
    "SBUX", "SHOP", "SMCI", "SOFI", "SPY", "SQ", "TSLA", "TSM", "UNH",
    "UPS", "V", "WMT", "XOM",
}


def is_stock_token(symbol: str) -> bool:
    """USDT 페어 심볼이 토큰화된 주식인지 판정."""
    if not symbol.endswith("USDT"):
        return False
    return symbol[:-4] in STOCK_TOKEN_BASES


@dataclass
class GateResult:
    symbol: str
    pass_gate: bool
    bar_dt: Optional[pd.Timestamp]
    close: Optional[float]
    ma20w: Optional[float]
    slope_4w: Optional[float]
    n_weeks: int
    reason: str


def evaluate_weekly_gate(
    df: pd.DataFrame,
    symbol: str,
    ma_window: int = 20,
    slope_window: int = 4,
    use_completed_only: bool = True,
    close_col: str = "close",
    dt_col: Optional[str] = "dt",
) -> GateResult:
    """주봉 DataFrame 한 종목 → 게이트 결과.

    Args:
        df: weekly OHLCV. close_col 필수.
        symbol: 표시용
        use_completed_only: True면 마지막 미완성 주봉 제외 (마지막 행 drop)
    """
    n = len(df)
    if n == 0:
        return GateResult(symbol, False, None, None, None, None, 0, "empty")

    work = df.iloc[:-1].copy() if use_completed_only and n >= 1 else df.copy()
    if len(work) < ma_window + slope_window:
        return GateResult(symbol, False, None, None, None, None, len(work),
                          f"insufficient (<{ma_window + slope_window}w)")

    ma = work[close_col].rolling(ma_window, min_periods=ma_window).mean()
    ma_prev = ma.shift(slope_window)
    slope = ma / ma_prev - 1.0

    last_close = float(work[close_col].iloc[-1])
    last_ma = float(ma.iloc[-1]) if not np.isnan(ma.iloc[-1]) else None
    last_slope = float(slope.iloc[-1]) if not np.isnan(slope.iloc[-1]) else None
    last_dt = pd.to_datetime(work[dt_col].iloc[-1]) if dt_col and dt_col in work.columns else None

    if last_ma is None or last_slope is None:
        return GateResult(symbol, False, last_dt, last_close, last_ma, last_slope,
                          len(work), "ma/slope NaN")

    cond_close = last_close > last_ma
    cond_slope = last_slope >= 0.0
    if cond_close and cond_slope:
        reason = "pass"
    elif not cond_close and not cond_slope:
        reason = "below MA20 + slope<0"
    elif not cond_close:
        reason = "below MA20"
    else:
        reason = "slope<0"

    return GateResult(symbol, cond_close and cond_slope, last_dt, last_close,
                      last_ma, last_slope, len(work), reason)


def screen_crypto(
    symbols: Optional[list[str]] = None,
    ma_window: int = 20,
    slope_window: int = 4,
    use_completed_only: bool = True,
    exclude_stocks: bool = False,
    exclude_stables: bool = False,
) -> pd.DataFrame:
    """crypto 전체 (또는 지정 심볼) 스크리닝 → DataFrame.

    캐시: data/cache/crypto/1d → 1w 리샘플 (data.resample.load 경유)
    """
    from data.resample import load as load_crypto
    from pathlib import Path

    if symbols is None:
        cache_dir = Path("data/cache/crypto/1d")
        symbols = sorted([p.stem for p in cache_dir.glob("*.parquet")])

    if exclude_stocks:
        symbols = [s for s in symbols if not is_stock_token(s)]
    if exclude_stables:
        cls_path = Path("data/cache/crypto/classification.parquet")
        if cls_path.exists():
            cls = pd.read_parquet(cls_path)
            stables = set(cls.loc[cls["tier_final"] == "stable", "symbol"])
            symbols = [s for s in symbols if s not in stables]

    rows = []
    for sym in symbols:
        try:
            wk = load_crypto(sym, "1w")
            if wk.empty:
                rows.append(GateResult(sym, False, None, None, None, None, 0, "empty"))
                continue
            wk = wk.copy()
            wk["dt"] = pd.to_datetime(wk["timestamp"], unit="ms")
            res = evaluate_weekly_gate(wk, sym, ma_window, slope_window,
                                       use_completed_only, "close", "dt")
            rows.append(res)
        except Exception as e:
            rows.append(GateResult(sym, False, None, None, None, None, 0, f"error: {e}"))

    df = pd.DataFrame([r.__dict__ for r in rows])
    return df


def main():
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    import argparse

    ap = argparse.ArgumentParser(description="주봉 MA20 게이트 스크리닝 (crypto)")
    ap.add_argument("--symbols", nargs="*", help="지정 심볼 (생략 시 전체 캐시)")
    ap.add_argument("--ma", type=int, default=20)
    ap.add_argument("--slope-window", type=int, default=4)
    ap.add_argument("--include-incomplete", action="store_true",
                    help="현재 미완성 주봉도 포함 (기본은 직전 완성 주봉 기준)")
    ap.add_argument("--out", type=str, default=None, help="CSV 저장 경로 (옵션)")
    ap.add_argument("--show-fails", action="store_true", help="실패 사유까지 출력")
    ap.add_argument("--exclude-stocks", action="store_true", help="Bitget 토큰화 주식 제외")
    ap.add_argument("--exclude-stables", action="store_true", help="classification.tier_final==stable 제외")
    args = ap.parse_args()

    df = screen_crypto(
        symbols=args.symbols,
        ma_window=args.ma,
        slope_window=args.slope_window,
        use_completed_only=not args.include_incomplete,
        exclude_stocks=args.exclude_stocks,
        exclude_stables=args.exclude_stables,
    )

    n_total = len(df)
    n_pass = int(df["pass_gate"].sum())
    print(f"\n=== 주봉 MA20 게이트 (close>MA20 AND slope_4w>=0) ===")
    print(f"기준봉: {'직전 완성 주봉' if not args.include_incomplete else '최신(미완성 포함)'}")
    if df["bar_dt"].notna().any():
        latest_dt = df.loc[df["pass_gate"], "bar_dt"].max() if n_pass else df["bar_dt"].max()
        print(f"기준 주봉 라벨 (passed 중 최신): {latest_dt}")
    print(f"전체 {n_total} 종목 중 {n_pass} 통과 ({n_pass/n_total*100:.1f}%)\n")

    passed = df[df["pass_gate"]].sort_values("slope_4w", ascending=False).reset_index(drop=True)
    passed_view = passed[["symbol", "bar_dt", "close", "ma20w", "slope_4w"]].copy()
    passed_view["slope_4w"] = (passed_view["slope_4w"] * 100).round(2)
    passed_view["close_vs_ma"] = ((passed["close"] / passed["ma20w"] - 1) * 100).round(2)
    print(passed_view.to_string(index=False))

    if args.show_fails:
        fails = df[~df["pass_gate"]]
        print(f"\n--- 실패 사유 분포 ---")
        print(fails["reason"].value_counts().to_string())

    if args.out:
        from pathlib import Path
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.out, index=False)
        print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
