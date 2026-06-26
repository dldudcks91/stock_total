"""Daum 'domesticInvestorsBundle' JS 안의 API URL 추출."""
import requests, re, sys
sys.stdout.reconfigure(encoding="utf-8")

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/120", "Referer": "https://finance.daum.net/"})
url = "https://t1.daumcdn.net/media/kraken/finance/resources/dist/260605180117/domesticInvestorsBundle.merged.js"
r = s.get(url, timeout=30)
print(f"status={r.status_code} len={len(r.text)}")
text = r.text

# /api/ 시작 URL 추출 — 따옴표 안에 있는 경로
pat = re.compile(r"""['"`](/api/[A-Za-z0-9_/${}.\-?=&]+)['"`]""")
api = set(pat.findall(text))
print(f"API patterns: {len(api)}")
for p in sorted(api):
    print(f"  {p}")

# investor 관련 단어 주변
print("\n=== investor 단어 주변 컨텍스트 ===")
seen = set()
for m in re.finditer(r"(?i)investor", text):
    s_idx = max(0, m.start() - 60); e_idx = min(len(text), m.end() + 200)
    sn = text[s_idx:e_idx].replace("\n", " ").replace("  ", " ")
    if sn not in seen:
        seen.add(sn)
        # api 또는 url 키워드 포함된 것만
        if any(k in sn.lower() for k in ("api", "url", "fetch", "/")):
            print(f"  ...{sn[:280]}...")
            if len(seen) > 30:
                break
