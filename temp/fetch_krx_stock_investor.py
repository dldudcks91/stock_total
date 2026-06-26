"""KRX 종목 1개 × 투자자별 기간합계 거래실적 (MDCSTAT02301).

사용 예 (케이뱅크 상장일~오늘):
  .venv/Scripts/python.exe -m temp.fetch_krx_stock_investor \
      --ticker 279570 --from 20260305 --to 20260623
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from temp.fetch_krx_pension_top import krx_login, UA, DATA_URL, DATA_REFERER


def to_isin(ticker: str) -> str:
    """KR 6자리 코드 → ISIN 12자리. 표준 우선주/보통주 룰 단순화 (KR7+code+3)."""
    return f"KR7{ticker}003"


def fetch_stock_investor(s: requests.Session, fr: str, to: str,
                         isucd: str) -> pd.DataFrame:
    payload = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02301",
        "strtDd": fr, "endDd": to, "isuCd": isucd,
        "inqTpCd": "1", "trdVolVal": "1", "askBid": "1",
    }
    h = {"User-Agent": UA, "Referer": DATA_REFERER,
         "X-Requested-With": "XMLHttpRequest"}
    r = s.post(DATA_URL, data=payload, headers=h, timeout=30)
    r.raise_for_status()
    out = r.json().get("output", [])
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out)
    for c in ("ASK_TRDVOL", "BID_TRDVOL", "NETBID_TRDVOL",
              "ASK_TRDVAL", "BID_TRDVAL", "NETBID_TRDVAL"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""),
                                  errors="coerce")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True, help="6자리 KR 코드 (예 279570)")
    ap.add_argument("--isin", default=None,
                    help="ISIN 12자리 직접 지정 (예 KR7279570006). 생략 시 KR7+ticker+003")
    ap.add_argument("--from", dest="fr", required=True, help="YYYYMMDD")
    ap.add_argument("--to", dest="to", required=True, help="YYYYMMDD")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    kid, kpw = os.getenv("KRX_ID"), os.getenv("KRX_PW")
    if not (kid and kpw):
        print("[ERR] KRX_ID/KRX_PW 환경변수 필요", file=sys.stderr)
        sys.exit(2)
    s = krx_login(kid, kpw)
    if s is None:
        sys.exit(3)

    isucd = args.isin or to_isin(args.ticker)
    df = fetch_stock_investor(s, args.fr, args.to, isucd)
    if df.empty:
        print(f"[{args.ticker}] {args.fr}~{args.to}: 결과 없음")
        return

    df["순매수(억)"] = df["NETBID_TRDVAL"] / 1e8
    df["매수대금(억)"] = df["BID_TRDVAL"] / 1e8
    df["매도대금(억)"] = df["ASK_TRDVAL"] / 1e8
    df["순매수(주)"] = df["NETBID_TRDVOL"]
    df["매수(주)"] = df["BID_TRDVOL"]
    df["매도(주)"] = df["ASK_TRDVOL"]

    print(f"\n=== {args.ticker} · 투자자별 기간합계 ({args.fr} ~ {args.to}) ===")
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 30)
    cols = ["INVST_TP_NM", "매수대금(억)", "매도대금(억)", "순매수(억)",
            "매수(주)", "매도(주)", "순매수(주)"]
    show = df[cols].rename(columns={"INVST_TP_NM": "투자자"})
    for c in ("매수대금(억)", "매도대금(억)", "순매수(억)"):
        show[c] = show[c].map(lambda v: f"{v:+,.0f}")
    for c in ("매수(주)", "매도(주)", "순매수(주)"):
        show[c] = show[c].map(lambda v: f"{int(v):+,}")
    print(show.to_string(index=False))


if __name__ == "__main__":
    main()
