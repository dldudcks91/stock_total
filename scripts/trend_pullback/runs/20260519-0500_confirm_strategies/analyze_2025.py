"""2025+ slice + head-to-head comparison."""
import pandas as pd, numpy as np
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
CUTOFF = int(datetime(2025,1,1,tzinfo=KST).timestamp()*1000)
OUT = 'scripts/trend_pullback/runs/20260519-0500_confirm_strategies/output'

horizons = [4, 24, 72, 168, 336, 672]

def stats(s):
    s = s.dropna()
    if len(s)==0: return None
    return {'n':len(s),'mean':s.mean(),'median':s.median(),'win':(s>0).mean()}

def horizon_curve(df, label):
    if df.empty: return pd.DataFrame()
    rows=[]
    for h in horizons:
        col = f'fwd_ret_{h}h'
        if col not in df.columns: continue
        st = stats(df[col])
        if st: rows.append({'strategy':label, 'h':h, **st})
    return pd.DataFrame(rows)

# Load each
A = pd.read_parquet(f'{OUT}/events_A.parquet')
B = pd.read_parquet(f'{OUT}/events_B.parquet')
C = pd.read_parquet(f'{OUT}/events_C.parquet')
D = pd.read_parquet(f'{OUT}/events_D.parquet')
E = pd.read_parquet(f'{OUT}/events_E.parquet')

# 2025+ slices
A25 = A[A['ts_entry']>=CUTOFF].copy()
B25 = B[B['ts_entry']>=CUTOFF].copy()
C25 = C[C['ts_entry']>=CUTOFF].copy()
D25 = D[D['ts_entry']>=CUTOFF].copy()
E25 = E[E['ts_entry']>=CUTOFF].copy()

print('=== 2025+ counts per strategy ===')
print(f'  A: {len(A25)}  B: {len(B25)}  C: {len(C25)}  D: {len(D25)}  E: {len(E25)}')

# Per combo summaries (2025+) for each strategy
def summarize_with_combo(df, key_cols, label):
    if df.empty: return pd.DataFrame()
    rows=[]
    for keys, grp in df.groupby(key_cols, observed=True):
        kd = dict(zip(key_cols, keys if isinstance(keys, tuple) else (keys,)))
        for h in horizons:
            col = f'fwd_ret_{h}h'
            if col not in grp.columns: continue
            s = grp[col].dropna()
            if len(s)==0: continue
            rows.append({'strategy':label, **kd, 'h':h, 'n':len(s),
                          'mean':s.mean(), 'median':s.median(),
                          'win':(s>0).mean()})
    return pd.DataFrame(rows)

sA25 = summarize_with_combo(A25, ['A_n_bars','A_tolerance'], 'A')
sB25 = summarize_with_combo(B25, ['B_timeout_h'], 'B')
sC25 = summarize_with_combo(C25, ['C_n_bars'], 'C')
sD25 = summarize_with_combo(D25, ['D_n_bars'], 'D')
sE25 = summarize_with_combo(E25, ['E_max_days'], 'E')
all25 = pd.concat([sA25,sB25,sC25,sD25,sE25], ignore_index=True)
all25.to_csv(f'{OUT}/summary_2025plus.csv', index=False)

print('\n=== 2025+ @ 24h, sorted by win desc ===')
sub = all25[all25.h==24].copy()
sub['combo'] = sub.apply(lambda r: ' '.join(f'{k}={v}' for k,v in r.items()
                                              if k in ('A_n_bars','A_tolerance','B_timeout_h','C_n_bars','D_n_bars','E_max_days') and pd.notna(v)), axis=1)
print(sub[['strategy','combo','n','mean','median','win']].sort_values('win', ascending=False).to_string(index=False))

print('\n=== 2025+ @ 168h, sorted by win desc ===')
sub = all25[all25.h==168].copy()
sub['combo'] = sub.apply(lambda r: ' '.join(f'{k}={v}' for k,v in r.items()
                                              if k in ('A_n_bars','A_tolerance','B_timeout_h','C_n_bars','D_n_bars','E_max_days') and pd.notna(v)), axis=1)
print(sub[['strategy','combo','n','mean','median','win']].sort_values('win', ascending=False).to_string(index=False))

print('\n=== 2025+ @ 672h, sorted by win desc ===')
sub = all25[all25.h==672].copy()
sub['combo'] = sub.apply(lambda r: ' '.join(f'{k}={v}' for k,v in r.items()
                                              if k in ('A_n_bars','A_tolerance','B_timeout_h','C_n_bars','D_n_bars','E_max_days') and pd.notna(v)), axis=1)
print(sub[['strategy','combo','n','mean','median','win']].sort_values('win', ascending=False).to_string(index=False))

# Best combo per strategy at 168h
print('\n=== Best combo per strategy @ 168h (2025+) ===')
all25_168 = all25[all25.h==168]
best_rows = []
for s, grp in all25_168.groupby('strategy'):
    best = grp.sort_values('win', ascending=False).iloc[0]
    best_rows.append(best.to_dict())
print(pd.DataFrame(best_rows).to_string(index=False))

# Same for all years
all_all = pd.concat([
    summarize_with_combo(A, ['A_n_bars','A_tolerance'], 'A'),
    summarize_with_combo(B, ['B_timeout_h'], 'B'),
    summarize_with_combo(C, ['C_n_bars'], 'C'),
    summarize_with_combo(D, ['D_n_bars'], 'D'),
    summarize_with_combo(E, ['E_max_days'], 'E'),
], ignore_index=True)
print('\n=== Best combo per strategy @ 168h (ALL years) ===')
best_rows = []
for s, grp in all_all[all_all.h==168].groupby('strategy'):
    best = grp.sort_values('win', ascending=False).iloc[0]
    best_rows.append(best.to_dict())
print(pd.DataFrame(best_rows).to_string(index=False))
