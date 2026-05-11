"""리포트 생성: 정량 (collect+analyze) + 정성 골격 (broker_report) → 마크다운 파일."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

import statistics
from collect import fetch_daily, save_daily
from analyze import report_metrics
from broker_report import fetch_reports, summarize as summarize_brokers
from pdf_parse import fetch_target_for_report
from industry import industry_brief
from financials import aggregate_across_reports
try:
    from dart import quarterly_series
    _DART_AVAILABLE = True
except Exception:
    _DART_AVAILABLE = False

LABEL_KO = {
    "revenue": "매출액 (십억원)",
    "op_profit": "영업이익 (십억원)",
    "net_income": "순이익 (십억원)",
    "eps": "EPS (원)",
    "per": "PER (배)",
    "pbr": "PBR (배)",
    "roe": "ROE (%)",
    "op_margin": "영업이익률 (%)",
    "ebitda_margin": "EBITDA 마진 (%)",
    "ebitda": "EBITDA (십억원)",
}
# 리포트 노출 순서 (중요한 항목 위로)
LABEL_ORDER = ["revenue", "op_profit", "net_income", "eps", "per", "pbr", "roe", "op_margin", "ebitda_margin"]

REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def _fmt_pct(v):
    return "—" if v is None else f"{v * 100:+.1f}%"


def _fmt_int(v):
    return "—" if v is None else f"{v:,}원"


def build_report(ticker: str, name: str, start: str = "2022-01-01") -> Path:
    df = fetch_daily(ticker, start=start)
    save_daily(ticker, df)
    m = report_metrics(df)

    try:
        broker_rows = fetch_reports(ticker, months=3)
        broker_summary = summarize_brokers(broker_rows)
        broker_ok = True
    except Exception as e:
        broker_rows = []
        broker_summary = {"error": str(e)}
        broker_ok = False

    # 각 리포트의 목표주가/투자의견 추출
    targets = []
    if broker_ok:
        for r in broker_rows:
            idx = r.get("report_idx")
            if not idx:
                continue
            tgt = fetch_target_for_report(idx)
            r["target_price"] = tgt.get("target_price")
            r["opinion"] = tgt.get("opinion")
            if tgt.get("target_price") is not None:
                targets.append(tgt["target_price"])

    consensus = {}
    if targets:
        consensus = {
            "n": len(targets),
            "mean": int(round(statistics.mean(targets))),
            "median": int(statistics.median(targets)),
            "min": min(targets),
            "max": max(targets),
        }
        # 상승여력 (현재가 대비)
        consensus["upside_to_mean"] = consensus["mean"] / m["close"] - 1
        consensus["upside_to_median"] = consensus["median"] / m["close"] - 1

    # 펀더멘털 컨센서스 (PDF Financial Data 표 집계)
    fund_idxs = [r["report_idx"] for r in broker_rows if r.get("report_idx")] if broker_ok else []
    fundamentals = aggregate_across_reports(fund_idxs) if fund_idxs else {"summary": {}, "parsed_count": 0}

    # 분기 실적 (DART 공식)
    quarters = []
    if _DART_AVAILABLE:
        try:
            quarters = quarterly_series(ticker, last_n_quarters=8)
        except Exception as e:
            quarters = []
            print(f"[warn] DART quarterly fetch failed: {e}")

    today = date.today().isoformat()
    out = REPORTS_DIR / f"{ticker}_{today.replace('-', '')}.md"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    md = []
    md.append(f"# {name} ({ticker}) 리서치 리포트")
    md.append("")
    md.append(f"**기준일:** {today}")
    md.append("**산출 모드:** B-1 (정량 실데이터 + 증권사 리포트 메타 + 정성 골격)")
    md.append("")
    md.append("---")
    md.append("")

    try:
        ind = industry_brief(ticker)
        ind_ok = True
    except Exception as e:
        ind = {"error": str(e)}
        ind_ok = False

    md.append("## 1. 기업 개요")
    md.append("")
    if ind_ok and ind["company"].get("found"):
        c = ind["company"]
        mc_str = f"{c['marcap'] / 1e12:,.1f}조원" if c.get("marcap") else "—"
        md.append("| 항목 | 값 |")
        md.append("|---|---|")
        md.append(f"| 종목명 / 코드 | {c['name']} ({c['ticker']}) |")
        md.append(f"| 시장 | {c['market']} |")
        md.append(f"| 시가총액 | **{mc_str}** |")
        md.append(f"| 업종 (KSIC) | {c.get('industry_ksic') or '—'} |")
        md.append(f"| 주요 제품 | {c.get('products') or '—'} |")
        md.append(f"| 대표자 | {c.get('representative') or '—'} |")
        md.append(f"| 본사 | {c.get('region') or '—'} |")
        md.append(f"| 결산월 | {c.get('settle_month') or '—'} |")
        md.append(f"| 상장일 | {c.get('listing_date') or '—'} |")
        md.append(f"| 홈페이지 | {c.get('homepage') or '—'} |")
        md.append("")
        md.append("> *추가 확인 필요* — 사업부별 매출 비중·임직원수·주요 거점·진행 중 투자는 DART 사업보고서로 보강.")
    else:
        md.append("> *수집 실패* — 수동 작성 필요.")
    md.append("")

    md.append("## 2. 업황 / 업계 구조")
    md.append("")
    if ind_ok and ind.get("peers"):
        md.append("**동종 업종 피어 (시가총액 순)**")
        md.append("")
        peer_source = ind["peers"][0].get("_source", "")
        md.append("| 종목 | 코드 | 시장 | 시가총액 |")
        md.append("|---|---|---|---|")
        for p in ind["peers"]:
            mc = f"{p['marcap'] / 1e12:.1f}조원" if p["marcap"] >= 1e12 else f"{p['marcap'] / 1e8:,.0f}억원"
            md.append(f"| {p['name']} | {p['code']} | {p['market']} | {mc} |")
        md.append("")
        md.append(f"> 피어 추출 기준: `{peer_source}`")
        md.append("")
    md.append("> *확인 필요* (자동 미수집 항목) — 업황 사이클 위치 / 밸류체인 위치 / 규제·정책. 산업 리포트 + WebSearch 로 별도 보강.")
    md.append("")

    md.append("## 3. 정량 분석")
    md.append("")
    md.append(f"**기준일: {m['as_of']} 종가 기준**")
    md.append("")
    md.append("| 항목 | 값 |")
    md.append("|---|---|")
    md.append(f"| 종가 | **{m['close']:,}원** |")
    md.append(f"| 52주 최고 / 최저 | {m['high_52w']:,} / {m['low_52w']:,}원 |")
    md.append(f"| MA20 | {_fmt_int(m['ma20'])} (현재가 **{m['ma20_pos']}**) |")
    md.append(f"| MA60 | {_fmt_int(m['ma60'])} (현재가 **{m['ma60_pos']}**) |")
    md.append(f"| MA120 | {_fmt_int(m['ma120'])} (현재가 **{m['ma120_pos']}**) |")
    md.append(f"| 1M 수익률 | **{_fmt_pct(m['ret_1m'])}** |")
    md.append(f"| 3M 수익률 | **{_fmt_pct(m['ret_3m'])}** |")
    md.append(f"| 1Y 수익률 | **{_fmt_pct(m['ret_1y'])}** |")
    vol = m["vol_20d_ann"]
    md.append(f"| 20일 변동성 (연환산) | **{vol * 100:.1f}%** |" if vol is not None else "| 20일 변동성 (연환산) | — |")
    md.append(
        f"| RSI(14) | **{m['rsi14']:.1f} — {m['rsi14_label']}** |"
        if m["rsi14"] is not None
        else "| RSI(14) | — |"
    )
    md.append("")
    md.append(
        f"> 데이터: `data/daily/{ticker}.parquet` ({df.index.min().date()} ~ {df.index.max().date()}, {len(df)}행)"
    )
    md.append("")

    md.append("## 4. 증권사 컨센서스")
    md.append("")
    if broker_ok and broker_rows:
        md.append(
            f"**최근 3개월 발행 리포트: {broker_summary['total_reports']}건** "
            f"({broker_summary['date_range']['from']} ~ {broker_summary['date_range']['to']})"
        )
        md.append("")
        if consensus:
            md.append("**목표주가 컨센서스 (PDF 추출)**")
            md.append("")
            md.append("| 항목 | 값 |")
            md.append("|---|---|")
            md.append(f"| 표기 리포트 수 | {consensus['n']} / {len(broker_rows)}건 |")
            md.append(f"| 평균 | **{consensus['mean']:,}원** |")
            md.append(f"| 중앙값 | **{consensus['median']:,}원** |")
            md.append(f"| 최고 / 최저 | {consensus['max']:,} / {consensus['min']:,}원 |")
            md.append(f"| 현재가 대비 상승여력 (평균) | **{consensus['upside_to_mean'] * 100:+.1f}%** |")
            md.append(f"| 현재가 대비 상승여력 (중앙값) | **{consensus['upside_to_median'] * 100:+.1f}%** |")
            md.append("")
        else:
            md.append("> 목표주가 추출된 리포트 없음 (Issue Comment 위주이거나 PDF 텍스트 추출 실패).")
            md.append("")
        md.append("**커버 증권사 (발행 건수)**")
        md.append("")
        md.append("| 증권사 | 건수 |")
        md.append("|---|---|")
        for broker, cnt in broker_summary["broker_counts"].items():
            md.append(f"| {broker} | {cnt} |")
        md.append("")
        md.append("**개별 리포트 (목표주가·투자의견 포함)**")
        md.append("")
        md.append("| 날짜 | 증권사 | 제목 | 목표주가 | 투자의견 |")
        md.append("|---|---|---|---|---|")
        for r in broker_rows:
            tp = f"{r['target_price']:,}원" if r.get("target_price") else "—"
            op = r.get("opinion") or "—"
            md.append(f"| {r['date']} | {r['broker']} | {r['title']} | {tp} | {op} |")
        md.append("")
        md.append("> 출처: 한경 컨센서스 (consensus.hankyung.com). 목표주가·투자의견은 PDF 1페이지 텍스트에서 정규식 추출.")
    elif broker_ok and not broker_rows:
        md.append("> 최근 3개월 내 발행 리포트 없음.")
    else:
        md.append(f"> *수집 실패* — `{broker_summary.get('error', 'unknown')}`. 수동 확인 필요.")
    md.append("")

    md.append("### 4-2. 펀더멘털 컨센서스 (증권사 추정치 집계)")
    md.append("")
    if fundamentals.get("summary"):
        md.append(f"> 집계 대상: {fundamentals['parsed_count']} / {fundamentals['n_input']}건 PDF 파싱 성공.")
        md.append("> 각 셀은 **중앙값** (괄호 안 = n건 / [min ~ max])")
        md.append("")
        # 모든 연도 수집 후 정렬
        all_years = set()
        for label_data in fundamentals["summary"].values():
            all_years.update(label_data.keys())
        years_sorted = sorted(all_years, key=lambda y: (int(y.replace("E", "")), "E" in y))
        md.append("| 항목 | " + " | ".join(years_sorted) + " |")
        md.append("|" + "---|" * (len(years_sorted) + 1))
        for label_key in LABEL_ORDER:
            if label_key not in fundamentals["summary"]:
                continue
            row_data = fundamentals["summary"][label_key]
            cells = [LABEL_KO.get(label_key, label_key)]
            for y in years_sorted:
                if y not in row_data:
                    cells.append("—")
                else:
                    d = row_data[y]
                    med = d["median"]
                    if med >= 1000:
                        med_str = f"{med:,.0f}"
                    elif med >= 10:
                        med_str = f"{med:.1f}"
                    else:
                        med_str = f"{med:.2f}"
                    cells.append(f"**{med_str}** ({d['n']})")
            md.append("| " + " | ".join(cells) + " |")
        md.append("")
        md.append("> 출처: 한경 컨센서스 PDF 1페이지 Financial Data 표 (`src/financials.py` 파싱). 증권사별 추정 차이가 있어 **중앙값 기준** 표기.")
    else:
        md.append("> 펀더멘털 추출된 리포트 없음.")
    md.append("")

    md.append("### 4-3. 분기 실적 추이 (DART 공식 데이터)")
    md.append("")
    if quarters:
        md.append(f"> 최근 {len(quarters)}분기 단독값 (연결재무제표 기준, 단위: 십억원)")
        md.append("")
        md.append("| 분기 | 매출 | 영업이익 | 순이익 | OP 마진 |")
        md.append("|---|---|---|---|---|")
        for q in quarters:
            label = f"{q['year']}-{q['quarter']}Q"
            rev = q["revenue"] / 1e9 if q.get("revenue") else None
            op = q["op_profit"] / 1e9 if q.get("op_profit") is not None else None
            ni = q["net_income"] / 1e9 if q.get("net_income") is not None else None
            margin = (q["op_profit"] / q["revenue"] * 100) if (q.get("revenue") and q.get("op_profit") is not None) else None
            md.append(
                f"| {label} | {rev:,.0f} | {op:,.0f} | {ni:,.0f} | {margin:.1f}% |"
                if rev is not None
                else f"| {label} | — | — | — | — |"
            )
        md.append("")
        md.append("> 출처: DART OpenAPI `fnlttSinglAcnt`. 1Q/반기/3Q 보고서는 단독 분기값, 사업보고서는 연간 합계 → Q4 = 연간 - Q1 - Q2 - Q3 로 계산.")
    else:
        md.append("> DART 분기 데이터 미수집.")
    md.append("")

    md.append("## 5. 미래가치 / 성장 동력")
    md.append("")
    md.append("> *확인 필요* — IR + 산업 리포트 + 매크로 자료 종합. 위 4번의 증권사 리포트 본문 요약과 결합.")
    md.append("")

    md.append("## 6. 리스크")
    md.append("")
    md.append("> *확인 필요* — 매크로 / 산업 / 회사 고유로 분리.")
    md.append("")

    md.append("## 투자포인트 3줄 요약")
    md.append("")
    md.append("> *확인 필요* — 위 섹션 채워진 후 작성.")
    md.append("")

    md.append("---")
    md.append("")
    md.append("## 부록: 산출 정보")
    md.append("")
    md.append("- 데이터: FinanceDataReader (KRX, KRX-DESC)")
    md.append("- 증권사 리포트: 한경 컨센서스 — 리스트 메타데이터 + PDF 1페이지 정규식 추출 (목표주가·투자의견)")
    md.append("- 분석 모듈: `src/collect.py`, `src/analyze.py`, `src/broker_report.py`, `src/pdf_parse.py`, `src/financials.py`, `src/industry.py`, `src/dart.py`, `src/report.py`")

    out.write_text("\n".join(md), encoding="utf-8")
    print(f"saved -> {out}")
    print(f"close: {m['close']:,}, 1Y ret: {_fmt_pct(m['ret_1y'])}, RSI: {m['rsi14']:.1f}, 리포트: {len(broker_rows)}건")
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python report.py <ticker> <name> [start]")
        sys.exit(1)
    ticker = sys.argv[1]
    name = sys.argv[2]
    start = sys.argv[3] if len(sys.argv) > 3 else "2022-01-01"
    build_report(ticker, name, start)
