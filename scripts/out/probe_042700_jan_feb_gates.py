"""한미반도체 1~2월 일별 모든 TF 게이트 상태 — 어디서 컷됐나 추적.

대상 기간: 2026-01-02 ~ 2026-02-25
TF별로 각 게이트 (정배열/slope/touch/angle/residence) 통과 여부 표시.
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
from scripts._common.recommend_runner import EVAL_TFS, MIN_DAILY_BARS

SYM = "042700"
ANGLE_MIN = 0.5
RES_MIN = 0.80
RES_WINDOW = 20

START = pd.Timestamp("2026-01-02")
END = pd.Timestamp("2026-02-25")


def analyze_day(df_full, cutoff: pd.Timestamp):
    """각 TF 게이트 상태 dict 반환."""
    df_d = df_full[df_full.index <= cutoff]
    if len(df_d) < MIN_DAILY_BARS or cutoff not in df_d.index:
        return None
    mtf = resample_multi_tf(df_d)
    allowed = set(select_eval_tfs(mtf))
    today_low = float(df_d["low"].iloc[-1])
    th = _compute_range_threshold(df_d)

    rows = []
    for tf in EVAL_TFS:
        df_tf = mtf[tf]
        kind = determine_eval_kind(df_tf)
        allow = tf in allowed
        if (not allow) or kind == "skip":
            continue
        df_ind = compute_mtf_indicators(df_tf, kind)
        if len(df_ind) < 1:
            continue
        last = df_ind.iloc[-1]
        close = last["close"]
        ma10 = last["ma10"]
        ma20 = last.get("ma20") if kind == "full" else None
        sl10 = last["slope_pct_ma10"]
        sl20 = last.get("slope_pct_ma20") if kind == "full" else None

        if kind == "full":
            angle = last.get("angle_ma20_deg")
            tail = df_ind.tail(RES_WINDOW)
            residence = float((tail["close"] > tail["ma20"]).mean()) if len(tail) == RES_WINDOW else float("nan")
            d10 = abs(today_low - ma10) if pd.notna(ma10) else float("nan")
            d20 = abs(today_low - ma20) if pd.notna(ma20) else float("nan")
            g_align = pd.notna(ma10) and pd.notna(ma20) and (ma10 > ma20) and (close > ma20)
            g_slope = pd.notna(sl10) and pd.notna(sl20) and (sl10 > 0) and (sl20 > 0)
            g_touch = (pd.notna(d10) and d10 <= th) or (pd.notna(d20) and d20 <= th)
            g_angle = pd.notna(angle) and angle >= ANGLE_MIN
            g_res = pd.notna(residence) and residence >= RES_MIN
        else:
            angle = last.get("angle_ma10_deg")
            tail = df_ind.tail(RES_WINDOW)
            residence = float((tail["close"] > tail["ma10"]).mean()) if len(tail) == RES_WINDOW else float("nan")
            d10 = abs(today_low - ma10) if pd.notna(ma10) else float("nan")
            g_align = pd.notna(ma10) and (close > ma10)
            g_slope = pd.notna(sl10) and (sl10 > 0)
            g_touch = pd.notna(d10) and d10 <= th
            g_angle = pd.notna(angle) and angle >= ANGLE_MIN
            g_res = pd.notna(residence) and residence >= RES_MIN
            ma20 = float("nan")

        passed = g_align and g_slope and g_touch and g_angle and g_res
        rows.append({
            "tf": tf, "kind": kind,
            "close": close, "ma10": ma10, "ma20": ma20,
            "today_low": today_low,
            "align": g_align, "slope+": g_slope, "touch": g_touch,
            "angle_deg": float(angle) if pd.notna(angle) else float("nan"),
            "angle_ok": g_angle,
            "residence": residence if pd.notna(residence) else float("nan"),
            "res_ok": g_res,
            "PASS": passed,
        })
    return rows


def main():
    df_full = load_normalized_daily("kr", SYM)
    dates = df_full.index[(df_full.index >= START) & (df_full.index <= END)]

    print(f"한미반도체 1~2월 {len(dates)} 거래일 — 각 TF 게이트 상태\n")
    print(f"각 행 = (TF). align/slope+/touch/angle/res 모두 ✓ 면 PASS")
    print(f"임계: angle≥{ANGLE_MIN}°, residence≥{int(RES_MIN*100)}%/{RES_WINDOW}봉\n")

    # 요약용 — 각 일자 어떤 TF 가 가장 가까웠나
    summary = []
    detail_lines = []

    for d in dates:
        rows = analyze_day(df_full, d)
        if not rows:
            continue
        close = rows[0]["close"]
        # 일변동
        prev_idx = df_full.index.searchsorted(d) - 1
        day_ret = (close / df_full.iloc[prev_idx]["close"] - 1) * 100 if prev_idx >= 0 else 0
        any_pass = any(r["PASS"] for r in rows)

        # 가장 통과에 가까운 TF — base 룰 통과한 TF 중 angle/res 미달
        best_near = None
        for r in rows:
            score = int(r["align"]) + int(r["slope+"]) + int(r["touch"]) + int(r["angle_ok"]) + int(r["res_ok"])
            if best_near is None or score > best_near[1]:
                best_near = (r, score)

        # 어떤 게이트가 컷했나 (binding TF 기준)
        r0, score0 = best_near
        cuts = []
        if not r0["align"]: cuts.append("align")
        if not r0["slope+"]: cuts.append("slope+")
        if not r0["touch"]: cuts.append("touch")
        if not r0["angle_ok"]: cuts.append(f"angle({r0['angle_deg']:.2f}°)")
        if not r0["res_ok"]: cuts.append(f"res({r0['residence']*100:.0f}%)")

        detail_lines.append(f"\n--- {d.date()}  close={close:,.0f}  day_ret={day_ret:+.2f}%  {'★PASS' if any_pass else '...'} ---")
        for r in rows:
            mark = "✓" if r["PASS"] else " "
            detail_lines.append(
                f"  [{mark}] {r['tf']:3s} {r['kind'][:4]:4s} "
                f"align={'O' if r['align'] else 'X'} slope+={'O' if r['slope+'] else 'X'} "
                f"touch={'O' if r['touch'] else 'X'} angle={r['angle_deg']:>5.2f}°{'O' if r['angle_ok'] else 'X'} "
                f"res={r['residence']*100:>3.0f}%{'O' if r['res_ok'] else 'X'}"
            )

        summary.append({
            "date": d.date(), "close": close, "day_ret_pct": day_ret,
            "any_pass": any_pass,
            "best_tf": r0["tf"], "best_score": score0,
            "fail_gates": ",".join(cuts) if cuts else ""
        })

    sdf = pd.DataFrame(summary)
    print("=== 요약 (date / close / day_ret / pass / best TF / 컷 게이트) ===")
    print(sdf.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    print("\n=== 컷 게이트 빈도 ===")
    from collections import Counter
    cnt = Counter()
    for s in summary:
        for g in s["fail_gates"].split(","):
            if g:
                # angle/res 의 구체적 값 제거
                key = g.split("(")[0]
                cnt[key] += 1
    for g, c in cnt.most_common():
        print(f"  {g:10s} : {c} / {len(summary)} 일")

    print("\n=== 상세 (각 일자 × 각 TF) ===")
    print("\n".join(detail_lines))

    out_csv = Path(__file__).parent / "_probe_042700_jan_feb_gates.csv"
    sdf.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\n요약 CSV: {out_csv.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
