"""KRX 종목별 투자자 순매수 상위 (연기금 등 임의 주체, 임의 기간).

2025-12-27 부터 KRX 정보데이터시스템이 회원 로그인 의무화로 전환되어
직접 호출 시 `LOGOUT` (400) 반환된다. 이 스크립트는 pykrx v1.2.8 의
로그인 흐름 (PR #254) 을 그대로 재현한 뒤 [12010] 투자자별 순매수상위
엔드포인트 (MDCSTAT02401) 를 호출한다.

요구:
  - `.env` 에 `KRX_ID=...` / `KRX_PW=...` (data.krx.co.kr 계정).
    네이버/카카오 간편가입 가능, 데이터 조회 자체는 무료.

사용:
  .venv/Scripts/python.exe -m temp.fetch_krx_pension_top \
      --from 20260608 --to 20260622 --market ALL --investor 6000 --top 10
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

import pandas as pd
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

LOGIN_PAGE = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
LOGIN_JSP = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
LOGIN_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
DATA_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
DATA_REFERER = "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

INVESTOR_CODES = {
    "1000": "금융투자", "2000": "보험", "3000": "투신", "3100": "사모",
    "4000": "은행", "5000": "기타금융", "6000": "연기금", "7050": "기관합계",
    "7100": "기타법인", "8000": "개인", "9000": "외국인",
    "9001": "기타외국인", "9999": "전체",
}
MARKET_NAMES = {"STK": "KOSPI", "KSQ": "KOSDAQ", "ALL": "KOSPI+KOSDAQ"}


def krx_login(login_id: str, login_pw: str) -> Optional[requests.Session]:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.get(LOGIN_PAGE, timeout=15)
    s.get(LOGIN_JSP, headers={"Referer": LOGIN_PAGE}, timeout=15)
    payload = {"mbrNm": "", "telNo": "", "di": "", "certType": "",
               "mbrId": login_id, "pw": login_pw}
    r = s.post(LOGIN_URL, data=payload,
               headers={"Referer": LOGIN_PAGE}, timeout=15)
    data = r.json()
    code = data.get("_error_code", "")
    msg = data.get("_error_message", "")
    if code == "CD010":
        print(f"[KRX] 비밀번호 변경 필요: {msg}", file=sys.stderr)
        return None
    if code == "CD011":
        payload["skipDup"] = "Y"
        r = s.post(LOGIN_URL, data=payload,
                   headers={"Referer": LOGIN_PAGE}, timeout=15)
        data = r.json()
        code = data.get("_error_code", "")
    if code != "CD001":
        print(f"[KRX] 로그인 실패 ({code}): {data.get('_error_message','')}",
              file=sys.stderr)
        return None
    print(f"[KRX] 로그인 OK (id={login_id})", file=sys.stderr)
    return s


def fetch_investor_top(session: requests.Session, fr: str, to: str,
                       market: str, investor: str) -> pd.DataFrame:
    payload = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT02401",
        "strtDd": fr, "endDd": to, "mktId": market, "invstTpCd": investor,
    }
    headers = {
        "User-Agent": UA, "Referer": DATA_REFERER,
        "X-Requested-With": "XMLHttpRequest",
    }
    r = session.post(DATA_URL, data=payload, headers=headers, timeout=30)
    r.raise_for_status()
    out = r.json().get("output", [])
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out)
    # 숫자 컬럼 정리
    num_cols = ["ASK_TRDVOL", "BID_TRDVOL", "NETBID_TRDVOL",
                "ASK_TRDVAL", "BID_TRDVAL", "NETBID_TRDVAL"]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""),
                                  errors="coerce")
    return df


def fmt_eok(v: float) -> str:
    return f"{v/1e8:+,.0f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="fr", required=True, help="YYYYMMDD")
    ap.add_argument("--to", dest="to", required=True, help="YYYYMMDD")
    ap.add_argument("--market", default="ALL",
                    choices=["STK", "KSQ", "ALL"],
                    help="STK=KOSPI / KSQ=KOSDAQ / ALL")
    ap.add_argument("--investor", default="6000",
                    help="투자자 코드 (기본 6000=연기금)")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    kid, kpw = os.getenv("KRX_ID"), os.getenv("KRX_PW")
    if not (kid and kpw):
        print("[ERR] KRX_ID / KRX_PW 환경변수 (.env) 필요. "
              "data.krx.co.kr 계정으로 설정.", file=sys.stderr)
        sys.exit(2)

    s = krx_login(kid, kpw)
    if s is None:
        sys.exit(3)

    df = fetch_investor_top(s, args.fr, args.to, args.market, args.investor)
    inv_nm = INVESTOR_CODES.get(args.investor, args.investor)
    mkt_nm = MARKET_NAMES.get(args.market, args.market)
    if df.empty:
        print(f"[{mkt_nm}] {args.fr}~{args.to} {inv_nm}: 결과 없음")
        sys.exit(0)

    print(f"\n=== {mkt_nm} · {inv_nm} 순매수 ({args.fr} ~ {args.to}) ===")
    print(f"  대상 종목 수: {len(df)}, 단위: 거래대금=억원, 거래량=주")

    cols_show = ["ISU_SRT_CD", "ISU_NM",
                 "BID_TRDVAL", "ASK_TRDVAL", "NETBID_TRDVAL"]
    df = df.dropna(subset=["NETBID_TRDVAL"]).copy()

    top_buy = df.sort_values("NETBID_TRDVAL", ascending=False).head(args.top)
    top_sell = df.sort_values("NETBID_TRDVAL", ascending=True).head(args.top)

    def render(d: pd.DataFrame) -> pd.DataFrame:
        r = d[cols_show].copy()
        r.columns = ["코드", "종목명", "매수대금(억)",
                     "매도대금(억)", "순매수(억)"]
        for c in ("매수대금(억)", "매도대금(억)", "순매수(억)"):
            r[c] = r[c].apply(fmt_eok)
        return r.reset_index(drop=True)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 30)
    print(f"\n[순매수 Top {args.top}]")
    print(render(top_buy).to_string(index=False))
    print(f"\n[순매도 Top {args.top}]")
    print(render(top_sell).to_string(index=False))


if __name__ == "__main__":
    main()
