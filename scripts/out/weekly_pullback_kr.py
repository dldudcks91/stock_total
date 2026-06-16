"""KR 전체 — 주봉 기반 상승 눌림 백테스트 + 주봉MA5-MA10 이격(파라볼릭) 분리력.

주봉 상승눌림 (fresh 신호):
  1 주봉 정배열 우상향: wMA5>wMA10>wMA20 AND wMA10 기울기>0 (3주)
  2 눌림 터치 : 주봉 저가 ≤ wMA5            (MA5까지 눌림, 관통 허용)
  3 추세 유지 : 주봉 종가 > wMA10           (더 깊은 MA10 지지 유지)
  4 유동성    : 거래대금(주봉) 20주 중앙값 ≥ 10억
  + fresh    : 이번 주 신호, 지난 주 신호 아님
  (4 비과열 fan 필터는 백테스트 후 버킷으로 탐색)

엔진(주봉): 신호주 종가 진입 → STOP(주봉종가<wMA10) / TIMEOUT(MAX_HOLD_WK주)
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT)); sys.stdout.reconfigure(encoding="utf-8")
from scripts._common.mtf_loader import load_normalized_daily, resample_multi_tf
from scripts._common.recommend_runner import discover_universe

MIN_TVAL = 1e9
MAX_HOLD_WK = 4
START = pd.Timestamp("2025-09-01"); END = pd.Timestamp("2026-06-15")


def per_symbol(sym):
    d = load_normalized_daily("kr", sym)
    if len(d) < 200: return []
    w = resample_multi_tf(d)["1W"].copy()
    if len(w) < 30: return []
    w["m5"] = w["close"].rolling(5).mean()
    w["m10"] = w["close"].rolling(10).mean()
    w["m20"] = w["close"].rolling(20).mean()
    w["tr"] = pd.concat([w["high"]-w["low"], (w["high"]-w["close"].shift()).abs(),
                         (w["low"]-w["close"].shift()).abs()], axis=1).max(axis=1)
    w["atr"] = w["tr"].rolling(10).mean()
    w["m10slope"] = (w["m10"] - w["m10"].shift(3)) / w["atr"]
    w["fan"] = (w["m5"] - w["m10"]) / w["atr"]               # MA5-MA10 이격(펼침)
    w["tval"] = (w["close"] * w["volume"]).rolling(20).median()

    align = (w["m5"] > w["m10"]) & (w["m10"] > w["m20"]) & (w["m10slope"] > 0)
    touch = w["low"] <= w["m5"]                               # 저가가 MA5까지 눌림(관통 허용)
    hold = w["close"] > w["m10"]                              # MA10 지지 유지
    liq = w["tval"] >= MIN_TVAL
    sig = align & touch & hold & liq & w["m20"].notna() & w["atr"].notna()
    fresh = sig & (~sig.shift(1).fillna(False).astype(bool))

    closes = w["close"].to_numpy(); m10 = w["m10"].to_numpy()
    n = len(w); out = []
    idxs = np.where(fresh.to_numpy() & (w.index >= START) & (w.index <= END))[0]
    for i in idxs:
        ec = closes[i]; reason = ex = None; held = 0
        for j in range(1, MAX_HOLD_WK + 1):
            if i + j >= n: break
            held = j
            if closes[i + j] < m10[i + j]:
                reason, ex = "STOP", closes[i + j]; break
        else:
            j = min(MAX_HOLD_WK, n - 1 - i)
            if j > 0: reason, ex, held = "TIMEOUT", closes[i + j], j
        if reason is None: continue
        out.append({"Symbol": sym, "week": w.index[i].date(), "entry": ec,
                    "ret_pct": (ex/ec - 1)*100, "weeks": held, "reason": reason,
                    "fan": float(w["fan"].iloc[i]), "m10slope": float(w["m10slope"].iloc[i]),
                    "low_m5": float((w["low"].iloc[i]-w["m5"].iloc[i])/w["atr"].iloc[i])})
    return out


def main():
    syms = discover_universe("kr")
    rows = []
    for k, s in enumerate(syms, 1):
        try: rows.extend(per_symbol(s))
        except Exception: pass
        if k % 300 == 0: print(f"  [{k}/{len(syms)}] trades={len(rows)}", file=sys.stderr)
    r = pd.DataFrame(rows)
    listing = pd.read_csv(_ROOT/"data"/"cache"/"kr"/"_listing.csv", dtype={"Symbol": str})
    r["Name"] = r["Symbol"].map(dict(zip(listing["Symbol"], listing["Name"])))

    s = r["ret_pct"]
    print(f"\n[주봉 상승눌림 — KR 전체, {START.date()}~{END.date()}, 보유 최대 {MAX_HOLD_WK}주]")
    print(f"거래 {len(r)} / {r['Symbol'].nunique()} 종목 | 평균 {s.mean():+.2f}% | 중앙 {s.median():+.2f}% | "
          f"승률 {(s>0).mean()*100:.1f}% | STOP {(r['reason']=='STOP').mean()*100:.1f}%")

    print("\n=== fan(주봉MA5-MA10 이격) 5분위별 — 파라볼릭 과열 컷 탐색 ===")
    r["q"] = pd.qcut(r["fan"], 5, labels=False, duplicates="drop")
    g = r.groupby("q").agg(n=("ret_pct","count"), mean=("ret_pct","mean"), median=("ret_pct","median"),
                           win=("ret_pct", lambda x:(x>0).mean()*100),
                           stop=("reason", lambda x:(x=="STOP").mean()*100),
                           fan_lo=("fan","min"), fan_hi=("fan","max"))
    print(g.to_string(float_format=lambda v: f"{v:.2f}"))

    print("\n=== fan 임계별 누적 (≤임계만) ===")
    for thr in [0.5, 0.8, 1.0, 1.5, 2.0, 99]:
        d = r[r["fan"] <= thr]; ss = d["ret_pct"]
        print(f"  fan≤{thr:>4}: n={len(d):5} | 평균{ss.mean():+6.2f}% | 승률{(ss>0).mean()*100:5.1f}% | STOP{(d['reason']=='STOP').mean()*100:5.1f}%")

    print("\n=== 한미반도체(042700) 주봉 신호 ===")
    hm = r[r["Symbol"]=="042700"]
    if len(hm):
        print(hm[["week","entry","fan","m10slope","low_m5","weeks","ret_pct","reason"]].to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    else:
        print("  없음")

    r.drop(columns=["q"]).to_csv(_ROOT/"scripts"/"out"/"_weekly_pullback_kr.csv", index=False, encoding="utf-8-sig")
    print(f"\nCSV: scripts/out/_weekly_pullback_kr.csv")


if __name__ == "__main__":
    main()
