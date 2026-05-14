"""SK하이닉스(000660) 분기 재무 데이터 장기 수집.

수집 범위: 2016Q1 ~ 2026Q1 (수집 가능한 만큼).
출력: temp/hynix_quarterly.csv (단위: 억원, 연결 우선)

당기순이익은 fnlttSinglAcntAll 의 '지배기업 소유주지분' (지배주주 귀속) 우선 추출,
실패 시 fnlttSinglAcnt 의 '당기순이익' (연결 총액) 폴백.

DART_API_KEY 는 프로젝트 루트 .env 에서 로드 후 env 변수로 주입
(research/dart.py 의 _load_env_key 가 research/.env 만 보므로).
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional, Dict, List

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# .env 로드 (DART API key)
_env_path = ROOT / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line.startswith("DART_API_KEY"):
            _, _, _val = _line.partition("=")
            os.environ["DART_API_KEY"] = _val.strip().strip('"').strip("'")
            break

from research.dart import (  # noqa: E402
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


TICKER = "000660"
START_YEAR = 2016
END_YEAR = 2026  # 2026Q1 까지 시도


def fetch_quarterly_all(ticker: str, year: int, quarter: str, fs_div: str = "CFS") -> List[Dict]:
    """fnlttSinglAcntAll — 전체 재무제표 (계정 풍부, 지배주주지분 등 포함)."""
    corp_code = get_corp_code(ticker)
    if corp_code is None:
        return []
    cache_path = CACHE_DIR / f"all_{ticker}_{year}_{quarter}_{fs_div}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    time.sleep(0.4)
    try:
        r = requests.get(
            f"{BASE}/fnlttSinglAcntAll.json",
            params={
                "crtfc_key": _api_key(),
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": REPRT_CODES[quarter],
                "fs_div": fs_div,
            },
            timeout=30,
        )
        data = r.json()
    except Exception:
        data = {"status": "ERR"}
    items = data.get("list", []) if data.get("status") == "000" else []
    cache_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return items


def extract_controlling_net_income(items: List[Dict]) -> Optional[int]:
    """CIS / IS 항목에서 '지배기업의 소유주지분' 당기순이익 추출.

    SK하이닉스/삼성전자 사례에서 account_nm 가 그냥 '지배기업의 소유주지분' 으로
    표시되며 직전 행이 '분기순이익(손실)' 또는 '당기순이익(손실)' 인 패턴이 흔함.
    또는 'XX순이익(손실)' 의 변형 + '지배기업'/'소유주' 키워드 포함하기도 함.
    """
    # 패턴 1: '지배기업'/'소유주' + '순이익' 조합
    for it in items:
        if it.get("sj_div") not in ("CIS", "IS"):
            continue
        nm = it.get("account_nm", "")
        if any(k in nm for k in ("지배기업", "지배회사", "지배주주")) and "순이익" in nm:
            v = _to_int(it.get("thstrm_amount"))
            if v is not None:
                return v

    # 패턴 2: '분기순이익(손실)' 또는 '당기순이익(손실)' 바로 다음 등장하는
    # '지배기업의 소유주지분' (CIS 영역, sj_div=CIS)
    # 실제 응답에서는 다음 순서: 분기순이익(손실) -> 비지배지분 -> 지배기업의 소유주지분
    # 그러므로 account_nm 가 '지배기업의 소유주지분' 또는 '지배기업의 소유주에게 귀속되는...'
    for it in items:
        if it.get("sj_div") not in ("CIS", "IS"):
            continue
        nm = it.get("account_nm", "")
        if nm in ("지배기업의 소유주지분", "지배기업 소유주지분"):
            v = _to_int(it.get("thstrm_amount"))
            if v is not None:
                return v
        if "지배기업" in nm and "소유주" in nm:
            v = _to_int(it.get("thstrm_amount"))
            if v is not None:
                return v
    return None


def collect_quarter(year: int, quarter: int) -> Optional[Dict]:
    """한 분기 raw 값 (revenue/op_profit/net_income/net_income_controlling).
    1Q/2Q/3Q : 단독 분기 (3개월) 값
    Q4(11011): 연간 12개월 합계
    """
    q_label = f"{quarter}Q"
    items_main = fetch_quarterly_main(TICKER, year, q_label)
    if not items_main:
        return None
    parsed = parse_main_accounts(items_main)
    if parsed["revenue"] is None:
        return None

    # 지배주주 순이익 시도 (CFS 우선, 없으면 OFS)
    controlling = None
    for fs in ("CFS", "OFS"):
        items_all = fetch_quarterly_all(TICKER, year, q_label, fs_div=fs)
        controlling = extract_controlling_net_income(items_all)
        if controlling is not None:
            break
    parsed["net_income_controlling"] = controlling if controlling is not None else parsed["net_income"]
    return parsed


def main() -> None:
    cc = get_corp_code(TICKER)
    print(f"[info] corp_code({TICKER}) = {cc}")

    raw: Dict = {}
    for yr in range(START_YEAR, END_YEAR + 1):
        for q in (1, 2, 3, 4):
            if yr == 2026 and q > 1:
                continue
            print(f"[fetch] {yr}Q{q} ...", end="", flush=True)
            data = collect_quarter(yr, q)
            if data is None:
                print(" (no data)")
                continue
            raw[(yr, q)] = data
            print(
                f" rev={data['revenue']/1e8:>11,.0f}억 "
                f"op={data['op_profit']/1e8:>10,.0f}억 "
                f"ni_ctrl={(data['net_income_controlling'] or 0)/1e8:>10,.0f}억 "
                f"({data.get('fs_div')})"
            )

    # 분기 단독값 산출
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

    out_path = ROOT / "temp" / "hynix_quarterly.csv"
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

    if rows:
        last4 = rows[-4:]
        print("\n[recent 4 quarters]")
        for r in last4:
            print(
                f"  {r['year']}Q{r['quarter']}: "
                f"매출 {r['revenue']/1e8:>9,.0f}억  "
                f"OP {r['op_profit']/1e8:>9,.0f}억  "
                f"NI {(r['net_income_controlling'] or 0)/1e8:>9,.0f}억"
            )


if __name__ == "__main__":
    main()
