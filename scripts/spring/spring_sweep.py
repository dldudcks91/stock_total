"""Spring 검출 파라미터 스윕 - 여러 강도 조합을 한 번에 비교.

각 심볼의 4H 데이터와 주봉 SMA10을 1번만 로드하고, 여러 (alpha, vol, wick)
조합으로 detect_springs를 돌려 (n, win%, mean%, median%) 표를 출력한다.
"""

from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from data.resample import load  # noqa: E402
from scripts.spring.spring_scan import (  # noqa: E402
    _weekly_sma10_on_4h,
    detect_springs,
    list_symbols,
)

CACHE_DIR = ROOT / "data" / "cache" / "crypto"
CLASSIFICATION_PATH = CACHE_DIR / "classification.parquet"

# 스윕할 조합 (alpha, vol_mult, wick_ratio, ft_atr)
CONFIGS = [
    # 이름,        alpha, vol, wick, body, ft
    ("loose",       0.3, 1.5, 0.50, 0.15, 0.0),   # 원래 (필터 약함)
    ("loose+ft",    0.3, 1.5, 0.50, 0.15, 0.3),   # +follow-through만 추가
    ("mid",         0.5, 1.8, 0.55, 0.20, 0.3),   # 중간
    ("mid+",        0.7, 2.0, 0.55, 0.20, 0.4),   # 중상
    ("strict-lite", 0.7, 2.0, 0.60, 0.20, 0.5),   # 엄격(완)
    ("strict",      1.0, 2.5, 0.60, 0.20, 0.5),   # 엄격(현재)
]


def evaluate(events: pd.DataFrame) -> dict:
    if events.empty:
        return {"n": 0, "win_24h": np.nan, "mean_24h": np.nan, "med_24h": np.nan,
                "win_96h": np.nan, "mean_96h": np.nan, "med_96h": np.nan}
    s24 = events["ret_24h"].dropna()
    s96 = events["ret_96h"].dropna()
    return {
        "n": len(events),
        "win_24h": (s24 > 0).mean() * 100 if len(s24) else np.nan,
        "mean_24h": s24.mean() if len(s24) else np.nan,
        "med_24h": s24.median() if len(s24) else np.nan,
        "win_96h": (s96 > 0).mean() * 100 if len(s96) else np.nan,
        "mean_96h": s96.mean() if len(s96) else np.nan,
        "med_96h": s96.median() if len(s96) else np.nan,
    }


def main():
    cls = None
    if CLASSIFICATION_PATH.exists():
        cls = pd.read_parquet(CLASSIFICATION_PATH)[["symbol", "tier_final"]]
    symbol_to_tier = dict(zip(cls["symbol"], cls["tier_final"])) if cls is not None else {}

    symbols = list_symbols()
    print(f"[sweep] symbols={len(symbols)} configs={len(CONFIGS)}")

    # 각 심볼의 4H + weekly SMA10 캐시
    cache: dict[str, tuple[pd.DataFrame, np.ndarray]] = {}
    for i, sym in enumerate(symbols, 1):
        try:
            df_4h = load(sym, "4h")
            wsma = _weekly_sma10_on_4h(sym, df_4h)
            cache[sym] = (df_4h, wsma)
        except Exception:
            pass
        if i % 100 == 0:
            print(f"  loaded {i}/{len(symbols)}")
    print(f"  cached {len(cache)} symbols")

    # 각 config 평가
    rows_overall = []
    rows_by_tier: dict[str, list] = {}
    for name, alpha, vol, wick, body, ft in CONFIGS:
        all_events = []
        for sym, (df_4h, wsma) in cache.items():
            ev = detect_springs(
                df_4h,
                alpha=alpha,
                vol_mult=vol,
                wick_ratio_min=wick,
                body_ratio_min=body,
                followthrough_atr=ft,
                weekly_sma10=wsma,
            )
            if not ev.empty:
                ev = ev.copy()
                ev["symbol"] = sym
                ev["tier"] = symbol_to_tier.get(sym, "?")
                all_events.append(ev)
        events = pd.concat(all_events, ignore_index=True) if all_events else pd.DataFrame()

        agg = evaluate(events)
        agg["config"] = name
        agg["params"] = f"α={alpha} vol×{vol} wick>{wick} ft={ft}·ATR"
        rows_overall.append(agg)

        # tier별
        if not events.empty:
            for tier, grp in events.groupby("tier"):
                if tier not in rows_by_tier:
                    rows_by_tier[tier] = []
                t = evaluate(grp)
                t["config"] = name
                rows_by_tier[tier].append(t)

    print("\n" + "=" * 100)
    print("OVERALL - all symbols")
    print("=" * 100)
    df_o = pd.DataFrame(rows_overall)[
        ["config", "params", "n", "win_24h", "mean_24h", "med_24h",
         "win_96h", "mean_96h", "med_96h"]
    ]
    print(df_o.to_string(index=False, float_format=lambda x: f"{x:7.2f}"))

    for tier in ["trend", "follower", "whale", "junk"]:
        if tier not in rows_by_tier:
            continue
        print(f"\n=== tier = {tier} ===")
        df_t = pd.DataFrame(rows_by_tier[tier])[
            ["config", "n", "win_24h", "mean_24h", "med_24h",
             "win_96h", "mean_96h", "med_96h"]
        ]
        print(df_t.to_string(index=False, float_format=lambda x: f"{x:7.2f}"))

    print(f"\n[hint] 거래 빈도 환산: n / 543 symbols / 3년 ≈ 심볼당 연간 평균 신호수")


if __name__ == "__main__":
    main()
