"""Daum 금융 페이지에서 JS 번들 URL 추출 → 번들 내부에서 API endpoint 패턴 찾기."""
import requests, re, sys
sys.stdout.reconfigure(encoding="utf-8")

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 Chrome/120",
    "Referer": "https://finance.daum.net/",
})

# 1) 페이지에서 JS 번들 URL 추출
r = s.get("https://finance.daum.net/domestic/investors/KOSPI", timeout=15)
print(f"page status={r.status_code}, len={len(r.text)}")
js_urls = re.findall(r'<script[^>]+src=["\']([^"\']+\.js[^"\']*)["\']', r.text)
print(f"found {len(js_urls)} JS files")
for j in js_urls[:30]:
    print(f"  {j}")

# 2) 각 JS 번들 가져와서 /api/ 패턴 추출
api_patterns = set()
for j in js_urls:
    full = j if j.startswith("http") else ("https://finance.daum.net" + j)
    try:
        rr = s.get(full, timeout=15)
        if rr.status_code != 200:
            continue
        # /api/[a-zA-Z_/{}-]+ 추출 (template literal 포함)
        for m in re.finditer(r"['\"`](/api/[a-zA-Z0-9_/${}\-]+)['\"`]", rr.text):
            api_patterns.add(m.group(1))
    except Exception:
        pass

print(f"\n=== {len(api_patterns)} API patterns found ===")
for p in sorted(api_patterns):
    low = p.lower()
    if any(k in low for k in ("invest","intra","trend","trade","hour","minute","time","market")):
        print(f"  {p}")
