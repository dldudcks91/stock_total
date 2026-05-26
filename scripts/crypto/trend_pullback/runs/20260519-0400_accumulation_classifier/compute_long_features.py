"""Compute long-window features (low held + MA smooth curve) for L3 events."""
import sys, time
sys.path.insert(0, '.')
import numpy as np
import pandas as pd
from data.resample import load as load_resampled

L3_OUT = 'scripts/trend_pullback/runs/20260519-0400_accumulation_classifier/output'
ev = pd.read_parquet(f'{L3_OUT}/events_with_features.parquet')
ev = ev[ev['post_confirm_bars']==4].reset_index(drop=True)
print(f'starting events: {len(ev)}')

LB_14D_H = 14*24
LB_28D_H = 28*24

syms = ev['symbol'].unique()
print(f'caching {len(syms)} symbols 1H + 1D MA20...')
sym_h1 = {}
sym_d1_ma = {}
for sym in syms:
    h1 = load_resampled(sym, '1h')
    d1 = load_resampled(sym, '1d')
    if h1 is None or d1 is None: continue
    h1 = h1.sort_values('timestamp').reset_index(drop=True)
    d1 = d1.sort_values('timestamp').reset_index(drop=True)
    d1['ma20'] = d1['close'].rolling(20).mean()
    sym_h1[sym] = h1
    sym_d1_ma[sym] = d1
print('cached.')

rows = []
t0 = time.time()
for si, sym in enumerate(syms, 1):
    h1 = sym_h1.get(sym); d1 = sym_d1_ma.get(sym)
    if h1 is None or d1 is None: continue
    ts_h = h1['timestamp'].astype('int64').to_numpy()
    lo_h = h1['low'].astype('float64').to_numpy()
    ts_d = d1['timestamp'].astype('int64').to_numpy()
    ma_d = d1['ma20'].astype('float64').to_numpy()
    n_h = len(h1); n_d = len(d1)
    sym_ev = ev[ev['symbol']==sym]
    for _, e in sym_ev.iterrows():
        ti_h = int(np.searchsorted(ts_h, e['ts_trigger']))
        if ti_h >= n_h: continue
        trig_low_actual = float(h1.iloc[ti_h]['low'])
        end14 = min(ti_h + 1 + LB_14D_H, n_h)
        end28 = min(ti_h + 1 + LB_28D_H, n_h)
        next14_lows = lo_h[ti_h+1:end14]
        next28_lows = lo_h[ti_h+1:end28]
        min_low_pct_14d = float(next14_lows.min() / trig_low_actual - 1.0) if len(next14_lows) > 0 else np.nan
        min_low_pct_28d = float(next28_lows.min() / trig_low_actual - 1.0) if len(next28_lows) > 0 else np.nan
        low_held_14d_2pct = (min_low_pct_14d >= -0.02) if np.isfinite(min_low_pct_14d) else None
        low_held_14d_5pct = (min_low_pct_14d >= -0.05) if np.isfinite(min_low_pct_14d) else None
        low_held_28d_5pct = (min_low_pct_28d >= -0.05) if np.isfinite(min_low_pct_28d) else None
        ti_d = int(np.searchsorted(ts_d, e['ts_trigger']) - 1)
        if ti_d < 0 or ti_d >= n_d:
            ma_slope_14d = ma_slope_28d = ma_smooth_14d = ma_mono_14d = np.nan
        else:
            ma_now = ma_d[ti_d]
            t14 = ti_d + 14
            t28 = ti_d + 28
            ma_slope_14d = float(ma_d[t14] / ma_now - 1.0) if (t14 < n_d and np.isfinite(ma_now) and ma_now > 0 and np.isfinite(ma_d[t14])) else np.nan
            ma_slope_28d = float(ma_d[t28] / ma_now - 1.0) if (t28 < n_d and np.isfinite(ma_now) and ma_now > 0 and np.isfinite(ma_d[t28])) else np.nan
            ma_window = ma_d[ti_d:t14+1]
            ma_window = ma_window[np.isfinite(ma_window)]
            if len(ma_window) >= 5:
                ma_ret = np.diff(ma_window) / ma_window[:-1]
                ma_smooth_14d = float(np.std(ma_ret))
                ma_mono_14d = float((np.diff(ma_window) > 0).mean())
            else:
                ma_smooth_14d = np.nan
                ma_mono_14d = np.nan
        rows.append({
            'symbol': sym,
            'ts_trigger': int(e['ts_trigger']),
            'ts_entry': int(e['ts_entry']),
            'trigger_low_actual': trig_low_actual,
            'fwd_ret_168h': float(e['fwd_ret_168h']) if pd.notna(e['fwd_ret_168h']) else np.nan,
            'fwd_ret_672h': float(e['fwd_ret_672h']) if pd.notna(e['fwd_ret_672h']) else np.nan,
            'min_low_pct_14d': min_low_pct_14d,
            'min_low_pct_28d': min_low_pct_28d,
            'low_held_14d_2pct': low_held_14d_2pct,
            'low_held_14d_5pct': low_held_14d_5pct,
            'low_held_28d_5pct': low_held_28d_5pct,
            'ma1d_slope_change_14d': ma_slope_14d,
            'ma1d_slope_change_28d': ma_slope_28d,
            'ma1d_smoothness_14d': ma_smooth_14d,
            'ma1d_monotonic_14d': ma_mono_14d,
        })
    if si % 100 == 0:
        print(f'  {si}/{len(syms)} ({time.time()-t0:.1f}s)')

