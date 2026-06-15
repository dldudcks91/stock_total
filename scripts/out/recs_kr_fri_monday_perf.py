"""금요일 신규 진입 vs 탈락 종목의 오늘(월요일) 수익률 비교.

기준:
  - 진입일: 2026-06-12 (Friday 종가에 매수했다 가정)
  - 평가일: 2026-06-15 (Monday 종가)
  - 변동률: (Mon_close - Fri_close) / Fri_close × 100
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

FRI = pd.Timestamp("2026-06-12")
MON = pd.Timestamp("2026-06-15")


def perf_table(csv_path: Path, label: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype={"Symbol": str})
    rows = []
    for sym, name in zip(df["Symbol"], df["Name"]):
        path = _ROOT / "data" / "cache" / "kr" / f"{sym}.parquet"
        if not path.exists():
            continue
        d = pd.read_parquet(path)
        d.columns = [c.lower() for c in d.columns]
        d = d.sort_index()
        if FRI not in d.index or MON not in d.index:
            continue
        fri_c = float(d.loc[FRI, "close"])
        mon_c = float(d.loc[MON, "close"])
        ret = (mon_c - fri_c) / fri_c * 100
        rows.append({"Symbol": sym, "Name": name, "Fri_close": fri_c, "Mon_close": mon_c, "ret_pct": ret})
    out = pd.DataFrame(rows).sort_values("ret_pct", ascending=False).reset_index(drop=True)
    out["bucket"] = label
    return out


def main():
    out_dir = Path(__file__).parent
    new_df = perf_table(out_dir / "_recs_kr_fri_new.csv", "new")
    drop_df = perf_table(out_dir / "_recs_kr_fri_drop.csv", "drop")

    def summarize(df: pd.DataFrame, label: str):
        s = df["ret_pct"]
        print(f"\n=== {label}  n={len(df)} ===")
        print(f"  mean   : {s.mean():+.2f}%")
        print(f"  median : {s.median():+.2f}%")
        print(f"  min    : {s.min():+.2f}%")
        print(f"  max    : {s.max():+.2f}%")
        print(f"  >0     : {(s > 0).sum()}  ({(s > 0).mean()*100:.0f}%)")
        print(f"  ==0    : {(s == 0).sum()}")
        print(f"  <0     : {(s < 0).sum()}  ({(s < 0).mean()*100:.0f}%)")

    summarize(new_df, "Friday 새 진입")
    summarize(drop_df, "Friday 탈락")

    # Welch t-test 없이 단순 평균 차
    print("\n=== 두 그룹 비교 ===")
    print(f"  평균차 (new − drop): {new_df['ret_pct'].mean() - drop_df['ret_pct'].mean():+.2f}%p")
    print(f"  중앙값차          : {new_df['ret_pct'].median() - drop_df['ret_pct'].median():+.2f}%p")

    print("\n=== Friday 새 진입 — Top10 상승 ===")
    print(new_df.head(10).to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print("\n=== Friday 새 진입 — Top10 하락 ===")
    print(new_df.tail(10).iloc[::-1].to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    print("\n=== Friday 탈락 — Top10 상승 ===")
    print(drop_df.head(10).to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print("\n=== Friday 탈락 — Top10 하락 ===")
    print(drop_df.tail(10).iloc[::-1].to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    combined = pd.concat([new_df, drop_df], ignore_index=True)
    out_csv = out_dir / "_recs_kr_fri_mon_perf.csv"
    combined.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
