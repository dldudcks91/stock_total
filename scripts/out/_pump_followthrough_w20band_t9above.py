"""
_pump_followthrough_w20band.py 의 forward=20 결과(CSV)를 후처리:
  + t+9 종가가 그 봉 MA10 위인 케이스만 남기고 봉별 통계 재산출.

⚠️ backward filter (look-ahead). 실전 셋업 X, 사후 분포 분석만.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import pandas as pd

OUT_DIR = Path("scripts/out")
SRC = OUT_DIR / "pump_followthrough_w20band_f20_events.csv"
FORWARD = 20


def main():
    ev = pd.read_csv(SRC)
    print(f"source: {SRC.name} → {len(ev):,} rows, {ev['symbol'].nunique()} symbols")

    mask = ev["dist_ma10_t+9_pct"] > 0
    sub = ev[mask].copy()
    print(f"filter (dist_ma10_t+9_pct > 0): {len(sub):,} rows ({len(sub)/len(ev):.1%}), {sub['symbol'].nunique()} symbols")

    print("\n=== 표 1. 전체 집계 (t+9 MA10 위 케이스) ===")
    summary = [
        ("총_트리거_횟수", len(sub), False),
        ("고유_심볼_수", int(sub["symbol"].nunique()), False),
        ("트리거봉_몸통상승률_중앙값_퍼센트", float(sub["trigger_body_pct"].median()), True),
        ("엔트리종가_주봉MA20거리_중앙값_퍼센트", float(sub["entry_close_to_weekly_ma20_pct"].median()), True),
        ("엔트리종가_MA10거리_중앙값_퍼센트", float(sub["entry_close_to_ma10_pct"].median()), True),
    ]
    for k, v, is_pct in summary:
        print(f"  {k}: {v:+.3f}" if is_pct else f"  {k}: {v}")

    rows = []
    for k in range(1, FORWARD + 1):
        rcol = f"ret_t+{k}_pct"
        mcol = f"dist_ma10_t+{k}_pct"
        rows.append({
            "봉_인덱스": f"t+{k}",
            "종가변화율_평균_퍼센트": float(sub[rcol].mean()),
            "종가변화율_중앙값_퍼센트": float(sub[rcol].median()),
            "MA10거리_평균_퍼센트": float(sub[mcol].mean()),
            "MA10거리_중앙값_퍼센트": float(sub[mcol].median()),
        })
    per_bar = pd.DataFrame(rows)
    out = OUT_DIR / "pump_followthrough_w20band_f20_t9above_per_bar.csv"
    per_bar.to_csv(out, index=False)
    print("\n=== 표 2. 봉 인덱스별 forward 통계 ===")
    print(per_bar.to_string(index=False, float_format=lambda x: f"{x:+.3f}"))
    print(f"\nsaved → {out}")


if __name__ == "__main__":
    main()
