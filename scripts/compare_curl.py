"""U자 곡률 조건 ON/OFF 비교.

use_curl=False (기존) vs use_curl=True (신규) 두 가지로 exit_grid 결과를 자산별로 측정.
KR/US: hold_52w_TP30_trail20, Crypto: hold_13w_trail15_cut1 만 사용 (1차 최적 룰).
"""
from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import asdict

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.strategies import ma_slope_turn_up  # noqa: E402
from scripts.count_slope_turn_signals import (  # noqa: E402
    load_crypto_weekly, load_stock_weekly, crypto_symbol_from_file,
    CRYPTO_1H_DIR, KR_DIR, US_DIR, SINCE, SINCE_YEARS,
)
from scripts.forward_returns_top200 import (  # noqa: E402
    kr_top_universe, us_top_universe, crypto_top_universe,
)
from scripts.exit_rule_grid import (  # noqa: E402
    ExitRule, simulate, summarize, COST_RT,
)


def collect(asset, files, loader, universe, rule, cost_rt, strategy_params):
    trades = []
    for p in files:
        symbol = crypto_symbol_from_file(p) if asset == "crypto" else p.stem
        if symbol not in universe:
            continue
        try:
            df_w = loader(p)
            if df_w is None or df_w.empty or len(df_w) < 120:
                continue
            sig = ma_slope_turn_up.signal(df_w.reset_index(drop=True), strategy_params)
            sig.index = df_w.index
            entries = (sig.diff() == 1) & (df_w.index >= SINCE)
            close = df_w["close"].to_numpy()
            low = df_w["low"].to_numpy() if "low" in df_w.columns else close
            ma_f = pd.Series(close).rolling(10).mean()
            ma_s = pd.Series(close).rolling(20).mean()
            slope_neg = ((ma_f.diff() < 0) | (ma_s.diff() < 0)).to_numpy()
            for pos in np.where(entries.to_numpy())[0]:
                exit_pos, gross_ret = simulate(close, low, pos, slope_neg, rule)
                trades.append({
                    "asset": asset, "symbol": symbol,
                    "entry_dt": df_w.index[pos].date().isoformat(),
                    "held_weeks": exit_pos - pos,
                    "gross_ret_%": gross_ret * 100,
                    "net_ret_%": (gross_ret - cost_rt) * 100,
                })
        except Exception:
            continue
    return trades


def main():
    kr_uni = kr_top_universe()
    us_uni = us_top_universe()
    cr_uni = crypto_top_universe()
    kr_files = [p for p in sorted(KR_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    us_files = [p for p in sorted(US_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    cr_files = sorted(CRYPTO_1H_DIR.glob("*.parquet"))

    rules = {
        "crypto": ExitRule("hold_13w_trail15_cut1", max_hold=13, trailing_pct=0.15, cut_1w_neg=True, slope_exit=False),
        "kr":     ExitRule("hold_52w_TP30_trail20", max_hold=52, trailing_pct=0.20, take_profit_pct=0.30, slope_exit=False),
        "us":     ExitRule("hold_52w_TP30_trail20", max_hold=52, trailing_pct=0.20, take_profit_pct=0.30, slope_exit=False),
    }

    variants = [
        ("curl_OFF",                {"use_curl": False}),
        # a>0 단독 (R² 0, accel_streak 1로 사실상 끔) — "MA가 위로 휘기만 하면 됨"
        ("a_only",                  {"use_curl": True, "curl_r2_min": 0.0,  "curl_window": 8,  "curl_accel_streak": 1}),
        # a>0 + R²만
        ("a_r2_0.70",               {"use_curl": True, "curl_r2_min": 0.70, "curl_window": 8,  "curl_accel_streak": 1}),
        ("a_r2_0.80",               {"use_curl": True, "curl_r2_min": 0.80, "curl_window": 8,  "curl_accel_streak": 1}),
        ("a_r2_0.85",               {"use_curl": True, "curl_r2_min": 0.85, "curl_window": 8,  "curl_accel_streak": 1}),
        # accel_streak만 (다항식 fit 없이, accel N봉 연속 양)
        ("accel_streak_3",          {"use_curl": True, "curl_r2_min": 0.0,  "curl_window": 8,  "curl_accel_streak": 3}),
        ("accel_streak_4",          {"use_curl": True, "curl_r2_min": 0.0,  "curl_window": 8,  "curl_accel_streak": 4}),
        # a+R²+streak 조합
        ("a_r2_0.80_streak_3",      {"use_curl": True, "curl_r2_min": 0.80, "curl_window": 8,  "curl_accel_streak": 3}),
        ("a_r2_0.85_streak_3",      {"use_curl": True, "curl_r2_min": 0.85, "curl_window": 8,  "curl_accel_streak": 3}),
    ]

    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.width", 160)

    rows = []
    for asset, files, loader, uni in [
        ("crypto", cr_files, load_crypto_weekly, cr_uni),
        ("kr",     kr_files, load_stock_weekly,  kr_uni),
        ("us",     us_files, load_stock_weekly,  us_uni),
    ]:
        rule = rules[asset]
        print(f"\n=== {asset.upper()} (universe={len(uni)}, rule={rule.name}) ===")
        print(f"{'variant':<24s} {'n':>4s} {'win%':>5s} {'mean%':>6s} {'med%':>6s} {'held':>5s} {'total%':>9s} {'MDD%':>7s} {'Sharpe':>7s} {'PF':>5s}")
        for vname, params in variants:
            trades = collect(asset, files, loader, uni, rule, COST_RT[asset], params)
            s = summarize(trades)
            rows.append({"asset": asset, "variant": vname, **s})
            if s["n"] == 0:
                print(f"{vname:<24s}    0 trades")
                continue
            print(f"{vname:<24s} {s['n']:>4d} {s['win%']:>4.1f}% {s['mean%']:>+6.1f} {s['median%']:>+6.1f} "
                  f"{s['held_w']:>5.1f} {s['total%']:>+9.1f} {s['MDD%']:>+7.1f} {s['Sharpe_ann']:>+7.2f} {s['PF']:>5.2f}")

    pd.DataFrame(rows).to_csv(ROOT / "scripts/out/compare_curl.csv", index=False, encoding="utf-8-sig")
    print(f"\nsaved: scripts/out/compare_curl.csv")


if __name__ == "__main__":
    main()
