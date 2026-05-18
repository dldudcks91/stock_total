"""Round 2 — BTC 추세 필터.

같은 시그널을 BTC 시장 환경별로 분리:
  - regime_ema200: BTC 1d close > EMA200 (강세) vs <= (약세)
  - regime_vol:    BTC 30d realized vol  상위 50% (고변동) vs 하위 (저변동)

시그널: trend_chase 1d (Round 1 best: th=60), trend_pullback 1d (th=70)
청산: Round 1 best 룰

산출:
  scripts/out/optimize/round2/crypto/task3_btc_filter.csv
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import trend_chase, trend_pullback  # noqa: E402
from scripts.optimize_grid import ExitRule, simulate  # noqa: E402
from scripts.optimize.crypto_groups import load_1d  # noqa: E402

CACHE_1D = ROOT / "data" / "cache" / "crypto" / "1d"
OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "round2" / "crypto"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NOW = pd.Timestamp.utcnow().tz_localize(None).normalize()
SINCE_YEARS = 3
SINCE = NOW - pd.DateOffset(years=SINCE_YEARS)
COST = 0.002

EXIT_RULE = ExitRule("hold_60d_trail20_TP30", max_hold=60, trailing_pct=0.20, take_profit_pct=0.30)


def build_btc_regime() -> pd.DataFrame:
    btc = load_1d(CACHE_1D / "BTCUSDT.parquet")
    close = btc["close"].astype("float64")
    ema200 = close.ewm(span=200, adjust=False).mean()
    above = close > ema200
    ret = close.pct_change()
    vol30 = ret.rolling(30).std() * np.sqrt(365)
    vol_med = vol30.median()
    high_vol = vol30 > vol_med
    out = pd.DataFrame({
        "above_ema200": above.astype("int8"),
        "high_vol": high_vol.astype("int8"),
    })
    out.to_csv(OUT_DIR / "task3_btc_regime.csv", encoding="utf-8-sig")
    print(f"[btc_regime] above_ema200 share: {above.mean():.2f}, "
          f"high_vol share: {high_vol.mean():.2f}", flush=True)
    return out


def summarize(rets: np.ndarray, years: float) -> dict:
    if len(rets) == 0:
        return {"n": 0, "win%": 0, "mean%": 0, "Sharpe_ann": 0, "PF": 0}
    win = float((rets > 0).mean() * 100)
    mean = float(rets.mean() * 100)
    if rets.std() > 0:
        sharpe = float(rets.mean() / rets.std() * np.sqrt(len(rets) / years))
    else:
        sharpe = 0.0
    gains = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = float(gains / losses) if losses > 0 else 99.99
    return {"n": len(rets), "win%": round(win, 1), "mean%": round(mean, 2),
            "Sharpe_ann": round(sharpe, 2), "PF": round(pf, 2)}


def main():
    regime = build_btc_regime()
    # 시그널 cache
    files = sorted(CACHE_1D.glob("*.parquet"))
    print(f"[load] {len(files)} 1d files", flush=True)
    per_sym = {}
    t0 = time.time()
    for i, p in enumerate(files):
        try:
            df = load_1d(p)
        except Exception:
            continue
        if df.empty or len(df) < 80:
            continue
        df_r = df.reset_index(drop=True)
        try:
            sc_c = trend_chase.score(df_r, {}).to_numpy().astype("float32")
            sc_p = trend_pullback.score(df_r, {}).to_numpy().astype("float32")
        except Exception:
            continue
        close = df["close"].astype("float64").to_numpy()
        in_period = np.asarray(df.index >= SINCE)
        per_sym[p.stem] = (close, sc_c, sc_p, in_period, df.index)
        if (i + 1) % 100 == 0:
            print(f"  scored {i+1}/{len(files)} ({time.time()-t0:.1f}s)", flush=True)
    print(f"[load] {len(per_sym)} scored", flush=True)

    # 각 시그널 진입을 (regime) tag 와 함께 누적
    SIGNALS = [("trend_chase", 1, 60), ("trend_pullback", 2, 70),
               ("trend_chase", 1, 70), ("trend_pullback", 2, 80)]
    bucket_rets: dict[tuple, list[float]] = {}
    for sym, (close, sc_c, sc_p, in_period, idx) in per_sym.items():
        # regime lookup: align by index
        try:
            r = regime.reindex(idx).fillna(method="ffill")
        except Exception:
            continue
        above = r["above_ema200"].to_numpy().astype("int8")
        hv = r["high_vol"].to_numpy().astype("int8")
        for strat_name, k, th in SIGNALS:
            sc = sc_c if k == 1 else sc_p
            sig01 = (sc >= float(th)).astype("int8")
            diff = np.diff(sig01.astype("int16"), prepend=0)
            enter_mask = (diff == 1) & in_period
            positions = np.where(enter_mask)[0]
            for pos in positions:
                if pos >= len(close) - 1:
                    continue
                exit_pos, gross = simulate(close, int(pos), EXIT_RULE)
                if exit_pos == pos:
                    continue
                net = gross - COST
                a = int(above[pos]) if pos < len(above) else 0
                v = int(hv[pos]) if pos < len(hv) else 0
                for key in [
                    (strat_name, th, "all", "all"),
                    (strat_name, th, f"ema200={'above' if a else 'below'}", "all"),
                    (strat_name, th, "all", f"vol={'high' if v else 'low'}"),
                    (strat_name, th, f"ema200={'above' if a else 'below'}", f"vol={'high' if v else 'low'}"),
                ]:
                    bucket_rets.setdefault(key, []).append(net)

    rows = []
    for key, rets in bucket_rets.items():
        strat, th, ema, vol = key
        rows.append({"strategy": strat, "score_th": th,
                     "ema200_filter": ema, "vol_filter": vol,
                     **summarize(np.array(rets), SINCE_YEARS)})
    out = pd.DataFrame(rows).sort_values(["strategy", "score_th", "ema200_filter", "vol_filter"])
    out.to_csv(OUT_DIR / "task3_btc_filter.csv", index=False, encoding="utf-8-sig")
    print(f"saved: {OUT_DIR / 'task3_btc_filter.csv'}", flush=True)
    print("\n=== top buckets (Sharpe) ===")
    print(out.sort_values("Sharpe_ann", ascending=False).head(20).to_string(index=False))


if __name__ == "__main__":
    main()
