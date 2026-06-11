"""ma_touch 추천 표 빌더 — `.claude/skills/recs` 가 호출하는 CLI.

`data/cache/{asset}/_ma_touch.parquet` 를 읽어 사용자 표 형식으로 stdout 출력.

표 컬럼:
  종목명 | 코드 | 시총 | 거래량 | 현재가
  | vs일봉MA10(%) | vs일봉MA20(%)
  | vs주봉MA10(%) | vs주봉MA20(%)
  | vs월봉MA10(%) | vs월봉MA20(%)
  | 통과TF | 큰흐름정합도

자산별 차이:
  KR : 이름 한글, 시총 조(KRW), 거래량 만주
  US : 이름 영문, 시총 십억 USD (B), 거래량 만주
  Crypto: 심볼 그대로, 시총 — (생략), 거래량 코인수 (USDT-M 1d Volume)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
_CACHE = _ROOT / "data" / "cache"


def _load_signals(asset: str) -> pd.DataFrame:
    p = _CACHE / asset / "_ma_touch.parquet"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p)


def _filter_passed(df: pd.DataFrame, tf: str, kind: str) -> pd.DataFrame:
    """tf={any|1D|1W|1M|1Q|1Y}, kind={full|partial|both}."""
    tf_list = ["1D", "1W", "1M", "1Q", "1Y"] if tf == "any" else [tf.upper()]
    kind_list = {"full": ["full"], "partial": ["partial"], "both": ["full", "partial"]}[kind]
    cols = [f"signal_ma_touch_{t}_{k}" for t in tf_list for k in kind_list]
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return df.iloc[0:0]
    mask = df[cols].fillna(False).any(axis=1)
    return df[mask].copy()


def _load_listing(asset: str) -> pd.DataFrame:
    """FDR 종목 listing (이름 + 시총). KR/US 만 의미 있음."""
    try:
        import FinanceDataReader as fdr
    except ImportError:
        return pd.DataFrame(columns=["symbol", "name", "marcap"])
    if asset == "kr":
        d = fdr.StockListing("KRX")[["Code", "Name", "Marcap"]].rename(
            columns={"Code": "symbol", "Name": "name", "Marcap": "marcap"}
        )
        return d
    if asset == "us":
        try:
            d = fdr.StockListing("NASDAQ")
        except Exception:
            return pd.DataFrame(columns=["symbol", "name", "marcap"])
        # FDR US listing 컬럼명이 다를 수 있어 케이스별 처리
        col_sym = next((c for c in ("Symbol", "symbol") if c in d.columns), None)
        col_name = next((c for c in ("Name", "name") if c in d.columns), None)
        col_mc = next((c for c in ("MarketCap", "Marcap", "marketCap") if c in d.columns), None)
        if not col_sym:
            return pd.DataFrame(columns=["symbol", "name", "marcap"])
        d2 = d[[col_sym] + ([col_name] if col_name else []) + ([col_mc] if col_mc else [])].copy()
        renames = {col_sym: "symbol"}
        if col_name:
            renames[col_name] = "name"
        if col_mc:
            renames[col_mc] = "marcap"
        d2 = d2.rename(columns=renames)
        if "name" not in d2.columns:
            d2["name"] = d2["symbol"]
        if "marcap" not in d2.columns:
            d2["marcap"] = None
        return d2[["symbol", "name", "marcap"]]
    return pd.DataFrame(columns=["symbol", "name", "marcap"])


def _attach_meta_and_volume(passed: pd.DataFrame, asset: str) -> pd.DataFrame:
    listing = _load_listing(asset)
    if not listing.empty:
        passed = passed.merge(listing, on="symbol", how="left")
    else:
        passed["name"] = passed["symbol"]
        passed["marcap"] = None

    # 거래량 (마지막 일봉)
    vols = []
    for sym in passed["symbol"]:
        try:
            if asset == "crypto":
                d = pd.read_parquet(_CACHE / "crypto" / "1d" / f"{sym}.parquet")
                vols.append(float(d["volume"].iloc[-1]))
            else:
                d = pd.read_parquet(_CACHE / asset / f"{sym}.parquet")
                vols.append(float(d["Volume"].iloc[-1]))
        except Exception:
            vols.append(None)
    passed["volume_today"] = vols
    return passed


def _format_table(passed: pd.DataFrame, asset: str, sort: str) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "종목명": passed.get("name", passed["symbol"]),
            "코드": passed["symbol"],
        }
    )
    # 시총 단위
    if asset == "kr":
        out["시총(조)"] = (passed["marcap"] / 1e12).round(2)
        out["거래량(만주)"] = (passed["volume_today"] / 1e4).round(1)
    elif asset == "us":
        out["시총(B$)"] = (pd.to_numeric(passed["marcap"], errors="coerce") / 1e9).round(2)
        out["거래량(만주)"] = (passed["volume_today"] / 1e4).round(1)
    else:  # crypto
        out["시총"] = "—"
        out["거래량(코인)"] = passed["volume_today"].round(1)

    out["현재가"] = passed["close_price"].round(2)
    for tf, label in [("1D", "일봉"), ("1W", "주봉"), ("1M", "월봉")]:
        out[f"vs{label}MA10(%)"] = passed[f"dist_to_ma10_{tf}_pct"].round(1)
        out[f"vs{label}MA20(%)"] = passed[f"dist_to_ma20_{tf}_pct"].round(1)
    out["통과TF"] = passed["signal_ma_touch_timeframes_passed"]
    out["큰흐름정합도"] = passed["count_angle_positive_ma20"].astype("Int64").astype(str) + "/5"

    # 정렬
    if sort == "marcap":
        mc_col = next((c for c in ("시총(조)", "시총(B$)") if c in out.columns), None)
        if mc_col is not None:
            out = out.sort_values(mc_col, ascending=False, na_position="last")
        else:
            out = out.sort_values("코드")
    elif sort == "ticker":
        out = out.sort_values("코드")
    elif sort == "tf":
        out = out.sort_values("통과TF")
    elif sort == "count_signal":
        out["_n"] = passed["count_signal_ma_touch_total"].values
        out = out.sort_values("_n", ascending=False).drop(columns="_n")
    return out.reset_index(drop=True)


def _print_section(asset: str, df: pd.DataFrame, top: Optional[int]) -> None:
    title = {"kr": "[KR / KOSPI]", "us": "[US / NASDAQ]", "crypto": "[Crypto / Bitget USDT-M]"}[asset]
    print(f"\n{title}  통과 종목 {len(df)}개")
    if len(df) == 0:
        print("  (해당 조건 통과 종목 없음)")
        return
    show = df if top is None else df.head(top)
    print(show.to_string(index=False))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="ma_touch 추천 표")
    ap.add_argument("--asset", default="kr", choices=["kr", "us", "crypto", "all"])
    ap.add_argument("--tf", default="any", choices=["any", "1D", "1W", "1M", "1Q", "1Y", "1d", "1w", "1m", "1q", "1y"])
    ap.add_argument("--kind", default="both", choices=["full", "partial", "both"])
    ap.add_argument("--sort", default="marcap", choices=["marcap", "ticker", "tf", "count_signal"])
    ap.add_argument("--top", type=int, default=None)
    args = ap.parse_args()

    assets = ["kr", "us", "crypto"] if args.asset == "all" else [args.asset]
    for a in assets:
        df = _load_signals(a)
        if df.empty:
            print(f"\n[{a.upper()}] _ma_touch.parquet 없음 — recommend 먼저 실행 필요.")
            continue
        passed = _filter_passed(df, args.tf, args.kind)
        if passed.empty:
            _print_section(a, passed, args.top)
            continue
        passed = _attach_meta_and_volume(passed, a)
        table = _format_table(passed, a, args.sort)
        _print_section(a, table, args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
