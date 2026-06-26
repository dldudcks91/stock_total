"""chartInvestorsBundle 안의 모든 investor / chart / api 패턴 dump."""
import requests, re, sys
sys.stdout.reconfigure(encoding="utf-8")

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://finance.daum.net/"})
url = "https://t1.daumcdn.net/media/kraken/finance/resources/dist/260605180117/chartInvestorsBundle.merged.js"
r = s.get(url, timeout=30)
text = r.text
print(f"len={len(text)}")

# 1) api/ 시작 패턴 모두
api = set()
for m in re.finditer(r"""['"`](/?api/[A-Za-z0-9_/${}.\-?=&]+)['"`]""", text):
    api.add(m.group(1))
# 2) chart/ 패턴
charts = set()
for m in re.finditer(r"""['"`](/?chart/[A-Za-z0-9_/${}.\-?=&]+)['"`]""", text):
    charts.add(m.group(1))

print(f"\napi/ patterns ({len(api)}):")
for p in sorted(api):
    print(f"  {p}")
print(f"\nchart/ patterns ({len(charts)}):")
for p in sorted(charts):
    print(f"  {p}")

# 3) 'investor' 단어 주변 코드 일부
print("\ninvestor context (top 15):")
seen = set()
for m in re.finditer(r"(?i)investor", text):
    s_idx = max(0, m.start() - 40); e_idx = min(len(text), m.end() + 150)
    sn = text[s_idx:e_idx].replace("\n", " ")[:200]
    if sn not in seen:
        seen.add(sn)
        if any(k in sn.lower() for k in ("api", "url", "fetch", "path", "/")):
            print(f"  ...{sn}...")
            if len(seen) > 15:
                break
