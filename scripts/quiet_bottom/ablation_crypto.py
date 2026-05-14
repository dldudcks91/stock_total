"""Crypto 진입 조건 ablation — 어느 조건이 가장 많이 거르는지 진단.

각 조건을 하나씩 꺼서 시그널 카운트가 어떻게 변하는지 측정.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import ma_slope_turn_up  # noqa: E402
from scripts.quiet_bottom.count_slope_turn_signals import (  # noqa: E402
    load_crypto_weekly, crypto_symbol_from_file,
    CRYPTO_1H_DIR, SINCE,
)
from scripts.quiet_bottom.forward_returns_top200 import crypto_top_universe  # noqa: E402


def count_signals(files, universe, params: dict) -> tuple[int, int]:
    """(시그널 수, 종목 수)"""
    n_sig = 0
    syms = set()
    for p in files:
        symbol = crypto_symbol_from_file(p)
        if symbol not in universe:
            continue
        try:
            df_w = load_crypto_weekly(p)
            if df_w is None or df_w.empty or len(df_w) < 120:
                continue
            sig = ma_slope_turn_up.signal(df_w.reset_index(drop=True), params)
            sig.index = df_w.index
            entries = (sig.diff() == 1) & (df_w.index >= SINCE)
            c = int(entries.sum())
            if c > 0:
                n_sig += c
                syms.add(symbol)
        except Exception:
            continue
    return n_sig, len(syms)


def main():
    # universe들 비교
    for top_n in [200, 300, 500]:
        # universe 재계산 (TOP_N 임시 변경)
        import scripts.quiet_bottom.forward_returns_top200 as ft
        ft.TOP_N = top_n
        uni = crypto_top_universe()
        files = sorted(CRYPTO_1H_DIR.glob("*.parquet"))
        # 안의 종목 수 확인
        eligible = [crypto_symbol_from_file(p) for p in files if crypto_symbol_from_file(p) in uni]
        print(f"\n[Crypto universe TOP{top_n}] cache match: {len(eligible)}/{len(uni)}")

        # ablation: 베이스라인 + 각 조건 끄기
        ablations = [
            ("baseline_all_on", {}),  # 모든 조건 ON (현재 default)
            ("OFF_slope_turn_before_settle", {"slope_turn_before_settle": False}),
            ("OFF_settle (no_breakdown+pullback)", {"settle_lookback": 1, "pullback_thr": 999}),
            ("OFF_long_dd",                {"long_dd_min": -0.999}),
            ("OFF_long_slope_neg",         {"long_slope_neg_ratio": 0.0}),
            ("OFF_prior_down",             {"down_lookback": 0}),  # 0이면 빈 윈도우
            ("OFF_close>MA20",             {}),  # 코드에 옵션 없으므로 skip
            ("relaxed_dd_-0.20",           {"long_dd_min": -0.20}),
            ("relaxed_settle_lb_2",        {"settle_lookback": 2}),
            ("relaxed_pullback_0.05",      {"pullback_thr": 0.05}),
            ("relaxed_long_neg_0.5",       {"long_slope_neg_ratio": 0.5}),
        ]
        print(f"{'variant':<42s} {'signals':>8s} {'symbols':>8s}")
        for name, override in ablations:
            try:
                n, sy = count_signals(files, uni, override)
                print(f"{name:<42s} {n:>8d} {sy:>8d}")
            except Exception as e:
                print(f"{name:<42s} ERROR: {e}")


if __name__ == "__main__":
    main()
