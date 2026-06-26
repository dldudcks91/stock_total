"""기관(7050) + 연기금의 누적 보유 추정 — 매수일 평균 단가 계산."""
import os, sys, pandas as pd
from pathlib import Path
sys.path.insert(0, r'C:\Users\user\Desktop\python_text\git\stock_total')
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv; load_dotenv()
from temp.fetch_krx_pension_top import krx_login, UA, DATA_URL, DATA_REFERER

s = krx_login(os.getenv('KRX_ID'), os.getenv('KRX_PW'))

# 일별 거래대금 (askBid=3 순매수, trdVolVal=2)
def fetch_daily(askbid, trdvolval):
    r = s.post(DATA_URL, data={
        'bld': 'dbms/MDC/STAT/standard/MDCSTAT02303',
        'strtDd':'20260305','endDd':'20260624','isuCd':'KR7279570006',
        'inqTpCd':'2','trdVolVal':str(trdvolval),'askBid':str(askbid),
    }, headers={'User-Agent':UA,'Referer':DATA_REFERER,
                'X-Requested-With':'XMLHttpRequest'}, timeout=30)
    out = r.json()['output']
    df = pd.DataFrame(out)
    df['date'] = pd.to_datetime(df['TRD_DD'].str.replace('/','-'))
    for c in [f'TRDVAL{i}' for i in range(1,12)]:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(',',''), errors='coerce').fillna(0)
    return df.sort_values('date').reset_index(drop=True)

# 3=순매수, 2=매수 only, 1=매도 only
net_val = fetch_daily(3, 2)   # 순매수 거래대금
net_vol = fetch_daily(3, 1)   # 순매수 거래량
buy_val = fetch_daily(2, 2)   # 매수 거래대금
buy_vol = fetch_daily(2, 1)   # 매수 거래량

# 기관 = TRDVAL1+...+TRDVAL7, 연기금 = TRDVAL7
def inst_col(df, cols):
    return df[cols].sum(axis=1)

# 매수 누적 (기관/연기금) - 매수만
inst_buy_val = inst_col(buy_val, [f'TRDVAL{i}' for i in range(1,8)]).sum()
inst_buy_vol = inst_col(buy_vol, [f'TRDVAL{i}' for i in range(1,8)]).sum()
pension_buy_val = buy_val['TRDVAL7'].sum()
pension_buy_vol = buy_vol['TRDVAL7'].sum()

# 매도 누적 (기관/연기금)
sell_val = fetch_daily(1, 2)
sell_vol = fetch_daily(1, 1)
inst_sell_val = inst_col(sell_val, [f'TRDVAL{i}' for i in range(1,8)]).sum()
inst_sell_vol = inst_col(sell_vol, [f'TRDVAL{i}' for i in range(1,8)]).sum()
pension_sell_val = sell_val['TRDVAL7'].sum()
pension_sell_vol = sell_vol['TRDVAL7'].sum()

print(f'\n===== 상장후 누적 (2026-03-05~06-24) =====')
print(f'기관: 매수 {inst_buy_val/1e8:,.0f}억 / {inst_buy_vol/1e4:,.0f}만주 -- 매도 {inst_sell_val/1e8:,.0f}억 / {inst_sell_vol/1e4:,.0f}만주')
print(f'  → 매수 평단: {inst_buy_val/inst_buy_vol:,.0f}원 / 매도 평단: {inst_sell_val/inst_sell_vol if inst_sell_vol else 0:,.0f}원')
print(f'  → 순매수: {(inst_buy_val-inst_sell_val)/1e8:+,.0f}억 / {(inst_buy_vol-inst_sell_vol)/1e4:+,.0f}만주')
print(f'  → 순매수 평단 (들고있는 단가 추정): {(inst_buy_val-inst_sell_val)/(inst_buy_vol-inst_sell_vol):,.0f}원')

print(f'\n연기금: 매수 {pension_buy_val/1e8:,.0f}억 / {pension_buy_vol/1e4:,.0f}만주')
print(f'  → 매수 평단: {pension_buy_val/pension_buy_vol:,.0f}원')

# 매수만 한 구간의 평단 (적극매수 모드: 06-10~06-19)
mask = (buy_val['date'] >= '2026-06-10') & (buy_val['date'] <= '2026-06-19')
inst_buy_val_active = inst_col(buy_val[mask], [f'TRDVAL{i}' for i in range(1,8)]).sum()
inst_buy_vol_active = inst_col(buy_vol[mask], [f'TRDVAL{i}' for i in range(1,8)]).sum()
print(f'\n=== 적극매수 구간 (06-10~06-19, Markup) 기관 평단 ===')
print(f'  매수: {inst_buy_val_active/1e8:,.0f}억 / {inst_buy_vol_active/1e4:,.0f}만주')
print(f'  평단: {inst_buy_val_active/inst_buy_vol_active:,.0f}원')

# 현재가 대비
print(f'\n=== 현재 가격 5,850원 기준 ===')
held_avg = (inst_buy_val-inst_sell_val)/(inst_buy_vol-inst_sell_vol)
print(f'  기관 들고있는 단가 추정: {held_avg:,.0f}원')
print(f'  현재 5,850 vs 기관 평단: {(5850/held_avg-1)*100:+.2f}%')
