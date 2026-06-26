import pandas as pd, sys
sys.stdout.reconfigure(encoding='utf-8')
df = pd.read_parquet('data/cache/kr/279570.parquet').sort_index()
df['VOL_AMT_억'] = (df['Close'] * df['Volume']) / 1e8
df['VOL_AMT_20d평균'] = df['VOL_AMT_억'].rolling(20).mean()
df['VR_20d'] = (df['VOL_AMT_억'] / df['VOL_AMT_20d평균']) * 100
df['전일대비%'] = df['Close'].pct_change() * 100
show = df.tail(15)[['Close','전일대비%','Volume','VOL_AMT_억','VOL_AMT_20d평균','VR_20d']].copy()
show['Close'] = show['Close'].astype(int)
show['Volume'] = (show['Volume']/1e4).round(0).astype(int).map(lambda v: f'{v:,}만주')
show['VOL_AMT_억'] = show['VOL_AMT_억'].round(0).astype(int).map(lambda v: f'{v:,}억')
show['VOL_AMT_20d평균'] = show['VOL_AMT_20d평균'].round(0).astype(int).map(lambda v: f'{v:,}억')
show['VR_20d'] = show['VR_20d'].round(0).astype(int).map(lambda v: f'{v}%')
show['전일대비%'] = show['전일대비%'].map(lambda v: f'{v:+.2f}')
print(show.to_string())
