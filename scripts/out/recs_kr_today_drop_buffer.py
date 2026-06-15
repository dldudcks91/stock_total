"""오늘 통과 종목의 '하락 이탈 버퍼' 계산.

각 종목 × 통과 TF 에 대해:
  binding MA = today_low 와 가장 가까운 MA (MA10 또는 MA20)
  threshold = 일봉 range_7 × 0.2 (절대값)
  하한 = binding_MA - threshold   ← low 가 이 아래로 가면 touch 깨짐
  buffer_below = today_low - 하한    (양수면 여유, 0이면 끝, 음수면 이미 깨짐)
  buffer_pct = buffer_below / close × 100

가장 작은 buffer 가진 TF 를 종목별 'fragility'로 채택.
참고: close-MA20 거리도 표시 (정배열 깨질 close 하락폭).
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
from scripts._common.signals import _compute_range_threshold
from scripts._common.tf_selector import determine_eval_kind, select_eval_tfs
from scripts._common.recommend_runner import EVAL_TFS, MIN_DAILY_BARS, discover_universe

MON = pd.Timestamp("2026-06-15")


def analyze_symbol(asset: str, sym: str, name_map: dict):
    try:
        df_d = load_normalized_daily(asset, sym)
    except Exception:
        return None
    df_d = df_d[df_d.index <= MON]
    if len(df_d) < MIN_DAILY_BARS or MON not in df_d.index:
        return None
    mtf = resample_multi_tf(df_d)
    allowed = set(select_eval_tfs(mtf))
    close = float(df_d["close"].iloc[-1])
    today_low = float(df_d["low"].iloc[-1])
    th = _compute_range_threshold(df_d)

    best = None   # 가장 작은 buffer 가진 통과 TF
    for tf in EVAL_TFS:
        df_tf = mtf[tf]
        kind = determine_eval_kind(df_tf)
        if (tf not in allowed) or kind == "skip":
            continue
        df_ind = compute_mtf_indicators(df_tf, kind)
        last = df_ind.iloc[-1]
        ma10 = last["ma10"]
        ma20 = last.get("ma20") if kind == "full" else None
        slope10 = last["slope_pct_ma10"]
        slope20 = last.get("slope_pct_ma20") if kind == "full" else None

        if pd.isna(ma10) or pd.isna(slope10):
            continue
        if kind == "full" and (pd.isna(ma20) or pd.isna(slope20)):
            continue

        if kind == "full":
            d10 = abs(today_low - ma10)
            d20 = abs(today_low - ma20)
            touch_ok = (d10 <= th) or (d20 <= th)
            align_ok = (ma10 > ma20) and (close > ma20)
            slope_ok = (slope10 > 0) and (slope20 > 0)
            if not (touch_ok and align_ok and slope_ok):
                continue
            binding_ma = ma10 if d10 <= d20 else ma20
            binding_label = "MA10" if d10 <= d20 else "MA20"
        else:  # partial
            d10 = abs(today_low - ma10)
            touch_ok = d10 <= th
            align_ok = close > ma10
            slope_ok = slope10 > 0
            if not (touch_ok and align_ok and slope_ok):
                continue
            binding_ma = ma10
            binding_label = "MA10(P)"
            ma20 = float("nan")

        # 버퍼: low 가 (binding_MA − th) 아래로 가면 touch 깨짐
        floor_price = binding_ma - th
        buf_abs = today_low - floor_price       # 양수면 여유
        buf_pct = buf_abs / close * 100

        # close ↔ MA20 거리 (정배열 깨질 close 하락 폭)
        if kind == "full":
            close_to_ma20_pct = (close - ma20) / close * 100   # 양수면 close 가 위
        else:
            close_to_ma20_pct = float("nan")

        rec = {"tf": tf, "binding_label": binding_label, "binding_MA": binding_ma,
               "th_abs": th, "today_low": today_low, "close": close,
               "buf_abs": buf_abs, "buf_pct": buf_pct,
               "close_to_ma20_pct": close_to_ma20_pct}
        if best is None or buf_pct < best["buf_pct"]:
            best = rec
    if best is None:
        return None
    best["Symbol"] = sym
    best["Name"] = name_map.get(sym, "")
    return best


def main():
    asset = "kr"
    symbols = discover_universe(asset)
    listing = pd.read_csv(_ROOT / "data" / "cache" / "kr" / "_listing.csv", dtype={"Symbol": str})
    name_map = dict(zip(listing["Symbol"], listing["Name"]))

    rows = []
    for i, sym in enumerate(symbols, 1):
        r = analyze_symbol(asset, sym, name_map)
        if r:
            rows.append(r)
        if i % 200 == 0:
            print(f"  [{i}/{len(symbols)}] passers so far={len(rows)}", file=sys.stderr)

    df = pd.DataFrame(rows).sort_values("buf_pct").reset_index(drop=True)
    df = df[["Symbol", "Name", "tf", "binding_label", "close", "today_low", "buf_pct",
             "close_to_ma20_pct"]]
    df.columns = ["Symbol", "Name", "TF", "binding", "close", "today_low",
                  "drop_buf_pct", "close_to_MA20_pct"]

    print(f"\n오늘 통과 종목 {len(df)} 의 하락 이탈 버퍼")
    print("(drop_buf_pct = 내일 low 가 이만큼 더 떨어지면 touch 게이트 깨짐. 절대값 % of close)")
    print("(close_to_MA20_pct = close 가 MA20 보다 얼마나 위에 있나. 음수면 이미 정배열 깨짐 임박)")

    # 버퍼 분포
    s = df["drop_buf_pct"]
    print(f"\n=== buffer 분포 ===")
    print(f"  median   : {s.median():.2f}%")
    print(f"  mean     : {s.mean():.2f}%")
    print(f"  p10/p90  : {s.quantile(0.10):.2f}% / {s.quantile(0.90):.2f}%")
    print(f"  최소     : {s.min():.2f}%  ({df.iloc[0]['Symbol']} {df.iloc[0]['Name']})")
    print(f"  최대     : {s.max():.2f}%  ({df.iloc[-1]['Symbol']} {df.iloc[-1]['Name']})")
    print(f"\n  buffer ≤ 0.5% (매우 취약): {(s <= 0.5).sum()}")
    print(f"  buffer ≤ 1.0% (취약)      : {(s <= 1.0).sum()}")
    print(f"  buffer ≤ 2.0% (보통)      : {(s <= 2.0).sum()}")
    print(f"  buffer  > 2.0% (안정)     : {(s > 2.0).sum()}")

    print(f"\n=== 가장 취약한 종목 Top 20 (drop_buf_pct 작은 순) ===")
    print(df.head(20).to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    print(f"\n=== 가장 안정적 Top 10 (drop_buf_pct 큰 순) ===")
    print(df.tail(10).iloc[::-1].to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    out_csv = Path(__file__).parent / "_recs_kr_today_drop_buffer.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
