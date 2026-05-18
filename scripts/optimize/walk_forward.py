"""Agent W — Round 3 Walk-forward / regime-fairness validator.

Round 2 의 OOS (2024-05 ~ 2026-05) Sharpe 가 IS 보다 큰 현상이 강세장 의존
때문인지 검증한다.

Tasks:
  task1 : 6 개 1년 sliding window (W1..W6) 별 Sharpe / mean% / win% / n
  task2 : 각 window 의 시장(KOSPI / NASDAQ) regime tag (강세/약세/횡보)
  task3 : Anchored walk-forward (IS_size 2yr→6yr, 다음 1년 OOS)
  task4 : 매크로 게이트 (지수 > EMA200) on/off 비교  (옵션)

전부 .venv/Scripts/python.exe 경유 실행. 룩어헤드 금지.

CLI:
  .venv/Scripts/python.exe -m scripts.optimize.walk_forward task1
  .venv/Scripts/python.exe -m scripts.optimize.walk_forward task2
  .venv/Scripts/python.exe -m scripts.optimize.walk_forward task3
  .venv/Scripts/python.exe -m scripts.optimize.walk_forward task4
  .venv/Scripts/python.exe -m scripts.optimize.walk_forward all
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.optimize_grid import (  # noqa: E402
    ExitRule, _files_for, load_symbol, MIN_BARS, COST_RT,
)
from scripts.optimize.kr_round2 import (  # noqa: E402
    build_cache as kr_build_cache,
    simulate2 as kr_simulate2,
    STRATEGIES,
)
from scripts.optimize.us_round2 import (  # noqa: E402
    build_cache as us_build_cache,
    us_top_universe,
    Rule2,
    simulate2 as us_simulate2,
    PERIOD_FULL as US_PERIOD_FULL,
)

OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "round3" / "walk_forward"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS = OUT_DIR / "PROGRESS.md"


# ---------------------------------------------------------------------------
# Recommended rules per Round 2 (asset, strategy, interval)
# ---------------------------------------------------------------------------
@dataclass
class Recommendation:
    asset: str           # "kr" | "us"
    strategy: str
    interval: str        # "1d" | "1w"
    threshold: float
    max_hold: int
    trailing_pct: float
    take_profit_pct: float
    hard_sl: Optional[float] = None  # negative number e.g. -0.20  (None disables)

    @property
    def key(self) -> str:
        return f"{self.asset}_{self.strategy}_{self.interval}"

    def to_kr_rule(self) -> ExitRule:
        r = ExitRule(
            name=f"h{self.max_hold}_tr{int(self.trailing_pct*100)}_TP{int(self.take_profit_pct*100)}",
            max_hold=self.max_hold,
            trailing_pct=self.trailing_pct,
            take_profit_pct=self.take_profit_pct,
        )
        r._hard_sl = self.hard_sl  # type: ignore[attr-defined]
        return r

    def to_us_rule(self) -> Rule2:
        return Rule2(
            name=f"h{self.max_hold}_tr{int(self.trailing_pct*100)}_TP{int(self.take_profit_pct*100)}",
            max_hold=self.max_hold,
            trailing_pct=self.trailing_pct,
            take_profit_pct=self.take_profit_pct,
            stop_loss_pct=(abs(self.hard_sl) if self.hard_sl is not None else 0.0),
            cut3d_neg=False,
        )


RECS: List[Recommendation] = [
    Recommendation("kr", "trend_pullback", "1d", 60, 252, 0.25, 0.40),
    Recommendation("kr", "trend_pullback", "1w", 75,  78, 0.20, 0.40),
    Recommendation("kr", "trend_chase",    "1d", 60, 365, 0.25, 0.40),
    Recommendation("us", "trend_pullback", "1d", 70, 252, 0.20, 0.30),
    Recommendation("us", "trend_pullback", "1w", 70,  52, 0.20, 0.30),
    Recommendation("us", "trend_chase",    "1d", 60, 252, 0.20, 0.30),
]

KR_UNIVERSE_TOP = 800
US_UNIVERSE_TOP = 300


# ---------------------------------------------------------------------------
# Windows (6 × 1y, sliding)
# ---------------------------------------------------------------------------
WINDOWS: List[Tuple[str, pd.Timestamp, pd.Timestamp]] = [
    ("W1", pd.Timestamp("2020-05-01"), pd.Timestamp("2021-05-01")),
    ("W2", pd.Timestamp("2021-05-01"), pd.Timestamp("2022-05-01")),
    ("W3", pd.Timestamp("2022-05-01"), pd.Timestamp("2023-05-01")),
    ("W4", pd.Timestamp("2023-05-01"), pd.Timestamp("2024-05-01")),
    ("W5", pd.Timestamp("2024-05-01"), pd.Timestamp("2025-05-01")),
    ("W6", pd.Timestamp("2025-05-01"), pd.Timestamp("2026-05-18")),
]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    ts = pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M:%S")
    line = f"- [{ts}] {msg}"
    print(line, flush=True)
    with PROGRESS.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Cache builders (memoised across tasks)
# ---------------------------------------------------------------------------
_KR_CACHE: Dict[Tuple[str, str], dict] = {}
_US_CACHE: Dict[Tuple[str, str], list] = {}


def get_kr_cache(strategy: str, interval: str) -> dict:
    key = (strategy, interval)
    if key not in _KR_CACHE:
        log(f"[cache] KR build {strategy}/{interval} top={KR_UNIVERSE_TOP}")
        t0 = time.time()
        _KR_CACHE[key] = kr_build_cache("kr", strategy, interval, KR_UNIVERSE_TOP)
        log(f"[cache] KR {strategy}/{interval} -> {len(_KR_CACHE[key])} symbols ({time.time()-t0:.1f}s)")
    return _KR_CACHE[key]


def get_us_cache(strategy: str, interval: str) -> list:
    key = (strategy, interval)
    if key not in _US_CACHE:
        log(f"[cache] US build {strategy}/{interval} top={US_UNIVERSE_TOP}")
        t0 = time.time()
        uni = us_top_universe(US_UNIVERSE_TOP)
        _US_CACHE[key] = us_build_cache(strategy, interval, uni, verbose=False)
        log(f"[cache] US {strategy}/{interval} -> {len(_US_CACHE[key])} symbols ({time.time()-t0:.1f}s)")
    return _US_CACHE[key]


# ---------------------------------------------------------------------------
# Window evaluator (asset-aware)
# ---------------------------------------------------------------------------
def _summary(rets: np.ndarray, helds: np.ndarray, since_years: float) -> dict:
    if len(rets) == 0:
        return {"n": 0, "win%": 0.0, "mean%": 0.0, "median%": 0.0, "held": 0.0,
                "total%": 0.0, "MDD%": 0.0, "Sharpe_ann": 0.0, "PF": 0.0}
    win = float((rets > 0).mean() * 100)
    mean = float(rets.mean() * 100)
    median = float(np.median(rets) * 100)
    held = float(helds.mean()) if len(helds) else 0.0
    eq = np.cumprod(1.0 + rets)
    total = float((eq[-1] - 1.0) * 100)
    peak = np.maximum.accumulate(eq)
    dd = float((eq / peak - 1.0).min() * 100)
    if rets.std() > 0:
        sharpe_pt = rets.mean() / rets.std()
        annual_factor = np.sqrt(max(1, len(rets)) / float(max(0.1, since_years)))
        sharpe_ann = float(sharpe_pt * annual_factor)
    else:
        sharpe_ann = 0.0
    gains = rets[rets > 0].sum()
    losses = -rets[rets < 0].sum()
    pf = float(gains / losses) if losses > 0 else float("inf")
    return {
        "n": int(len(rets)), "win%": round(win, 1),
        "mean%": round(mean, 2), "median%": round(median, 2),
        "held": round(held, 1), "total%": round(total, 1),
        "MDD%": round(dd, 1), "Sharpe_ann": round(sharpe_ann, 2),
        "PF": round(pf, 2) if pf != float("inf") else 99.99,
    }


def evaluate_window_kr(cache: dict, threshold: float, rule: ExitRule,
                       is_quiet: bool,
                       start: pd.Timestamp, end: pd.Timestamp,
                       cost: float, since_years: float,
                       macro_mask: Optional[Dict[pd.Timestamp, bool]] = None,
                       ) -> dict:
    """KR cache 형식: {symbol: (close, val, dt_idx)}."""
    rets = []
    helds = []
    for symbol, (close, val, dt_idx) in cache.items():
        in_period = (dt_idx >= start) & (dt_idx < end)
        if is_quiet:
            sig01 = val
        else:
            sig01 = (val >= float(threshold)).astype("int8")
        if len(sig01) < 2:
            continue
        diff = np.diff(sig01.astype("int16"), prepend=0)
        enter_mask = (diff == 1) & in_period
        positions = np.where(enter_mask)[0]
        for pos in positions:
            if macro_mask is not None:
                ts = dt_idx[pos]
                # round down to nearest macro idx date (daily) — exact-key lookup
                ok = macro_mask.get(pd.Timestamp(ts).normalize(), False)
                if not ok:
                    continue
            if pos >= len(close) - 1:
                continue
            exit_pos, gross_ret = kr_simulate2(close, int(pos), rule)
            if exit_pos == pos:
                continue
            rets.append(gross_ret - cost)
            helds.append(exit_pos - pos)
    return _summary(np.asarray(rets, dtype="float64"),
                    np.asarray(helds, dtype="float64"),
                    since_years)


def evaluate_window_us(cache: list, threshold: float, rule: Rule2,
                       start: pd.Timestamp, end: pd.Timestamp,
                       cost: float, since_years: float,
                       macro_mask: Optional[Dict[pd.Timestamp, bool]] = None,
                       ) -> dict:
    """US cache 형식: list[SymCache]."""
    rets = []
    helds = []
    for rec in cache:
        # dt 문자열을 Timestamp 로
        dt_arr_str = rec.dt_arr
        # numpy datetime64 conversion
        dt_index = pd.DatetimeIndex(pd.to_datetime(dt_arr_str))
        in_period_arr = np.asarray((dt_index >= start) & (dt_index < end))
        sig01 = (rec.scores >= float(threshold)).astype("int8")
        if len(sig01) < 2:
            continue
        diff = np.diff(sig01.astype("int16"), prepend=0)
        enter_mask = (diff == 1) & in_period_arr
        positions = np.where(enter_mask)[0]
        for pos in positions:
            if macro_mask is not None:
                ts = dt_index[pos]
                ok = macro_mask.get(pd.Timestamp(ts).normalize(), False)
                if not ok:
                    continue
            if pos >= len(rec.close) - 1:
                continue
            exit_pos, gross_ret = us_simulate2(rec.close, int(pos), rule)
            if exit_pos == pos:
                continue
            rets.append(gross_ret - cost)
            helds.append(exit_pos - pos)
    return _summary(np.asarray(rets, dtype="float64"),
                    np.asarray(helds, dtype="float64"),
                    since_years)


def evaluate_rec_window(rec: Recommendation, start: pd.Timestamp, end: pd.Timestamp,
                        macro_mask: Optional[Dict[pd.Timestamp, bool]] = None,
                        ) -> dict:
    years = max(0.05, (end - start).days / 365.25)
    cost = COST_RT[rec.asset]
    if rec.asset == "kr":
        cache = get_kr_cache(rec.strategy, rec.interval)
        return evaluate_window_kr(
            cache, rec.threshold, rec.to_kr_rule(),
            is_quiet=(rec.strategy == "quiet_bottom"),
            start=start, end=end, cost=cost, since_years=years,
            macro_mask=macro_mask,
        )
    else:
        cache = get_us_cache(rec.strategy, rec.interval)
        return evaluate_window_us(
            cache, rec.threshold, rec.to_us_rule(),
            start=start, end=end, cost=cost, since_years=years,
            macro_mask=macro_mask,
        )


# ---------------------------------------------------------------------------
# Task 1 — sliding window walk-forward
# ---------------------------------------------------------------------------
def task1() -> pd.DataFrame:
    log("task1 start — 6 sliding windows × 6 recommendations")
    rows = []
    summary_rows = []
    for rec in RECS:
        log(f"  evaluating {rec.key} (th={rec.threshold}, hold={rec.max_hold}, "
            f"trail={rec.trailing_pct}, TP={rec.take_profit_pct})")
        ws_sharpe = []
        for wname, ws, we in WINDOWS:
            s = evaluate_rec_window(rec, ws, we)
            row = {
                "asset": rec.asset, "strategy": rec.strategy, "interval": rec.interval,
                "window": wname,
                "start": ws.strftime("%Y-%m-%d"), "end": we.strftime("%Y-%m-%d"),
                "threshold": rec.threshold,
                "max_hold": rec.max_hold, "trailing_pct": rec.trailing_pct,
                "take_profit_pct": rec.take_profit_pct,
                **s,
            }
            rows.append(row)
            ws_sharpe.append(s["Sharpe_ann"])
            print(f"    {wname} {ws.date()}~{we.date()}: "
                  f"n={s['n']:>4} sharpe={s['Sharpe_ann']:>6.2f} "
                  f"mean={s['mean%']:>6.2f}% win={s['win%']:>5.1f}% MDD={s['MDD%']:>6.1f}%",
                  flush=True)
        arr = np.asarray(ws_sharpe)
        summary_rows.append({
            "asset": rec.asset, "strategy": rec.strategy, "interval": rec.interval,
            "W1": ws_sharpe[0], "W2": ws_sharpe[1], "W3": ws_sharpe[2],
            "W4": ws_sharpe[3], "W5": ws_sharpe[4], "W6": ws_sharpe[5],
            "mean": round(float(arr.mean()), 2),
            "std": round(float(arr.std()), 2),
            "min": round(float(arr.min()), 2),
            "max": round(float(arr.max()), 2),
            "pct_pos": round(float((arr > 0).mean() * 100), 1),
        })
        # per-rec CSV
        rec_df = pd.DataFrame([r for r in rows if r["asset"] == rec.asset
                              and r["strategy"] == rec.strategy
                              and r["interval"] == rec.interval])
        rec_df.to_csv(OUT_DIR / f"task1_{rec.asset}_{rec.strategy}_{rec.interval}.csv",
                      index=False, encoding="utf-8-sig")

    full = pd.DataFrame(rows)
    full.to_csv(OUT_DIR / "task1_all.csv", index=False, encoding="utf-8-sig")
    summ = pd.DataFrame(summary_rows)
    summ.to_csv(OUT_DIR / "task1_sharpe_matrix.csv", index=False, encoding="utf-8-sig")
    log("task1 done")
    print("\n=== Task 1 Sharpe matrix ===", flush=True)
    print(summ.to_string(index=False), flush=True)
    return summ


# ---------------------------------------------------------------------------
# Task 2 — Regime tagging via KOSPI / NASDAQ index
# ---------------------------------------------------------------------------
INDEX_CACHE = OUT_DIR / "_indices.parquet"


def load_indices() -> Dict[str, pd.Series]:
    """Returns {'kr': KOSPI close series, 'us': NASDAQ close series}.

    캐시 우선. 없으면 FDR fetch. 실패 시 빈 dict.
    """
    if INDEX_CACHE.exists():
        try:
            df = pd.read_parquet(INDEX_CACHE)
            return {col: df[col].dropna() for col in df.columns}
        except Exception:
            pass
    try:
        import FinanceDataReader as fdr
        kospi = fdr.DataReader("KS11", "2018-01-01")["Close"]
        nas = fdr.DataReader("IXIC", "2018-01-01")["Close"]
        df = pd.DataFrame({"kr": kospi, "us": nas})
        df.to_parquet(INDEX_CACHE)
        log(f"[indices] fetched KOSPI {kospi.shape} NASDAQ {nas.shape}")
        return {"kr": kospi, "us": nas}
    except Exception as e:
        log(f"[indices] WARN failed to fetch indices: {e}")
        return {}


def classify_regime(idx: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    sub = idx[(idx.index >= start) & (idx.index < end)].dropna()
    if len(sub) < 2:
        return {"start_px": None, "end_px": None, "ret%": 0.0,
                "max_dd%": 0.0, "regime": "n/a"}
    s0 = float(sub.iloc[0])
    s1 = float(sub.iloc[-1])
    ret = (s1 / s0 - 1.0) * 100.0
    peak = sub.cummax()
    dd = float((sub / peak - 1.0).min() * 100.0)
    if ret >= 8:
        regime = "bull"
    elif ret <= -8:
        regime = "bear"
    else:
        regime = "sideways"
    return {"start_px": round(s0, 2), "end_px": round(s1, 2),
            "ret%": round(ret, 1), "max_dd%": round(dd, 1),
            "regime": regime}


def task2() -> pd.DataFrame:
    log("task2 start — regime tag per window")
    idxs = load_indices()
    if not idxs:
        log("task2: no index data → BLOCKED partial")
    rows = []
    for asset, idx in idxs.items():
        for wname, ws, we in WINDOWS:
            tag = classify_regime(idx, ws, we)
            rows.append({"asset": asset, "window": wname,
                         "start": ws.strftime("%Y-%m-%d"),
                         "end": we.strftime("%Y-%m-%d"),
                         **tag})
    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "task2_regime.csv", index=False, encoding="utf-8-sig")
    print("\n=== Task 2 Regime tags ===", flush=True)
    print(df.to_string(index=False), flush=True)

    # correlation regime <-> Sharpe (from task1_sharpe_matrix)
    t1 = OUT_DIR / "task1_sharpe_matrix.csv"
    if t1.exists() and not df.empty:
        sm = pd.read_csv(t1)
        # wide -> long
        long_rows = []
        for _, r in sm.iterrows():
            for w in ("W1", "W2", "W3", "W4", "W5", "W6"):
                long_rows.append({"asset": r["asset"], "strategy": r["strategy"],
                                  "interval": r["interval"],
                                  "window": w, "Sharpe": r[w]})
        long_df = pd.DataFrame(long_rows)
        merged = long_df.merge(df, on=["asset", "window"], how="left")
        merged.to_csv(OUT_DIR / "task2_regime_x_sharpe.csv",
                      index=False, encoding="utf-8-sig")
        # correlation across strategies
        corrs = []
        for (a, s, iv), g in merged.groupby(["asset", "strategy", "interval"]):
            if g["ret%"].notna().sum() >= 3 and g["Sharpe"].std() > 0:
                c = float(g["ret%"].corr(g["Sharpe"]))
            else:
                c = float("nan")
            corrs.append({"asset": a, "strategy": s, "interval": iv,
                          "corr_index_ret_vs_sharpe": round(c, 3) if not np.isnan(c) else None})
        corr_df = pd.DataFrame(corrs)
        corr_df.to_csv(OUT_DIR / "task2_corr.csv", index=False, encoding="utf-8-sig")
        print("\n=== Task 2 Corr(index ret%, Sharpe) ===", flush=True)
        print(corr_df.to_string(index=False), flush=True)

    log("task2 done")
    return df


# ---------------------------------------------------------------------------
# Task 3 — Anchored walk-forward
# ---------------------------------------------------------------------------
def task3() -> pd.DataFrame:
    """IS_size = 2..5yr, anchored at 2020-05-01. 다음 1년 OOS 평가.
    (IS_size, OOS_year):
       2yr  IS 2020-05~2022-05  → OOS 2022-05~2023-05
       3yr  IS 2020-05~2023-05  → OOS 2023-05~2024-05
       4yr  IS 2020-05~2024-05  → OOS 2024-05~2025-05
       5yr  IS 2020-05~2025-05  → OOS 2025-05~2026-05
    """
    log("task3 start — anchored walk-forward")
    anchor = pd.Timestamp("2020-05-01")
    splits = []
    for is_yr in (2, 3, 4, 5):
        is_end = anchor + pd.DateOffset(years=is_yr)
        oos_end = is_end + pd.DateOffset(years=1)
        if oos_end > pd.Timestamp("2026-05-18"):
            oos_end = pd.Timestamp("2026-05-18")
        splits.append((is_yr, anchor, is_end, is_end, oos_end))

    rows = []
    for rec in RECS:
        log(f"  anchored {rec.key}")
        for is_yr, is_s, is_e, oos_s, oos_e in splits:
            is_years = (is_e - is_s).days / 365.25
            oos_years = max(0.05, (oos_e - oos_s).days / 365.25)
            is_summary = evaluate_rec_window(rec, is_s, is_e)
            # for anchored we keep same rule (Round 2 rec) — measure stability of OOS
            oos_summary = evaluate_rec_window(rec, oos_s, oos_e)
            rows.append({
                "asset": rec.asset, "strategy": rec.strategy, "interval": rec.interval,
                "IS_yr": is_yr,
                "IS_start": is_s.strftime("%Y-%m-%d"),
                "IS_end": is_e.strftime("%Y-%m-%d"),
                "OOS_start": oos_s.strftime("%Y-%m-%d"),
                "OOS_end": oos_e.strftime("%Y-%m-%d"),
                "IS_n": is_summary["n"], "IS_Sharpe": is_summary["Sharpe_ann"],
                "IS_mean%": is_summary["mean%"], "IS_win%": is_summary["win%"],
                "OOS_n": oos_summary["n"], "OOS_Sharpe": oos_summary["Sharpe_ann"],
                "OOS_mean%": oos_summary["mean%"], "OOS_win%": oos_summary["win%"],
            })
            print(f"    IS{is_yr}yr ({is_s.date()}..{is_e.date()})  "
                  f"IS_S={is_summary['Sharpe_ann']:>6.2f} | "
                  f"OOS({oos_s.date()}..{oos_e.date()}) "
                  f"OOS_S={oos_summary['Sharpe_ann']:>6.2f} "
                  f"n={oos_summary['n']}",
                  flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "task3_anchored.csv", index=False, encoding="utf-8-sig")
    print("\n=== Task 3 OOS Sharpe per IS_size ===", flush=True)
    pivot = df.pivot_table(index=["asset", "strategy", "interval"],
                           columns="IS_yr", values="OOS_Sharpe")
    print(pivot.to_string(), flush=True)
    pivot.to_csv(OUT_DIR / "task3_oos_sharpe_pivot.csv", encoding="utf-8-sig")
    log("task3 done")
    return df


# ---------------------------------------------------------------------------
# Task 4 — Macro gate (index > EMA200 or 6m ROC > 0)
# ---------------------------------------------------------------------------
def build_macro_mask(idx: pd.Series, gate: str = "ema200") -> Dict[pd.Timestamp, bool]:
    """gate ∈ {'ema200', 'roc6m'}.

    Returns {Timestamp(normalize): True/False} — pos lookup at entry day.
    룩어헤드 안전: t 시점에 가능한 t-1까지의 정보만 사용. 여기서는 그날 close
    기준으로 판단 (실제 진입은 t+1 이라 안전).
    """
    idx = idx.dropna().sort_index()
    if gate == "ema200":
        ema = idx.ewm(span=200, adjust=False).mean()
        above = (idx > ema)
    elif gate == "roc6m":
        roc = idx / idx.shift(126) - 1.0
        above = (roc > 0)
    else:
        raise ValueError(gate)
    above = above.fillna(False)
    # build dict with normalized timestamps
    out: Dict[pd.Timestamp, bool] = {}
    for ts, ok in above.items():
        out[pd.Timestamp(ts).normalize()] = bool(ok)
    return out


def task4() -> pd.DataFrame:
    log("task4 start — macro gate (index EMA200 / 6m ROC)")
    idxs = load_indices()
    if not idxs:
        log("task4: indices unavailable → SKIP")
        return pd.DataFrame()
    masks = {}
    for asset, idx in idxs.items():
        masks[(asset, "ema200")] = build_macro_mask(idx, "ema200")
        masks[(asset, "roc6m")] = build_macro_mask(idx, "roc6m")

    rows = []
    for rec in RECS:
        log(f"  macro-gate {rec.key}")
        for gname in ("none", "ema200", "roc6m"):
            mask = None if gname == "none" else masks.get((rec.asset, gname))
            # full 6y window — bull / bear / sideways 혼합
            full_s = WINDOWS[0][1]
            full_e = WINDOWS[-1][2]
            years = (full_e - full_s).days / 365.25
            s = evaluate_rec_window(rec, full_s, full_e, macro_mask=mask)
            rows.append({
                "asset": rec.asset, "strategy": rec.strategy, "interval": rec.interval,
                "gate": gname,
                "n": s["n"], "win%": s["win%"], "mean%": s["mean%"],
                "MDD%": s["MDD%"], "Sharpe_ann": s["Sharpe_ann"], "PF": s["PF"],
            })
            print(f"    gate={gname:>7}  n={s['n']:>5} sharpe={s['Sharpe_ann']:>6.2f} "
                  f"mean={s['mean%']:>6.2f}% MDD={s['MDD%']:>6.1f}%", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT_DIR / "task4_macro_gate.csv", index=False, encoding="utf-8-sig")
    log("task4 done")
    return df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="walk_forward")
    p.add_argument("task", choices=["task1", "task2", "task3", "task4", "all"])
    args = p.parse_args(argv)

    log(f"=== Agent W start: {args.task} ===")
    t0 = time.time()
    if args.task in ("task1", "all"):
        task1()
    if args.task in ("task2", "all"):
        task2()
    if args.task in ("task3", "all"):
        task3()
    if args.task in ("task4", "all"):
        task4()
    log(f"=== Agent W done ({time.time()-t0:.1f}s) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
