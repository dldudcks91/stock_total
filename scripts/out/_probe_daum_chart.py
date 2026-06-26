"""Daum chart/A005930/investors 페이지의 JS 번들에서 종목별 investor endpoint 패턴 추적."""
import requests, re, sys
sys.stdout.reconfigure(encoding="utf-8")

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://finance.daum.net/"})

# 1) 차트 페이지 자체
r = s.get("https://finance.daum.net/chart/A005930/investors", timeout=15)
print(f"chart page status={r.status_code} len={len(r.text)}")
js = re.findall(r'<script[^>]+src=["\']([^"\']+\.js[^"\']*)["\']', r.text)
print(f"JS: {len(js)}")
for j in js:
    print(f"  {j}")

# 2) 모든 bundle.js 검색
patterns = {"investor", "stock", "chart", "intraday", "times", "days", "minute"}
seen_api = set()
for j in js:
    full = j if j.startswith("http") else "https://finance.daum.net" + j
    if not full.lower().endswith(".js"):
        continue
    if "bundle" not in full.lower() and "merged" not in full.lower():
        continue
    try:
        rr = s.get(full, timeout=30)
    except Exception:
        continue
    if rr.status_code != 200:
        continue
    bundle_name = full.split("/")[-1]
    # 종목코드 또는 _SYMBOL_CODE 또는 quote 패턴
    for m in re.finditer(r"""['"`]([^'"`]*(?:investor|chart/[^'"`]+|stock|quote)[^'"`]{1,80})['"`]""", rr.text):
        u = m.group(1)
        if "/" in u and len(u) < 200 and u not in seen_api:
            if any(k in u.lower() for k in patterns):
                seen_api.add(u)

print(f"\n=== {len(seen_api)} candidates ===")
for u in sorted(seen_api):
    print(f"  {u}")
