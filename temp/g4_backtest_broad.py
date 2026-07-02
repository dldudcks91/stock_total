"""G4 임계값 탐색 — KR 시총 상위 200 / US 시총 상위 100 확장 백테스트.

동일 룰 (일봉 MA60, slope 20 −, close < MA60, deviation 하위 5%/10% percentile, cooldown 30일).
직전 sample 5종목/자산 → 확장 sample 로 통계 신뢰도 확보 목적.
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
COOLDOWN = 30
PCTS = [0.05, 0.10]
MIN_BARS = PCT_WIN + MA_WIN  # 최소 데이터

# 유니버스 크기
KR_TOP_N = 200
US_TOP_N = 100


def pick_universe():
    """시총 상위 유니버스 선정."""
    kr = pd.read_parquet(ROOT / "data/cache/kr/_live_snapshot.parquet")
    kr["mv"] = pd.to_numeric(kr["marketValue"], errors="coerce")
    kr = kr.dropna(subset=["mv"]).sort_values("mv", ascending=False)
    kr_codes = kr["itemCode"].astype(str).str.zfill(6).head(KR_TOP_N).tolist()

    us = pd.read_parquet(ROOT / "data/cache/us/_live_snapshot.parquet")
    us["mv"] = pd.to_numeric(us["marketValueRaw"], errors="coerce")
    us = us.dropna(subset=["mv"]).sort_values("mv", ascending=False)
    # SPAC/warrant/unit/rights 제외 (심볼 뒷자리 R, U, W 로 흔히 끝남)
    def is_common_stock(sym: str) -> bool:
        s = str(sym).upper()
        if len(s) >= 5 and s[-1] in ("R", "U", "W") and s[-2] not in "AEIOU":
            return False
        return True
    us = us[us["symbolCode"].apply(is_common_stock)]
    us_codes = us["symbolCode"].astype(str).head(US_TOP_N).tolist()
    return kr_codes, us_codes


def load_kr(sym: str) -> pd.DataFrame:
    p = KR_DIR / f"{sym}.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df.columns = [c.lower() for c in df.columns]
    return df[["close"]].sort_index()


def load_us(sym: str) -> pd.DataFrame:
    p = US_DIR / f"{sym}.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df.columns = [c.lower() for c in df.columns]
    return df[["close"]].sort_index()


def backtest(df: pd.DataFrame, pct: float) -> pd.DataFrame:
    if len(df) < MIN_BARS:
        return pd.DataFrame()
    close = df["close"].astype(float)
    ma = close.rolling(MA_WIN).mean()
    slope = ma.diff(SLOPE_WIN)
    dev = (close - ma) / ma
    pct_thresh = dev.rolling(PCT_WIN, min_periods=252).quantile(pct)
    cond = (slope < 0) & (close < ma) & (dev <= pct_thresh)

    signals = []
    last_i = -10**9
    cond_arr = cond.to_numpy()
    for i in range(len(df)):
        if not cond_arr[i]:
            continue
        if i - last_i < COOLDOWN:
            continue
        signals.append(i)
        last_i = i
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


def summarize_pool(rets_list, asset, pct):
    """자산 × 임계 그룹 요약 (분포 통계 포함)."""
    if not rets_list:
        return {"자산": asset, "임계": f"하위{int(pct*100)}%", "종목수": 0, "신호수": 0}
    merged = pd.concat(rets_list, ignore_index=True)
    row = {
        "자산": asset,
        "임계": f"하위{int(pct*100)}%",
        "종목수": len(rets_list),
        "신호수": len(merged),
        "평균이격": f"{merged['dev'].mean()*100:.1f}%",
        "이격중앙": f"{merged['dev'].median()*100:.1f}%",
    }
    for n in FORWARDS:
        r = merged[f"ret_{n}d"].dropna()
        if r.empty:
            for suffix in ("평균", "중앙", "승률"):
                row[f"{suffix}_{n}일"] = "-"
            continue
        row[f"평균_{n}일"] = f"{r.mean()*100:+.1f}%"
        row[f"중앙_{n}일"] = f"{r.median()*100:+.1f}%"
        row[f"승률_{n}일"] = f"{(r > 0).mean()*100:.0f}%"
    return row


def top_bottom_per_symbol(pool, pct, asset, top_n=5):
    """자산-임계별 종목별 60일 평균수익 top/bottom."""
    per_sym = []
    for sym, rets in pool:
        r = rets["ret_60d"].dropna()
        if len(r) < 3:
            continue
        per_sym.append((sym, len(rets), r.mean()*100, (r > 0).mean()*100))
    if not per_sym:
        return None, None
    df = pd.DataFrame(per_sym, columns=["symbol", "신호수", "60일평균%", "60일승률%"])
    df = df.sort_values("60일평균%", ascending=False)
    return df.head(top_n), df.tail(top_n).iloc[::-1]


def main():
    kr_codes, us_codes = pick_universe()
    print(f"유니버스: KR {len(kr_codes)}, US {len(us_codes)}")

    summary_rows = []
    for asset, codes, loader in [("KR", kr_codes, load_kr), ("US", us_codes, load_us)]:
        for pct in PCTS:
            pool = []       # (sym, rets)
            rets_list = []
            skipped = 0
            for sym in codes:
                df = loader(sym)
                if df.empty:
                    skipped += 1
                    continue
                rets = backtest(df, pct)
                if rets.empty:
                    continue
                pool.append((sym, rets))
                rets_list.append(rets)
            print(f"  [{asset} 하위{int(pct*100)}%] pool={len(pool)}, skipped={skipped}")
            summary_rows.append(summarize_pool(rets_list, asset, pct))

            # 종목별 top/bottom (10% 컷 기준으로 한 번만 출력)
            if pct == 0.10:
                top, bot = top_bottom_per_symbol(pool, pct, asset, top_n=5)
                if top is not None:
                    print(f"\n  === {asset} 60일평균 TOP5 (10%컷) ===")
                    print(top.to_string(index=False))
                    print(f"  === {asset} 60일평균 BOTTOM5 (10%컷) ===")
                    print(bot.to_string(index=False))

    print("\n=== 확장 백테스트 요약 ===")
    tbl = pd.DataFrame(summary_rows)
    with pd.option_context("display.max_columns", None, "display.width", 250):
        print(tbl.to_string(index=False))


if __name__ == "__main__":
    main()
