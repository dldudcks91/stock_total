"""금요일(6/12) 0.5° + residence 80% 필터 통과 종목 + 오늘(6/15) 변동.

약세 진입 조건은 제외 (얼마나 잡히는지 보기 위함).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.mtf_loader import load_normalized_daily, resample_multi_tf
from scripts._common.mtf_indicators import compute_mtf_indicators
from scripts._common.signals import _compute_range_threshold, PARTIAL_CONSEC_BARS
from scripts._common.tf_selector import determine_eval_kind, select_eval_tfs
from scripts._common.recommend_runner import EVAL_TFS, MIN_DAILY_BARS, discover_universe

ASSET = "kr"
ANGLE_MIN = 0.5
RES_MIN = 0.80
RES_WINDOW = 20

THU = pd.Timestamp("2026-06-11")
FRI = pd.Timestamp("2026-06-12")
MON = pd.Timestamp("2026-06-15")

_DF_CACHE: dict = {}


def get_daily(sym: str):
    if sym not in _DF_CACHE:
        try:
            _DF_CACHE[sym] = load_normalized_daily(ASSET, sym)
        except Exception:
            _DF_CACHE[sym] = None
    return _DF_CACHE[sym]


def best_passing(sym: str, cutoff: pd.Timestamp):
    df_full = get_daily(sym)
    if df_full is None:
        return None
    df_d = df_full[df_full.index <= cutoff]
    if len(df_d) < MIN_DAILY_BARS or cutoff not in df_d.index:
        return None
    mtf = resample_multi_tf(df_d)
    allowed = set(select_eval_tfs(mtf))
    today_low = float(df_d["low"].iloc[-1])
    th = _compute_range_threshold(df_d)
    if pd.isna(th):
        return None

    best = None
    for tf in EVAL_TFS:
        df_tf = mtf[tf]
        kind = determine_eval_kind(df_tf)
        if (tf not in allowed) or kind == "skip":
            continue
        df_ind = compute_mtf_indicators(df_tf, kind)
        if len(df_ind) < 1:
            continue
        last = df_ind.iloc[-1]
        close = last["close"]
        ma10 = last["ma10"]
        sl10 = last["slope_pct_ma10"]
        if pd.isna(ma10) or pd.isna(sl10):
            continue

        if kind == "full":
            ma20 = last["ma20"]
            sl20 = last["slope_pct_ma20"]
            if pd.isna(ma20) or pd.isna(sl20):
                continue
            if not ((ma10 > ma20) and (close > ma20) and sl10 > 0 and sl20 > 0):
                continue
            d10 = abs(today_low - ma10)
            d20 = abs(today_low - ma20)
            if not (d10 <= th or d20 <= th):
                continue
            angle = float(last.get("angle_ma20_deg", float("nan")))
            tail = df_ind.tail(RES_WINDOW)
            if len(tail) < RES_WINDOW:
                continue
            residence = float((tail["close"] > tail["ma20"]).mean())
        else:
            if not (close > ma10 and sl10 > 0):
                continue
            d10 = abs(today_low - ma10)
            if not (d10 <= th):
                continue
            tail3 = df_ind.tail(PARTIAL_CONSEC_BARS)
            if not (tail3["close"] > tail3["ma10"]).all():
                continue
            angle = float(last.get("angle_ma10_deg", float("nan")))
            tail = df_ind.tail(RES_WINDOW)
            if len(tail) < RES_WINDOW:
                continue
            residence = float((tail["close"] > tail["ma10"]).mean())

        if pd.isna(angle):
            continue
        if angle < ANGLE_MIN or residence < RES_MIN:
            continue
        if best is None or angle > best[1]:
            best = (tf, angle, residence)
    return best


def main():
    symbols = discover_universe(ASSET)
    print(f"universe={len(symbols)}", file=sys.stderr)

    thu_pass = set()
    fri_pass: dict = {}
    for i, sym in enumerate(symbols, 1):
        if best_passing(sym, THU):
            thu_pass.add(sym)
        f = best_passing(sym, FRI)
        if f:
            fri_pass[sym] = f
        if i % 200 == 0:
            print(f"  [{i}/{len(symbols)}]", file=sys.stderr)

    listing = pd.read_csv(_ROOT / "data" / "cache" / "kr" / "_listing.csv", dtype={"Symbol": str})
    name_map = dict(zip(listing["Symbol"], listing["Name"]))

    rows = []
    for sym, (tf, angle, res) in fri_pass.items():
        df_full = get_daily(sym)
        if df_full is None or FRI not in df_full.index or THU not in df_full.index or MON not in df_full.index:
            continue
        thu_c = float(df_full.loc[THU, "close"])
        fri_c = float(df_full.loc[FRI, "close"])
        mon_c = float(df_full.loc[MON, "close"])
        fri_ret = (fri_c - thu_c) / thu_c * 100   # 진입일 변동 (참고)
        mon_ret = (mon_c - fri_c) / fri_c * 100   # 오늘 변동
        bucket = "A" if sym in thu_pass else "B"   # 목→금 유지 vs 신규
        rows.append({"bucket": bucket, "Symbol": sym, "Name": name_map.get(sym, ""),
                     "tf": tf, "angle_deg": angle, "residence_20": res,
                     "Fri_ret_pct": fri_ret, "Mon_close": mon_c, "today_ret_pct": mon_ret})

    df = pd.DataFrame(rows).sort_values(["bucket", "today_ret_pct"], ascending=[True, False]).reset_index(drop=True)
    print(f"\n금요일(6/12) 0.5°+80% 필터 통과: {len(df)}")
    print(f"  A (목/금 유지)  : {(df.bucket == 'A').sum()}")
    print(f"  B (금 신규)    : {(df.bucket == 'B').sum()}")

    s = df["today_ret_pct"]
    print(f"  오늘 변동 — mean={s.mean():+.2f}%  median={s.median():+.2f}%  win={(s>0).mean()*100:.0f}%")

    print()
    print("=== A (목/금 유지) — 오늘 변동 내림차순 ===")
    if (df.bucket == "A").any():
        print(df[df.bucket == "A"].to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print()
    print("=== B (금 신규 진입) — 오늘 변동 내림차순 ===")
    if (df.bucket == "B").any():
        print(df[df.bucket == "B"].to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    out_csv = Path(__file__).parent / "_recs_kr_fri_filtered_with_today.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
