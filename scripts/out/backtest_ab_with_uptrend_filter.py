"""A+B 게이트 추가 백테스트 — 와리가리 차단.

기존 ma_touch 룰 (정배열 + slope+ + touch) 위에 다음 두 게이트 AND:
  A. angle_MA20_deg ≥ 15°  (full) / angle_MA10_deg ≥ 15° (partial)
  B. close > MA20 가 최근 20봉 중 80% 이상 (full) / close > MA10 (partial)

A/B 그룹 분류 + 익일 수익률 동일 방식.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from scripts._common.mtf_loader import load_normalized_daily, resample_multi_tf
from scripts._common.mtf_indicators import compute_mtf_indicators
from scripts._common.signals import _compute_range_threshold
from scripts._common.tf_selector import determine_eval_kind, select_eval_tfs
from scripts._common.recommend_runner import EVAL_TFS, MIN_DAILY_BARS, discover_universe

ASSET = "kr"
LOOKBACK_DAYS = 35

ANGLE_MIN_DEG = 3.0           # 1M 분포 p90 ≈ 3.1° — flat 제거
RESIDENCE_WINDOW = 20
RESIDENCE_FRAC = 0.70         # 와리가리 (≈ 50%) 컷


_DF_CACHE: dict = {}


def get_daily(sym: str):
    if sym not in _DF_CACHE:
        try:
            _DF_CACHE[sym] = load_normalized_daily(ASSET, sym)
        except Exception:
            _DF_CACHE[sym] = None
    return _DF_CACHE[sym]


def passes_at(sym: str, cutoff: pd.Timestamp) -> bool:
    df_full = get_daily(sym)
    if df_full is None:
        return False
    df_d = df_full[df_full.index <= cutoff]
    if len(df_d) < MIN_DAILY_BARS or cutoff not in df_d.index:
        return False
    mtf = resample_multi_tf(df_d)
    allowed = set(select_eval_tfs(mtf))
    today_low = float(df_d["low"].iloc[-1])
    th = _compute_range_threshold(df_d)
    if pd.isna(th):
        return False

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
        angle10 = last.get("angle_ma10_deg", float("nan"))

        if pd.isna(ma10) or pd.isna(sl10):
            continue

        if kind == "full":
            ma20 = last["ma20"]
            sl20 = last["slope_pct_ma20"]
            angle20 = last.get("angle_ma20_deg", float("nan"))
            if any(pd.isna(x) for x in (ma20, sl20)):
                continue
            # base ma_touch 룰
            g_align = (ma10 > ma20) and (close > ma20)
            g_slope = (sl10 > 0) and (sl20 > 0)
            d10 = abs(today_low - ma10)
            d20 = abs(today_low - ma20)
            g_touch = (d10 <= th) or (d20 <= th)
            if not (g_align and g_slope and g_touch):
                continue
            # A. angle gate
            if pd.isna(angle20) or angle20 < ANGLE_MIN_DEG:
                continue
            # B. residence — 최근 20봉 중 close > MA20 80%+
            tail = df_ind.tail(RESIDENCE_WINDOW)
            if len(tail) < RESIDENCE_WINDOW:
                continue
            residence = (tail["close"] > tail["ma20"]).mean()
            if residence < RESIDENCE_FRAC:
                continue
            return True
        else:  # partial
            # base partial rule
            g_align = close > ma10
            g_slope = sl10 > 0
            d10 = abs(today_low - ma10)
            g_touch = d10 <= th
            from scripts._common.signals import PARTIAL_CONSEC_BARS
            tail3 = df_ind.tail(PARTIAL_CONSEC_BARS)
            g_consec = bool((tail3["close"] > tail3["ma10"]).all())
            if not (g_align and g_slope and g_touch and g_consec):
                continue
            # A. angle gate (partial → MA10)
            if pd.isna(angle10) or angle10 < ANGLE_MIN_DEG:
                continue
            # B. residence (partial → MA10)
            tail = df_ind.tail(RESIDENCE_WINDOW)
            if len(tail) < RESIDENCE_WINDOW:
                continue
            residence = (tail["close"] > tail["ma10"]).mean()
            if residence < RESIDENCE_FRAC:
                continue
            return True
    return False


def passers_at(symbols, cutoff: pd.Timestamp) -> set[str]:
    return {s for s in symbols if passes_at(s, cutoff)}


def main():
    symbols = discover_universe(ASSET)
    print(f"universe={len(symbols)}", file=sys.stderr)

    samsung = get_daily("005930")
    if samsung is None:
        samsung = get_daily(symbols[0])
    all_dates = samsung.index
    today = pd.Timestamp.today().normalize()
    recent = all_dates[(all_dates >= today - pd.Timedelta(days=LOOKBACK_DAYS)) & (all_dates <= today)]
    eval_dates = list(recent[:-1])
    print(f"평가 거래일: {len(eval_dates)} 개 ({eval_dates[0].date()} ~ {eval_dates[-1].date()})", file=sys.stderr)

    needed = set(eval_dates)
    for d in eval_dates:
        idx = recent.get_loc(d)
        if idx > 0:
            needed.add(recent[idx - 1])
    needed = sorted(needed)

    passers_cache: dict = {}
    t0 = time.time()
    for i, dt in enumerate(needed, 1):
        passers_cache[dt] = passers_at(symbols, dt)
        elapsed = time.time() - t0
        print(f"  [{i}/{len(needed)}] {dt.date()}: {len(passers_cache[dt])} passers  (elapsed={elapsed:.0f}s)",
              file=sys.stderr)

    listing = pd.read_csv(_ROOT / "data" / "cache" / "kr" / "_listing.csv", dtype={"Symbol": str})
    name_map = dict(zip(listing["Symbol"], listing["Name"]))

    records = []
    for d in eval_dates:
        idx = recent.get_loc(d)
        if idx == 0:
            continue
        prev = recent[idx - 1]
        try:
            next_d = recent[idx + 1]
        except IndexError:
            continue
        prev_set = passers_cache.get(prev, set())
        today_set = passers_cache.get(d, set())
        for sym in today_set:
            df_full = get_daily(sym)
            if df_full is None or d not in df_full.index or prev not in df_full.index or next_d not in df_full.index:
                continue
            ec = float(df_full.loc[d, "close"])
            pc = float(df_full.loc[prev, "close"])
            nc = float(df_full.loc[next_d, "close"])
            today_ret = (ec - pc) / pc * 100
            if today_ret > 0:
                continue
            next_ret = (nc - ec) / ec * 100
            bucket = "A" if sym in prev_set else "B"
            records.append({"eval_date": d.date(), "next_date": next_d.date(),
                            "bucket": bucket, "Symbol": sym, "Name": name_map.get(sym, ""),
                            "today_ret_pct": today_ret, "next_ret_pct": next_ret})

    df = pd.DataFrame(records)
    if df.empty:
        print("no records (필터 너무 빡빡)", file=sys.stderr)
        return

    print(f"\n[필터: angle≥{ANGLE_MIN_DEG}° + residence≥{int(RESIDENCE_FRAC*100)}%/{RESIDENCE_WINDOW}봉]")
    print(f"총 관측치: {len(df)}")
    print(f"  A (유지 + 약세) : {(df.bucket == 'A').sum()}")
    print(f"  B (신규 + 약세) : {(df.bucket == 'B').sum()}")

    def stats(s, label):
        if len(s) == 0:
            print(f"  {label} (n=0)")
            return
        print(f"  {label} (n={len(s)})  mean={s.mean():+.2f}%  median={s.median():+.2f}%  "
              f"win={(s>0).mean()*100:.0f}%  min={s.min():+.2f}%  max={s.max():+.2f}%  std={s.std():.2f}%")

    print("\n=== 그룹별 익일 수익률 ===")
    stats(df[df.bucket == "A"]["next_ret_pct"], "A 유지+약세")
    stats(df[df.bucket == "B"]["next_ret_pct"], "B 신규+약세")
    stats(df["next_ret_pct"], "전체")

    print("\n=== 날짜별 ===")
    day_grp = df.groupby("eval_date").agg(
        n=("Symbol", "count"),
        next_mean=("next_ret_pct", "mean"),
        win=("next_ret_pct", lambda s: (s > 0).mean() * 100),
    )
    print(day_grp.to_string(float_format=lambda v: f"{v:.2f}"))

    out_csv = Path(__file__).parent / "_backtest_ab_with_uptrend_filter.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
