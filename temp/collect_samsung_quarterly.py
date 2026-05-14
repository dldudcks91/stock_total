"""삼성전자(005930) 분기 재무 데이터 장기 수집.

수집 범위: 2016Q1 ~ 2026Q1 (수집 가능한 만큼).
출력: temp/samsung_quarterly.csv (단위: 억원)

당기순이익은 fnlttSinglAcnt 의 '당기순이익' (연결 총액)을 사용.
지배주주 귀속분이 별도 필요하면 fnlttSinglAcntAll 로 '지배기업 소유주지분...' 항목 별도 추출 필요.
1차 시도로 fnlttSinglAcntAll 에서 '지배기업의 소유주에게 귀속되는 당기순이익' 시도, 실패 시 총액으로 폴백.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path
from typing import Optional, Dict, List

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.dart import (
    _api_key,
    get_corp_code,
    fetch_quarterly_main,
    parse_main_accounts,
    CACHE_DIR,
    BASE,
    REPRT_CODES,
    _to_int,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


TICKER = "005930"
START_YEAR = 2016
END_YEAR = 2026  # 2026Q1 까지 시도


def fetch_quarterly_all(ticker: str, year: int, quarter: str) -> List[Dict]:
    """fnlttSinglAcntAll — 전체 재무제표 (계정 풍부, 지배주주지분 등 포함)."""
    corp_code = get_corp_code(ticker)
    if corp_code is None:
        return []
    cache_path = CACHE_DIR / f"all_{ticker}_{year}_{quarter}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    time.sleep(0.4)
    r = requests.get(
        f"{BASE}/fnlttSinglAcntAll.json",
        params={
            "crtfc_key": _api_key(),
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": REPRT_CODES[quarter],
            "fs_div": "CFS",  # 연결
        },
        timeout=30,
    )
    try:
        data = r.json()
    except Exception:
        data = {"status": "ERR"}
    items = data.get("list", []) if data.get("status") == "000" else []
    cache_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return items


def extract_controlling_net_income(items: List[Dict]) -> Optional[int]:
    """fnlttSinglAcntAll 에서 '지배기업 소유주에게 귀속되는 당기순이익' 추출."""
    # 표기 변형 다양: 키워드 매칭으로
    keywords = ["지배기업", "지배회사", "소유주", "지배주주"]
    for it in items:
        nm = it.get("account_nm", "")
        if "순이익" in nm and any(k in nm for k in keywords):
            val = _to_int(it.get("thstrm_amount"))
            if val is not None:
                return val
    return None


def collect_quarter(year: int, quarter: int) -> Optional[Dict]:
    """한 분기의 누적 raw 값을 반환 (revenue/op_profit/net_income).
    1Q/2Q/3Q 의 fnlttSinglAcnt 응답은 단독 분기값 (3개월).
    Q4(사업보고서) 응답은 연간(12개월) 합계.
    """
    q_label = f"{quarter}Q"
    items_main = fetch_quarterly_main(TICKER, year, q_label)
    if not items_main:
        return None
    parsed = parse_main_accounts(items_main)
    if parsed["revenue"] is None:
        return None

    # 지배주주순이익 시도 (fnlttSinglAcntAll)
    items_all = fetch_quarterly_all(TICKER, year, q_label)
    controlling = extract_controlling_net_income(items_all)
    if controlling is not None:
        parsed["net_income_controlling"] = controlling
    else:
        parsed["net_income_controlling"] = parsed["net_income"]  # 폴백

    return parsed


def main() -> None:
    cc = get_corp_code(TICKER)
    print(f"[info] corp_code({TICKER}) = {cc}")

    raw: Dict = {}  # (year, quarter) -> {revenue, op_profit, net_income_controlling}
    for yr in range(START_YEAR, END_YEAR + 1):
        for q in (1, 2, 3, 4):
            # 미래 분기 skip
            if yr == 2026 and q > 1:
                continue
            print(f"[fetch] {yr}Q{q} ...", end="", flush=True)
            data = collect_quarter(yr, q)
            if data is None:
                print(" (no data)")
                continue
            raw[(yr, q)] = data
            print(
                f" rev={data['revenue']/1e8:>10,.0f}억 op={data['op_profit']/1e8:>9,.0f}억 ni={data['net_income_controlling']/1e8:>9,.0f}억"
            )

    # 분기 단독값 산출
    # Q1/Q2/Q3 : fnlttSinglAcnt 가 이미 분기 단독값 (3개월) 을 반환
    # Q4       : 연간(11011) - Q1 - Q2 - Q3
    rows: List[Dict] = []
    for (yr, q), data in sorted(raw.items()):
        if q < 4:
            single = dict(data)
        else:
            q1 = raw.get((yr, 1))
            q2 = raw.get((yr, 2))
            q3 = raw.get((yr, 3))
            if not (q1 and q2 and q3):
                print(f"[warn] {yr}Q4 단독 계산 불가 (Q1~Q3 누락)")
                continue
            def _diff(annual, *parts):
                if annual is None or any(p is None for p in parts):
                    return None
                return annual - sum(parts)

            single = {
                "revenue": _diff(data["revenue"], q1["revenue"], q2["revenue"], q3["revenue"]),
                "op_profit": _diff(data["op_profit"], q1["op_profit"], q2["op_profit"], q3["op_profit"]),
                "net_income_controlling": _diff(
                    data["net_income_controlling"],
                    q1["net_income_controlling"],
                    q2["net_income_controlling"],
                    q3["net_income_controlling"],
                ),
                "fs_div": data.get("fs_div"),
            }
        rows.append({"year": yr, "quarter": q, **single})

    # CSV 저장 (단위: 억원)
    out_path = ROOT / "temp" / "samsung_quarterly.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "quarter", "report_period", "revenue_eok", "op_profit_eok", "net_profit_eok", "fs_div"])
        for r in rows:
            rev = r.get("revenue")
            op = r.get("op_profit")
            ni = r.get("net_income_controlling")
            w.writerow([
                r["year"],
                r["quarter"],
                f"{r['year']}Q{r['quarter']}",
                f"{rev/1e8:.0f}" if rev is not None else "",
                f"{op/1e8:.0f}" if op is not None else "",
                f"{ni/1e8:.0f}" if ni is not None else "",
                r.get("fs_div") or "",
            ])
    print(f"\n[done] {len(rows)} rows -> {out_path}")

    # 간단 요약
    if rows:
        last4 = rows[-4:]
        print("\n[recent 4 quarters]")
        for r in last4:
            print(
                f"  {r['year']}Q{r['quarter']}: "
                f"매출 {r['revenue']/1e8:>8,.0f}억  "
                f"OP {r['op_profit']/1e8:>8,.0f}억  "
                f"NI {r['net_income_controlling']/1e8:>8,.0f}억"
            )


if __name__ == "__main__":
    main()
