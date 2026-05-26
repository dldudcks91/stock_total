"""리뷰 점수 기준 추천."""
from __future__ import annotations
import sys, warnings
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[3]))
sys.stdout.reconfigure(encoding='utf-8')
warnings.filterwarnings('ignore')
import pandas as pd

STOCK_TOKENS = {
    "AAPLUSDT","AMDUSDT","AMZNUSDT","ARMUSDT","COINUSDT","COPPERUSDT",
    "COSTUSDT","GOOGLUSDT","INTCUSDT","JDUSDT","METAUSDT","MRVLUSDT",
    "MSFTUSDT","NFLXUSDT","NVDAUSDT","QQQUSDT","SPYUSDT","TSLAUSDT","UNHUSDT",
}
STATE_MAP = {
    "A2":1.0,"B5":0.95,"A1":0.85,"B4":0.55,"B3":0.30,
    "A3":0.10,"A4":-0.30,"A5":-0.50,"B1":-0.40,"B2":-0.20,"C1":-0.50,
}
VOL_MAP = {
    "normal":0.0,"accumulation_suspect":0.30,
    "distribution_suspect":-0.40,"dry":-0.20,"pump_dump_trace":-1.0,
}
RISK_PEN = {
    "parabolic":-0.30,"pump_dump_trace":-1.0,"low_history":-0.10,
    "zombie":-0.50,"distribution_suspect":-0.30,
}

def rev_score(row) -> float:
    s = 0.0
    for tf, w in (("1m", 0.3), ("1w", 0.4), ("1d", 0.3)):
        s += STATE_MAP.get(row.get(f"state_{tf}"), 0.0) * w
        s += VOL_MAP.get(row.get(f"volume_flag_{tf}"), 0.0) * w * 0.3
    if row.get("verdict_confidence") == "high": s += 0.10
    elif row.get("verdict_confidence") == "low": s -= 0.10
    if row.get("tf_consistency") == "정합": s += 0.10
    elif row.get("tf_consistency") == "충돌": s -= 0.15
    for k, v in RISK_PEN.items():
        if k in str(row.get("risk_flags") or ""): s += v
    return s

def load_clean():
    cs = pd.read_parquet("data/cache/crypto/visual_review/coin_state.parquet")
    cs = cs[cs["last_review_date"].astype(str) == "2026-05-21"].copy()
    cs = cs[~cs["symbol"].isin(STOCK_TOKENS)]
    cs = cs[cs["verdict"] != "reject"]
    rf = cs["risk_flags"].fillna("").astype(str)
    cs = cs[~rf.str.contains("pump_dump_trace")]
    cs = cs[~rf.str.contains("zombie")]
    cs["rev_score"] = cs.apply(rev_score, axis=1)
    return cs.sort_values("rev_score", ascending=False)

def print_table(df):
    print(f"{'심볼':12s} {'점수':>5s} {'1m':>4s} {'1w':>4s} {'1d':>4s} {'micro_1d':>16s} {'vol_1d':>22s} {'tf':>4s} {'vconf':>6s}  리스크")
    print("-" * 105)
    for _, r in df.iterrows():
        risks = (str(r.get("risk_flags") or "")
                 .replace("low_history","LH").replace("drawdown_deep","DD")
                 .replace("accumulation_suspect","ACC").replace("parabolic","PAR")
                 .replace("distribution_suspect","DIST").strip(",").strip())
        print(
            f"{r['symbol']:12s} {r['rev_score']:>5.2f}"
            f" {str(r.get('state_1m','?')):>4s} {str(r.get('state_1w','?')):>4s} {str(r.get('state_1d','?')):>4s}"
            f" {str(r.get('micro_action_1d','?')):>16s} {str(r.get('volume_flag_1d','?')):>22s}"
            f" {str(r.get('tf_consistency','?')):>4s} {str(r.get('verdict_confidence','?')):>6s}  {risks}"
        )

if __name__ == "__main__":
    import sys as _sys
    cs = load_clean()
    mode = _sys.argv[1] if len(_sys.argv) > 1 else "top"

    if mode == "b45":
        filt = cs[cs["state_1w"].isin(["B4","B5"]) | cs["state_1d"].isin(["B4","B5"])]
        print(f"B4/B5 보유 심볼 ({len(filt)}개) — rev_score 내림차순\n")
        print_table(filt)
    else:
        print_table(cs.head(30))
