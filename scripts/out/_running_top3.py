"""Running-dedup TOP N (한 번 나온 심볼 이후 시각에 제외) — 1회성 분석."""
import sys
sys.path.insert(0, '.')
import pandas as pd
from scripts.crypto._common.mtf_recs import compute_score_matrix


def running_unique_top_n(score_df: pd.DataFrame, n: int = 3, min_score: float = 1.0,
                         reset_hours: int = 8):
    """매 reset_hours KST 마다 seen 초기화. 기본 8h (KST 00/08/16시 reset)."""
    seen = set()
    last_bucket = None
    rows = []
    for ts in score_df.index:   # 오래된 → 최신 (UTC naive)
        ts_kst = ts + pd.Timedelta(hours=9)
        # KST 기준 reset 버킷 — 자정부터 reset_hours 단위
        bucket = (ts_kst.normalize(), ts_kst.hour // reset_hours)
        if bucket != last_bucket:
            seen = set()
            last_bucket = bucket
        row = score_df.loc[ts].dropna()
        row = row[row >= min_score].sort_values(ascending=False)
        picks = []
        for sym in row.index:
            if sym in seen:
                continue
            picks.append(sym)
            seen.add(sym)
            if len(picks) >= n:
                break
        rows.append({'ts': ts_kst.strftime('%m-%d %H:%M'),
                     **{f'#{i+1}': (picks[i] if i < len(picks) else '') for i in range(n)}})
    return pd.DataFrame(rows)


def main():
    df = pd.read_parquet('data/cache/crypto/1h/BTCUSDT.parquet')
    end_ts = pd.to_datetime(df['timestamp'].iloc[-1], unit='ms', utc=True).tz_localize(None).floor('1h')
    hours = 95  # 05-23 00:00 KST → 05-26 22:00 KST
    mats = compute_score_matrix(end_ts, hours=hours, workers=6)

    for name in ('chase', 'pullback'):
        tbl = running_unique_top_n(mats[name], n=3)
        out = f'scripts/out/_running_top3_{name}.csv'
        tbl.to_csv(out, index=False, encoding='utf-8-sig')
        print(f'\n## {name.upper()} TOP 3 (running dedup, from 05-23 00:00 KST)\n')
        print('| 시각 | #1 | #2 | #3 |')
        print('|---|---|---|---|')
        for _, r in tbl.iterrows():
            print(f'| {r["ts"]} | {r["#1"]} | {r["#2"]} | {r["#3"]} |')
        print(f'\nsaved: {out}')


if __name__ == '__main__':
    main()
