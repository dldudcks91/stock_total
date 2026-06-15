"""금요일 신규 진입 (NEW rule) 중 금요일 자체가 하락/보합인 종목만 추출.

조건: Fri_return = (Fri_close − Thu_close) / Thu_close × 100 ≤ 0
의도: 폭등으로 우연히 터치한 노이즈를 거르고, '실제로 눌림목/되돌림' 자리로 진입한 종목만 보기.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

THU = pd.Timestamp("2026-06-11")
FRI = pd.Timestamp("2026-06-12")
MON = pd.Timestamp("2026-06-15")


def main():
    new_csv = Path(__file__).parent / "_recs_kr_fri_new.csv"
    df = pd.read_csv(new_csv, dtype={"Symbol": str})

    rows = []
    for sym, name in zip(df["Symbol"], df["Name"]):
        path = _ROOT / "data" / "cache" / "kr" / f"{sym}.parquet"
        if not path.exists():
            continue
        d = pd.read_parquet(path)
        d.columns = [c.lower() for c in d.columns]
        d = d.sort_index()
        if THU not in d.index or FRI not in d.index:
            continue
        thu_c = float(d.loc[THU, "close"])
        fri_c = float(d.loc[FRI, "close"])
        mon_c = float(d.loc[MON, "close"]) if MON in d.index else None
        fri_ret = (fri_c - thu_c) / thu_c * 100
        mon_ret = (mon_c - fri_c) / fri_c * 100 if mon_c else None
        rows.append({"Symbol": sym, "Name": name, "Thu_close": thu_c, "Fri_close": fri_c, "Mon_close": mon_c,
                     "Fri_ret_pct": fri_ret, "Mon_ret_pct": mon_ret})

    out = pd.DataFrame(rows)
    no_rally = out[out["Fri_ret_pct"] <= 0].sort_values("Fri_ret_pct").reset_index(drop=True)

    print(f"전체 신규 진입: {len(out)}")
    print(f"  금요일 하락(<0): {(out['Fri_ret_pct'] < 0).sum()}")
    print(f"  금요일 보합(=0): {(out['Fri_ret_pct'] == 0).sum()}")
    print(f"  금요일 상승(>0): {(out['Fri_ret_pct'] > 0).sum()}")
    print(f"  → 하락+보합 추출: {len(no_rally)}")
    print()
    print("=== 금요일 하락/보합 신규 진입 종목 ===")
    print("(Fri_ret = 금요일 종가 변화, Mon_ret = 월요일 종가 변화)")
    print()
    print(no_rally.to_string(index=False,
                             columns=["Symbol", "Name", "Thu_close", "Fri_close", "Mon_close", "Fri_ret_pct", "Mon_ret_pct"],
                             float_format=lambda v: f"{v:.2f}"))

    if len(no_rally) > 0:
        print()
        print(f"=== 그룹 통계 (하락/보합 신규, n={len(no_rally)}) ===")
        s = no_rally["Mon_ret_pct"].dropna()
        print(f"  Mon mean    : {s.mean():+.2f}%")
        print(f"  Mon median  : {s.median():+.2f}%")
        print(f"  Mon 상승    : {(s > 0).sum()}  ({(s > 0).mean()*100:.0f}%)")
        print(f"  Mon 하락    : {(s < 0).sum()}  ({(s < 0).mean()*100:.0f}%)")

    out_csv = Path(__file__).parent / "_recs_kr_fri_new_no_rally.csv"
    no_rally.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
