"""
KOSPI 종목 중:
  - 월봉 MA10 의 3개월 변화율 > 0 (기울기 양수)
  - 현재 close 가 월봉 MA10 ±5% 이내 (근처)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pathlib import Path
import numpy as np
import pandas as pd

CACHE = Path("data/cache/kr")
OUT_DIR = Path("scripts/out")

WINDOW = 10
NEAR_PCT = 5.0
SLOPE_LB = 3


def main():
    listing_fp = CACHE / "_listing.csv"
    code_to_name = {}
    if listing_fp.exists():
        try:
            listing = pd.read_csv(listing_fp, dtype={"Code": str, "Symbol": str})
            for cc in ("Code", "Symbol", "종목코드"):
                if cc in listing.columns:
                    for nc in ("Name", "종목명"):
                        if nc in listing.columns:
                            code_to_name = dict(zip(
                                listing[cc].astype(str).str.zfill(6), listing[nc]))
                            break
                    break
        except Exception as e:
            print(f"listing read fail: {e}")

    rows = []
    for fp in sorted(CACHE.glob("*.parquet")):
        code = fp.stem
        if not code.isdigit() or len(code) != 6:
            continue
        df = pd.read_parquet(fp)
        if "Close" not in df.columns or len(df) < WINDOW * 21 + 30:
            continue
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        m_close = df["Close"].resample("ME").last().dropna()
        if len(m_close) < WINDOW + SLOPE_LB + 1:
            continue
        ma10 = m_close.rolling(WINDOW).mean()
        if pd.isna(ma10.iloc[-1]) or pd.isna(ma10.iloc[-SLOPE_LB - 1]):
            continue

        slope_pct = (ma10.iloc[-1] - ma10.iloc[-SLOPE_LB - 1]) / ma10.iloc[-SLOPE_LB - 1] * 100
        if slope_pct <= 0:
            continue

        close_now = float(df["Close"].iloc[-1])  # 일봉 최신
        ma10_now = float(ma10.iloc[-1])
        dist_pct = (close_now - ma10_now) / ma10_now * 100
        if abs(dist_pct) > NEAR_PCT:
            continue

        rows.append({
            "code": code,
            "name": code_to_name.get(code, ""),
            "close": close_now,
            "monthly_ma10": ma10_now,
            "dist_pct": dist_pct,
            "ma10_slope_3m_pct": slope_pct,
            "last_date": df.index[-1].strftime("%Y-%m-%d"),
            "n_months": int(len(m_close)),
        })

    df_out = pd.DataFrame(rows)
    if df_out.empty:
        print("조건 만족 종목 없음.")
        return

    # 정렬: |dist| 작은 순, slope 큰 순
    df_out["abs_dist"] = df_out["dist_pct"].abs()
    df_out = df_out.sort_values(["abs_dist", "ma10_slope_3m_pct"], ascending=[True, False]).drop(columns="abs_dist").reset_index(drop=True)

    print(f"=== KOSPI 월봉 MA10 기울기>0 + close 거리 ±{NEAR_PCT}% 이내 ===")
    print(f"총 {len(df_out)}개 종목 (전체 캐시 중)\n")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 240)
    pd.set_option("display.max_rows", None)
    print(df_out.to_string(index=False, float_format=lambda x: f"{x:+.2f}" if isinstance(x, float) and abs(x) < 100 else (f"{x:,.0f}" if isinstance(x, float) else x)))

    df_out.to_csv(OUT_DIR / "kr_monthly_ma10_near.csv", index=False)
    print(f"\nsaved → {OUT_DIR/'kr_monthly_ma10_near.csv'}")


if __name__ == "__main__":
    main()
