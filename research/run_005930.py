"""삼성전자 시범 실행: 일봉 수집 → 저장 → 정량 지표 출력."""
import json
from pathlib import Path
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collect import fetch_daily, save_daily
from analyze import report_metrics


def main():
    ticker = "005930"
    df = fetch_daily(ticker, start="2022-01-01")
    save_daily(ticker, df)

    metrics = report_metrics(df)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

    out = Path(__file__).resolve().parent / "analysis" / f"{ticker}_metrics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved -> {out}")
    print(f"daily rows: {len(df)}, range: {df.index.min().date()} ~ {df.index.max().date()}")


if __name__ == "__main__":
    main()