df = pd.DataFrame(rows)
df.to_parquet(f'{L3_OUT}/events_with_long_features.parquet', index=False)
print(f'\nsaved {len(df)} rows')

win_th = 0.05; lose_th = -0.05
wmask = df['fwd_ret_168h'] > win_th
lmask = df['fwd_ret_168h'] < lose_th
print(f'\nwinners (168h > +5%): {wmask.sum()}')
print(f'losers (168h < -5%): {lmask.sum()}')

feats = ['min_low_pct_14d','min_low_pct_28d','ma1d_slope_change_14d','ma1d_slope_change_28d',
         'ma1d_smoothness_14d','ma1d_monotonic_14d']
print('\n=== Winner vs Loser group means (new long-window features) ===')
rows_comp = []
for f in feats:
    w = df.loc[wmask, f].dropna()
    l = df.loc[lmask, f].dropna()
    if len(w)<30 or len(l)<30: continue
    rows_comp.append({
        'feature': f,
        'win_n': len(w), 'win_mean': w.mean(), 'win_med': w.median(),
        'lose_n': len(l), 'lose_mean': l.mean(), 'lose_med': l.median(),
        'diff_WL': w.mean() - l.mean(),
    })
cmp_df = pd.DataFrame(rows_comp).sort_values('diff_WL', key=lambda s: s.abs(), ascending=False)
cmp_df.to_csv(f'{L3_OUT}/winner_loser_long_features.csv', index=False)
print(cmp_df.to_string(index=False))

print('\n=== held=True vs False, fwd_ret_168h (and 672h) ===')
rows_h = []
for fname in ['low_held_14d_2pct','low_held_14d_5pct','low_held_28d_5pct']:
    for label, mask in [('True', df[fname]==True), ('False', df[fname]==False)]:
        s168 = df.loc[mask, 'fwd_ret_168h'].dropna()
        s672 = df.loc[mask, 'fwd_ret_672h'].dropna()
        rows_h.append({
            'feature': fname, 'group': label,
            'n168': len(s168), 'win_168h': (s168>0).mean(), 'mean_168h': s168.mean(),
            'n672': len(s672), 'win_672h': (s672>0).mean(), 'mean_672h': s672.mean(),
        })
print(pd.DataFrame(rows_h).to_string(index=False))

def qtable(df, feat, fwd):
    s = df[feat].dropna()
    if len(s) < 50: return pd.DataFrame()
    cats = pd.qcut(s, 5, duplicates='drop').astype(str)
    full = pd.Series(pd.NA, index=df.index, dtype='object')
    full.loc[s.index] = cats
    rows=[]
    for cat, idx in full.dropna().groupby(full.dropna()).indices.items():
        sub = df.loc[list(idx)]
        sf = sub[fwd].dropna()
        if len(sf)==0: continue
        rows.append({'q':cat,'n':len(sf),'mean':sf.mean(),'med':sf.median(),'win':(sf>0).mean()})
    return pd.DataFrame(rows)
for f in ['ma1d_slope_change_14d','ma1d_monotonic_14d','min_low_pct_14d','min_low_pct_28d']:
    print(f'\nQuintile {f} vs fwd_ret_168h:')
    print(qtable(df, f, 'fwd_ret_168h').to_string(index=False))
