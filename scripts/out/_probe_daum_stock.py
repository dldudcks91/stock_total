"""Daum 종목 상세 페이지에서 투자자별 endpoint 패턴 추출."""
import requests, re, sys
sys.stdout.reconfigure(encoding="utf-8")

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/120", "Referer": "https://finance.daum.net/"})
r = s.get("https://finance.daum.net/quotes/A005930", timeout=15)
print(f"page status={r.status_code} len={len(r.text)}")
js_urls = re.findall(r'<script[^>]+src=["\']([^"\']+\.js[^"\']*)["\']', r.text)
print(f"found {len(js_urls)} JS files")
for j in js_urls:
    print(f"  {j}")
print()

# stock 관련 bundle 추정 → 모든 번들에서 investor 패턴
for j in js_urls:
    full = j if j.startswith("http") else ("https://finance.daum.net" + j)
    if "bundle" not in full.lower():
        continue
    try:
        rr = s.get(full, timeout=20)
    except Exception:
        continue
    if rr.status_code != 200:
        continue
    print(f"\n--- {j.split('/')[-1]} ({len(rr.text)} bytes) ---")
    # investor 관련 endpoint 패턴
    pat = re.compile(r"['\"`]([^'\"`]*(?:investor|invest)[^'\"`]*)['\"`]", re.IGNORECASE)
    seen = set()
    for m in pat.finditer(rr.text):
        u = m.group(1)
        if "/" in u and len(u) < 200:
            if u not in seen:
                seen.add(u)
                print(f"  {u}")
                if len(seen) > 50:
                    break
