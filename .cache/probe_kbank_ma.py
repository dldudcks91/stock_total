import pandas as pd, sys
sys.stdout.reconfigure(encoding='utf-8')
df = pd.read_parquet('data/cache/kr/279570.parquet').sort_index()
for n in (5,10,20,50):
    df[f'MA{n}'] = df['Close'].rolling(n).mean()
print('최근 12영업일:')
print(df.tail(12)[['Close','MA5','MA10','MA20','MA50']].round(0).astype('Int64'))
print('\n상장 후 분포:')
print(df['Close'].describe().round(0))
print('\n최근 30일 High/Low:', int(df['High'].tail(30).max()), int(df['Low'].tail(30).min()))
last = df.iloc[-1]
print(f'\n마지막 ({df.index[-1].date()}) Close={int(last.Close):,} '
      f'MA10={int(last.MA10):,} MA20={int(last.MA20):,} MA50={int(last.MA50):,}')
print(f'5,850 위치 vs MA10: {(5850/last.MA10-1)*100:+.2f}%, '
      f'vs MA20: {(5850/last.MA20-1)*100:+.2f}%, '
      f'vs MA50: {(5850/last.MA50-1)*100:+.2f}%')
