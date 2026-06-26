import requests, re, sys
sys.stdout.reconfigure(encoding="utf-8")
s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.daum.net/",
    "Accept-Language": "ko-KR,ko;q=0.9",
})
r = s.get("https://finance.daum.net/domestic/investors/KOSPI", timeout=15)
print(f"status={r.status_code} len={len(r.text)}")
# 모든 URL-like 추출
keys = ("invest", "trend", "intraday", "trade", "hour", "minute", "time", "api")
seen = set()
for m in re.finditer(r"""['"]([^'"\\s<>]{8,200})['"]""", r.text):
    u = m.group(1)
    low = u.lower()
    if any(k in low for k in keys) and not u.endswith(".js"):
        if u not in seen:
            seen.add(u)
            print(f"  {u[:160]}")
