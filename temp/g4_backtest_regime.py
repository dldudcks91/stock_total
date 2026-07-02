"""G4 임계값 탐색 — regime 필터로 "하락 사이클당 1회" 카운트.

이전 버전 (temp/g4_backtest_broad.py) 은 30일 cooldown 만 두고 같은 하락 국면 안에서
여러 번 카운트 → 통계 오염. 이번엔 정통 G4 정의에 맞게 사이클당 1회.

Regime 정의:
  - 사이클 시작 = close < MA60 진입
  - 사이클 종료 = close ≥ MA60 복귀 (그 다음 재진입해야 새 사이클)
  - 사이클 안에서 slope<0 + dev ≤ percentile 를 만족하는 첫 봉만 신호

동일 유니버스 (KR 시총 상위 200 중 데이터 충분한 종목, US 시총 상위 100).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
KR_DIR = ROOT / "data" / "cache" / "kr"
US_DIR = ROOT / "data" / "cache" / "us"

MA_WIN = 60
SLOPE_WIN = 20
PCT_WIN = 756
FORWARDS = [5, 10, 20, 60]
PCTS = [0.05, 0.10]
MIN_BARS = PCT_WIN + MA_WIN

KR_TOP_N = 200
US_TOP_N = 100


def pick_universe():
    kr = pd.read_parquet(ROOT / "data/cache/kr/_live_snapshot.parquet")
    kr["mv"] = pd.to_numeric(kr["marketValue"], errors="coerce")
    kr = kr.dropna(subset=["mv"]).sort_values("mv", ascending=False)
    kr_codes = kr["itemCode"].astype(str).str.zfill(6).head(KR_TOP_N).tolist()

    us = pd.read_parquet(ROOT / "data/cache/us/_live_snapshot.parquet")
    us["mv"] = pd.to_numeric(us["marketValueRaw"], errors="coerce")
    us = us.dropna(subset=["mv"]).sort_values("mv", ascending=False)
    def is_common(sym):
        s = str(sym).upper()
        if len(s) >= 5 and s[-1] in ("R", "U", "W") and s[-2] not in "AEIOU":
            return False
        return True
    us = us[us["symbolCode"].apply(is_common)]
    us_codes = us["symbolCode"].astype(str).head(US_TOP_N).tolist()
    return kr_codes, us_codes


def load_daily(asset, sym):
    p = (KR_DIR if asset == "KR" else US_DIR) / f"{sym}.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df.columns = [c.lower() for c in df.columns]
    return df[["close"]].sort_index()


def backtest_regime(df: pd.DataFrame, pct: float) -> pd.DataFrame:
    """사이클당 1회 카운트.

    below_ma = (close < MA60) 상태. below_ma 가 False → True 로 바뀌는 순간 = 사이클 시작.
    사이클이 열려 있는 동안, 처음으로 (slope<0 & dev<=pct_thresh) 만족하는 봉이 신호.
    사이클 종료 (below_ma True → False) 되면 다음 사이클 대기.
    """
    if len(df) < MIN_BARS:
        return pd.DataFrame()
    close = df["close"].astype(float)
    ma = close.rolling(MA_WIN).mean()
    slope = ma.diff(SLOPE_WIN)
    dev = (close - ma) / ma
    pct_thresh = dev.rolling(PCT_WIN, min_periods=252).quantile(pct)
    below = close < ma
    extreme = (slope < 0) & below & (dev <= pct_thresh)

    below_arr = below.to_numpy()
    ext_arr = extreme.to_numpy()

    signals = []
    in_cycle = False
    fired_this_cycle = False
    for i in range(len(df)):
        # 사이클 상태 전이
        if below_arr[i] and not in_cycle:
            in_cycle = True
            fired_this_cycle = False
        elif not below_arr[i] and in_cycle:
            in_cycle = False
            fired_this_cycle = False
        # 사이클 안에서 첫 극단 자리만
        if in_cycle and (not fired_this_cycle) and ext_arr[i]:
            signals.append(i)
            fired_this_cycle = True

    if not signals:
        return pd.DataFrame()

    idx = df.index
    close_arr = close.to_numpy()
    rows = []
    for i in signals:
        row = {"date": idx[i], "dev": dev.iloc[i]}
        for n in FORWARDS:
            j = i + n
            row[f"ret_{n}d"] = np.nan if j >= len(close_arr) else close_arr[j] / close_arr[i] - 1
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(rets_list, asset, pct):
    if not rets_list:
        return {"자산": asset, "임계": f"하위{int(pct*100)}%", "종목수": 0, "신호수": 0}
    merged = pd.concat(rets_list, ignore_index=True)
    row = {
        "자산": asset,
        "임계": f"하위{int(pct*100)}%",
        "종목수": len(rets_list),
        "신호수": len(merged),
        "종목당신호": f"{len(merged)/len(rets_list):.1f}",
        "평균이격": f"{merged['dev'].mean()*100:.1f}%",
        "이격중앙": f"{merged['dev'].median()*100:.1f}%",
    }
    for n in FORWARDS:
        r = merged[f"ret_{n}d"].dropna()
        if r.empty:
            continue
        row[f"평균_{n}일"] = f"{r.mean()*100:+.1f}%"
        row[f"중앙_{n}일"] = f"{r.median()*100:+.1f}%"
        row[f"승률_{n}일"] = f"{(r > 0).mean()*100:.0f}%"
    return row


def top_bottom(pool, top_n=5):
    per = []
    for sym, rets in pool:
        r = rets["ret_60d"].dropna()
        if len(r) < 2:
            continue
        per.append((sym, len(rets), r.mean()*100, (r > 0).mean()*100))
    if not per:
        return None, None
    df = pd.DataFrame(per, columns=["symbol", "신호수", "60일평균%", "60일승률%"])
    df = df.sort_values("60일평균%", ascending=False)
    return df.head(top_n), df.tail(top_n).iloc[::-1]


def main():
    kr_codes, us_codes = pick_universe()
    print(f"유니버스: KR {len(kr_codes)}, US {len(us_codes)}")

    summary_rows = []
    for asset, codes in [("KR", kr_codes), ("US", us_codes)]:
        for pct in PCTS:
            pool = []
            rets_list = []
            for sym in codes:
                df = load_daily(asset, sym)
                if df.empty:
                    continue
                rets = backtest_regime(df, pct)
                if rets.empty:
                    continue
                pool.append((sym, rets))
                rets_list.append(rets)
            print(f"  [{asset} 하위{int(pct*100)}%] pool={len(pool)}, 총신호={sum(len(r) for r in rets_list)}")
            summary_rows.append(summarize(rets_list, asset, pct))

            if pct == 0.10:
                top, bot = top_bottom(pool, top_n=5)
                if top is not None:
                    print(f"\n  === {asset} 60일평균 TOP5 (10%컷) ===")
                    print(top.to_string(index=False))
                    print(f"  === {asset} 60일평균 BOTTOM5 (10%컷) ===")
                    print(bot.to_string(index=False))

    print("\n=== Regime 필터 요약 (사이클당 1회) ===")
    tbl = pd.DataFrame(summary_rows)
    with pd.option_context("display.max_columns", None, "display.width", 250):
        print(tbl.to_string(index=False))


if __name__ == "__main__":
    main()
