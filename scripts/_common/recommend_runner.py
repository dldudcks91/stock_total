"""ma_touch 자산별 recommend 의 공통 엔진.

자산별 `scripts/{asset}/ma_touch/recommend.py` 는 universe 만 제공하고 이 엔진을
호출. 5 TF × {full, partial} 평가 + row 조립 + parquet 저장까지 한 군데서 처리.

흐름:
  for symbol in universe:
    mtf = mtf_loader.load_multi_tf(asset, symbol)
    for tf in [1D, 1W, 1M, 1Q, 1Y]:
        kind = tf_selector.determine_eval_kind(mtf[tf])
        df_ind = mtf_indicators.compute_mtf_indicators(mtf[tf], kind)
        passed_full, passed_partial, extras = signals.evaluate_tf(df_ind, kind)
        → row 의 signal_ma_touch_{tf}_full/partial + ma10/ma20/dist/angle 컬럼 채움
  → DataFrame 변환 → parquet 저장
"""
from __future__ import annotations

import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd

from scripts._common.mtf_loader import TF_FREQ, load_multi_tf
from scripts._common.mtf_indicators import compute_mtf_indicators
from scripts._common.signals.g3 import evaluate_tf
from scripts._common.tf_selector import determine_eval_kind, select_eval_tfs

_ROOT = Path(__file__).resolve().parents[2]
_CACHE = _ROOT / "data" / "cache"
_KST_TZ = "Asia/Seoul"

# 평가 대상 TF (출력 컬럼 순서 고정).
EVAL_TFS = ("1D", "1W", "1M", "1Q", "1Y")

# 일봉 너무 짧으면 스킵 (PLAN 1절).
MIN_DAILY_BARS = 60


def _row_for_symbol(asset: str, symbol: str) -> Optional[dict]:
    """한 종목의 평가 결과 row dict. 일봉 60일 미만이면 None."""
    try:
        mtf = load_multi_tf(asset, symbol)
    except Exception:
        # parquet 읽기 실패 — 종목 제외
        return None

    df_d = mtf["1D"]
    if len(df_d) < MIN_DAILY_BARS:
        return None

    row: dict = {
        "symbol": symbol,
        "asset": asset,
        "close_price": float(df_d["close"].iloc[-1]),
        "evaluated_at_kst": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z"),
    }

    passed_tfs: List[str] = []
    angle_pos_ma20_count = 0
    signal_count = 0

    # 사용자 룰: 월봉 MA10 가능 → 1D 평가 제외
    allowed_tfs = set(select_eval_tfs(mtf))
    # 모든 TF 평가에 사용할 today_low (오늘 일봉 마지막 봉의 low)
    today_low = float(df_d["low"].iloc[-1])

    for tf in EVAL_TFS:
        df_tf = mtf[tf]
        kind = determine_eval_kind(df_tf)
        if (tf not in allowed_tfs) or kind == "skip":
            row[f"signal_ma_touch_{tf}_full"] = None
            row[f"signal_ma_touch_{tf}_partial"] = None
            row[f"ma10_{tf}_price"] = None
            row[f"ma20_{tf}_price"] = None
            row[f"dist_to_ma10_{tf}_pct"] = None
            row[f"dist_to_ma20_{tf}_pct"] = None
            row[f"angle_ma10_{tf}_degree"] = None
            row[f"angle_ma20_{tf}_degree"] = None
            row[f"angle_strength_label_{tf}"] = None
            continue

        df_ind = compute_mtf_indicators(df_tf, kind)
        last = df_ind.iloc[-1]

        passed_full, passed_partial, extras = evaluate_tf(df_ind, df_d, kind, today_low=today_low)

        row[f"signal_ma_touch_{tf}_full"] = passed_full if kind == "full" else None
        row[f"signal_ma_touch_{tf}_partial"] = passed_partial if kind == "partial" else None
        row[f"ma10_{tf}_price"] = float(last["ma10"]) if pd.notna(last["ma10"]) else None
        row[f"ma20_{tf}_price"] = float(last["ma20"]) if pd.notna(last["ma20"]) else None
        row[f"dist_to_ma10_{tf}_pct"] = float(last["dist_to_ma10_pct"]) if pd.notna(last["dist_to_ma10_pct"]) else None
        row[f"dist_to_ma20_{tf}_pct"] = float(last["dist_to_ma20_pct"]) if pd.notna(last["dist_to_ma20_pct"]) else None
        row[f"angle_ma10_{tf}_degree"] = float(last["angle_ma10_deg"]) if pd.notna(last["angle_ma10_deg"]) else None
        row[f"angle_ma20_{tf}_degree"] = float(last["angle_ma20_deg"]) if pd.notna(last["angle_ma20_deg"]) else None
        row[f"angle_strength_label_{tf}"] = extras.get("angle_strength_label")

        if passed_full or passed_partial:
            passed_tfs.append(tf)
            signal_count += 1
        # 각도 양수 (큰 흐름 정합도)
        a20 = row[f"angle_ma20_{tf}_degree"]
        if a20 is not None and a20 > 0:
            angle_pos_ma20_count += 1

    # 파생 라벨
    row["signal_ma_touch_timeframes_passed"] = ",".join(passed_tfs) if passed_tfs else ""
    row["count_signal_ma_touch_total"] = signal_count
    row["count_angle_positive_ma20"] = angle_pos_ma20_count

    return row


def evaluate_universe(asset: str, symbols: Iterable[str], verbose: bool = True) -> pd.DataFrame:
    """전체 universe 평가 → DataFrame.

    실패 종목은 silently skip. 진행 표시는 verbose=True 일 때만 stderr 로.
    """
    rows: List[dict] = []
    syms = list(symbols)
    n = len(syms)
    t0 = time.time()
    failed = 0
    for i, sym in enumerate(syms, 1):
        try:
            r = _row_for_symbol(asset, sym)
            if r is not None:
                rows.append(r)
        except Exception:
            failed += 1
            if verbose and failed <= 3:
                print(f"  ! {sym}: {traceback.format_exc().splitlines()[-1]}", file=sys.stderr)
        if verbose and i % 100 == 0:
            elapsed = time.time() - t0
            print(f"  [{i}/{n}] elapsed={elapsed:.1f}s  rows={len(rows)}", file=sys.stderr)

    elapsed = time.time() - t0
    if verbose:
        print(f"Done: {len(rows)}/{n} rows, failed={failed}, wall={elapsed:.1f}s", file=sys.stderr)
    return pd.DataFrame(rows)


def save_recommendations(df: pd.DataFrame, asset: str) -> Path:
    out = _CACHE / asset / "_ma_touch.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return out


def discover_universe(asset: str) -> List[str]:
    """캐시 폴더에서 자동 universe 추출. crypto 는 주식/ETF perpetual 자동 제외."""
    if asset == "crypto":
        base = _CACHE / "crypto" / "1d"
    else:
        base = _CACHE / asset
    if not base.exists():
        return []
    syms = sorted(p.stem for p in base.glob("*.parquet") if not p.stem.startswith("_"))
    if asset == "crypto":
        from scripts._common.crypto_filters import filter_crypto_universe
        syms = filter_crypto_universe(syms)
    return syms
