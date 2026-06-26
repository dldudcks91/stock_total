"""케이뱅크 최근 2주 일별: 종가·등락률 + 투자자별 순매수 + 누적."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd
from dotenv import load_dotenv; load_dotenv()
from temp.fetch_krx_pension_top import krx_login, UA, DATA_URL, DATA_REFERER

ISIN = "KR7279570006"
FR, TO = "20260609", "20260623"

s = krx_login(os.getenv("KRX_ID"), os.getenv("KRX_PW"))
r = s.post(DATA_URL, data={
    "bld": "dbms/MDC/STAT/standard/MDCSTAT02303",
    "strtDd": FR, "endDd": TO, "isuCd": ISIN,
    "inqTpCd": "2", "trdVolVal": "2", "askBid": "3",
}, headers={"User-Agent":UA,"Referer":DATA_REFERER,
            "X-Requested-With":"XMLHttpRequest"}, timeout=30)
rows = r.json()["output"]
df = pd.DataFrame(rows)
df["date"] = pd.to_datetime(df["TRD_DD"].str.replace("/","-"))
for c in [f"TRDVAL{i}" for i in range(1,12)]:
    df[c] = pd.to_numeric(df[c].astype(str).str.replace(",",""), errors="coerce").fillna(0)
df = df.sort_values("date").reset_index(drop=True)
df["기관"] = df[[f"TRDVAL{i}" for i in range(1,8)]].sum(axis=1)
df["연기금"] = df["TRDVAL7"]
df["기타법인"] = df["TRDVAL8"]
df["개인"] = df["TRDVAL9"]
df["외국인"] = df["TRDVAL10"] + df["TRDVAL11"]

# 가격
px = pd.read_parquet("data/cache/kr/279570.parquet")
px.index = pd.to_datetime(px.index)
px["전일대비"] = px["Close"].pct_change() * 100

out = df.set_index("date").join(px[["Close","전일대비","Volume"]])
out["누적_기관"] = out["기관"].cumsum() / 1e8
out["누적_개인"] = out["개인"].cumsum() / 1e8
out["누적_외국인"] = out["외국인"].cumsum() / 1e8

show = pd.DataFrame({
    "일자": out.index.strftime("%m-%d"),
    "종가": out["Close"].astype(int).map(lambda x: f"{x:,}"),
    "등락률(%)": out["전일대비"].map(lambda v: f"{v:+.2f}"),
    "개인(억)": (out["개인"]/1e8).map(lambda v: f"{v:+,.0f}"),
    "기관(억)": (out["기관"]/1e8).map(lambda v: f"{v:+,.0f}"),
    "연기금(억)": (out["연기금"]/1e8).map(lambda v: f"{v:+,.0f}"),
    "외국인(억)": (out["외국인"]/1e8).map(lambda v: f"{v:+,.0f}"),
    "누적_기관": out["누적_기관"].map(lambda v: f"{v:+,.0f}"),
    "누적_개인": out["누적_개인"].map(lambda v: f"{v:+,.0f}"),
})
print(show.to_string(index=False))
