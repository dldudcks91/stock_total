import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'C:\Users\user\Desktop\python_text\git\stock_total')
from dotenv import load_dotenv; load_dotenv()
from temp.fetch_krx_pension_top import krx_login, UA, DATA_URL, DATA_REFERER

s = krx_login(os.getenv('KRX_ID'), os.getenv('KRX_PW'))

# 일별 상세 (12주체) — MDCSTAT02303
r = s.post(DATA_URL, data={
    'bld': 'dbms/MDC/STAT/standard/MDCSTAT02303',
    'strtDd': '20260601', 'endDd': '20260605',
    'isuCd': 'KR7279570006',
    'inqTpCd': '2', 'trdVolVal': '2', 'askBid': '3',
}, headers={'User-Agent':UA,'Referer':DATA_REFERER,'X-Requested-With':'XMLHttpRequest'}, timeout=30)
j = r.json()
out = j.get('output', [])
print('rows:', len(out))
if out:
    print('keys:', list(out[0].keys()))
    print(json.dumps(out[0], ensure_ascii=False, indent=2))
    # 02302 일반 4주체와 매칭 위해 마지막 행도
    print(json.dumps(out[-1], ensure_ascii=False, indent=2))
