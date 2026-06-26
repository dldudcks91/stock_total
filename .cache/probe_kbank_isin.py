import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'C:\Users\user\Desktop\python_text\git\stock_total')
from dotenv import load_dotenv; load_dotenv()
from temp.fetch_krx_pension_top import krx_login, UA, DATA_URL, DATA_REFERER

s = krx_login(os.getenv('KRX_ID'), os.getenv('KRX_PW'))

# 전종목 기본정보 (상장종목 메타) — bld 후보 시도
for bld in ('dbms/MDC/STAT/standard/MDCSTAT01901',
            'dbms/MDC/STAT/issue/MDCSTAT01901',
            'dbms/MDC/STAT/standard/MDCSTAT04601'):
    r = s.post(DATA_URL, data={'bld': bld, 'mktId':'STK','share':'1'},
               headers={'User-Agent':UA,'Referer':DATA_REFERER,
                        'X-Requested-With':'XMLHttpRequest'}, timeout=30)
    try:
        j = r.json()
        out = j.get('output', j.get('OutBlock_1', []))
    except Exception:
        out = []
    print(f'bld={bld}  status={r.status_code}  rows={len(out)}')
    if out:
        # find 279570
        for row in out:
            v = ' '.join(str(x) for x in row.values())
            if '279570' in v or '케이뱅크' in v:
                print('  HIT:', row)
                break
        else:
            print('  keys sample:', list(out[0].keys()))
