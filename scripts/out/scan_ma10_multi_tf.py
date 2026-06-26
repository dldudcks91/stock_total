"""TF별 MA10 위치 + ATH drawdown 스캔.

대상: 직전 게이트 (close >= MA20d AND close >= MA10w) 통과 종목.
출력: 1h/4h/1d/1w 각 TF 에서 close vs MA10 gap%, ATH 대비 drawdown%.

라이브 ticker (lastPr) 로 모든 TF 마지막 봉 close 를 덮어써서 현재 시각 반영.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from data.resample import load
from scripts.out.scan_ma10w_uptrend_live import (
    fetch_live_tickers,
    patch_with_live,
    resample_to_weekly,
)

CACHE_1D = ROOT / "data" / "cache" / "crypto" / "1d"
CACHE_1H = ROOT / "data" / "cache" / "crypto" / "1h"


# 토큰화 주식 식별 — 알려진 ticker 리스트 (Bitget이 perp 상장한 미 주식/ETF)
EQUITY_TICKERS = {
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    "AVGO", "ASML", "ORCL", "INTC", "AMD", "MRVL", "TSM", "RDDT", "LLY",
    "UNH", "GE", "BABA", "HOOD", "COIN", "SPY", "QQQ", "EWJ", "AAOI",
    "APLD", "APP", "AXTI", "ARQQ", "ASTS", "AVAV", "AVNT", "BARD",
    "MU", "OXY", "COPPER", "ANTHROPIC", "LIGHT", "CLO", "NOM", "SAGA",
    "ACHR", "ACU", "ARM", "MAGMA", "IDOL", "VVV", "DEXE",
    "ALCH", "AAOI", "EPIC", "BEAT",
}


def tag_class(sym: str) -> str:
    base = sym.replace("USDT", "")
    if base in EQUITY_TICKERS:
        return "equity"
    return "crypto"


def tf_ma10_gap(sym: str, last_pr: float | None, tf: str) -> tuple[float, float] | None:
    """주어진 TF 에서 (close, gap_pct) 반환. last_pr 있으면 마지막 close 덮어씀."""
    try:
        df = load(sym, tf)
    except Exception:
        return None
    if df is None or len(df) < 11:
        return None
    df = df.copy()
    if last_pr is not None:
        df.iloc[-1, df.columns.get_loc("close")] = last_pr
    df["ma10"] = df["close"].rolling(10).mean()
    c = df["close"].iloc[-1]
    m = df["ma10"].iloc[-1]
    if pd.isna(m) or m <= 0:
        return None
    return c, (c / m - 1) * 100


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("[1/4] fetching live tickers ...")
    tickers = fetch_live_tickers()
    print(f"      got {len(tickers)} symbols live")

    # [2/4] 게이트 통과 종목 추출 (close>=MA20d AND close>=MA10w, live patched)
    print("[2/4] selecting gate-pass universe ...")
    passers = []
    for p in sorted(CACHE_1D.glob("*.parquet")):
        sym = p.stem
        try:
            df_1d = pd.read_parquet(p)
        except Exception:
            continue
        if len(df_1d) < 80:
            continue
        tick = tickers.get(sym)
        if tick is not None:
            df_1d = patch_with_live(df_1d, tick)
        df_1d["ma20d"] = df_1d["close"].rolling(20).mean()
        c_d = df_1d["close"].iloc[-1]
        m20 = df_1d["ma20d"].iloc[-1]
        if pd.isna(m20) or m20 <= 0:
            continue
        df_1w = resample_to_weekly(df_1d)
        if len(df_1w) < 11:
            continue
        df_1w["ma10w"] = df_1w["close"].rolling(10).mean()
        c_w = df_1w["close"].iloc[-1]
        m10w = df_1w["ma10w"].iloc[-1]
        if pd.isna(m10w) or m10w <= 0:
            continue
        if c_d >= m20 and c_w >= m10w:
            ath = df_1d["high"].max()
            passers.append((sym, c_d, ath))

    print(f"      {len(passers)} gate-pass symbols")

    # [3/4] 4 TF MA10 + ATH dd 계산
    print("[3/4] computing 4-TF MA10 + ATH dd ...")
    rows = []
    for sym, c_d, ath in passers:
        tick = tickers.get(sym)
        last_pr = float(tick["lastPr"]) if tick else None
        row = {"symbol": sym, "type": tag_class(sym), "close": last_pr or c_d}

        for tf in ("1h", "4h", "1d", "1w"):
            r = tf_ma10_gap(sym, last_pr, tf)
            if r is None:
                row[f"{tf}_gap"] = None
            else:
                row[f"{tf}_gap"] = r[1]

        # ATH dd: 라이브 close vs 1d 전체 high 최대
        c = last_pr if last_pr is not None else c_d
        ath_dd = (c / ath - 1) * 100  # 음수 = ATH 아래
        row["ath_dd_pct"] = ath_dd
        row["ath"] = ath

        # 4주 거래대금 (활성도 정렬용)
        try:
            df_1d = pd.read_parquet(CACHE_1D / f"{sym}.parquet")
            if tick is not None:
                df_1d = patch_with_live(df_1d, tick)
            df_1w = resample_to_weekly(df_1d)
            n = len(df_1w)
            start = max(0, n - 4)
            row["amt_4w_M"] = df_1w["amount"].iloc[start:n].sum() / 1e6
        except Exception:
            row["amt_4w_M"] = 0.0
        rows.append(row)

    df = pd.DataFrame(rows)
    print(f"[4/4] {len(df)} symbols\n")

    pd.set_option("display.max_rows", 300)
    pd.set_option("display.float_format", lambda x: f"{x:.2f}")

    # 순수 코인만 / 거래대금 ≥ 10M / 1h_gap 내림차순
    crypto = df[df["type"] == "crypto"].copy()
    crypto_active = crypto[crypto["amt_4w_M"] >= 10.0].sort_values(
        "amt_4w_M", ascending=False
    )
    cols = ["symbol", "close", "1h_gap", "4h_gap", "1d_gap", "1w_gap",
            "ath", "ath_dd_pct", "amt_4w_M"]
    print(f"=== 순수 코인 (활성, amt_4w >= 10M USDT): {len(crypto_active)} ===")
    print(crypto_active[cols].to_string(index=False))

    equity = df[df["type"] == "equity"].copy()
    equity_active = equity[equity["amt_4w_M"] >= 10.0].sort_values(
        "amt_4w_M", ascending=False
    )
    print(f"\n=== 토큰화 주식 (활성, amt_4w >= 10M USDT): {len(equity_active)} ===")
    print(equity_active[cols].to_string(index=False))


if __name__ == "__main__":
    main()
