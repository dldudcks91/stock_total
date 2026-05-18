"""Round 2 KR optimizer — extends optimize_grid for fine-tuning exit rules,
IS/OOS split, and universe sensitivity.

원본 scripts/optimize_grid.py 는 손대지 않음. 여기서 read-only 로 simulate/summarize
재사용 후 (asset, strategy, interval, score_th, exit_rule, date_window, universe_top)
별 그리드를 돌린다.

CLI:
  python -m scripts.optimize.kr_round2 task1 --strategy trend_pullback --interval 1d
  python -m scripts.optimize.kr_round2 task2 --strategy trend_pullback --interval 1d
  python -m scripts.optimize.kr_round2 task3 --strategy trend_pullback --interval 1d
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import trend_chase, trend_pullback, quiet_bottom  # noqa: E402
from scripts.optimize_grid import (  # noqa: E402
    ExitRule, simulate, summarize_trades,
    _files_for, load_symbol, MIN_BARS, COST_RT,
)
from scripts.trend_strategies.forward_returns import (  # noqa: E402
    kr_universe,
)

OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "round2" / "kr"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NOW = pd.Timestamp.utcnow().tz_localize(None).normalize()

STRATEGIES = {
    "trend_chase": trend_chase,
    "trend_pullback": trend_pullback,
    "quiet_bottom": quiet_bottom,
}

# round1 권장 threshold (best_per_combo 기반)
BEST_THRESHOLD = {
    ("trend_pullback", "1d"): 60,
    ("trend_pullback", "1w"): 75,
    ("trend_chase", "1d"): 60,
    ("trend_chase", "1w"): 60,
}


# ---------------------------------------------------------------------------
# Cache (symbol-level signal/score, computed once and reused)
# ---------------------------------------------------------------------------
_DATA_CACHE: Dict[Tuple[str, str], Dict[str, Tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]]] = {}


def build_cache(asset: str, strategy_name: str, interval: str,
                universe_top: int) -> Dict[str, Tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]]:
    """종목별 (close, score-or-signal, dt_index) 1회 캐시.

    Note: universe_top 별로 cache key 다름 — universe 가 작아지면 부분 집합.
    """
    key = (asset, strategy_name, interval, universe_top)
    cached = _DATA_CACHE.get(key)
    if cached is not None:
        return cached

    strat = STRATEGIES[strategy_name]
    min_bars = MIN_BARS[interval]
    is_quiet = (strategy_name == "quiet_bottom")

    if asset != "kr":
        raise ValueError("kr_round2 only supports asset=kr")
    # universe_top <= 0 → 모든 KR 캐시 파일 사용 (all)
    if universe_top <= 0:
        files_all = _files_for(asset, interval)
        universe = {p.stem for p in files_all}
    else:
        universe = kr_universe(universe_top)
        # FDR Marcap 이 300 까지만 반환할 수 있어 실제 universe 가 universe_top
        # 보다 작을 수 있음. 보강: universe_top > len(universe) 이면 캐시 파일 전체로 확장.
        if len(universe) < universe_top:
            files_all = _files_for(asset, interval)
            extra = {p.stem for p in files_all} - universe
            # 캐시 stems 의 사전순 (코드 오름차순) 으로 추가 → 결정적
            for stem in sorted(extra):
                if len(universe) >= universe_top:
                    break
                universe.add(stem)
    files = _files_for(asset, interval)

    print(f"\n--- build_cache asset=kr strategy={strategy_name} interval={interval} "
          f"universe_top={universe_top} -> {len(universe)} symbols, {len(files)} files ---",
          flush=True)

    t0 = time.time()
    out: Dict[str, Tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]] = {}
    n_done = 0
    n_skip = 0
    for p in files:
        symbol = p.stem
        if symbol not in universe:
            continue
        try:
            df = load_symbol(asset, p, interval)
        except Exception:
            n_skip += 1
            continue
        if df is None or df.empty or len(df) < min_bars:
            n_skip += 1
            continue
        df = df.sort_index()
        df_r = df.reset_index(drop=True)
        try:
            if is_quiet:
                sig = strat.signal(df_r, {})
                val = sig.to_numpy().astype("int8")
            else:
                sc = strat.score(df_r, {})
                val = sc.to_numpy().astype("float32")
        except Exception:
            n_skip += 1
            continue
        close = df["close"].astype("float64").to_numpy()
        dt_idx = pd.DatetimeIndex(df.index)
        out[symbol] = (close, val, dt_idx)
        n_done += 1
        if n_done % 50 == 0:
            print(f"  loaded {n_done} (skipped {n_skip}) elapsed {time.time()-t0:.1f}s",
                  flush=True)
    print(f"  build_cache done: {n_done} symbols, skipped {n_skip}. "
          f"elapsed {time.time()-t0:.1f}s", flush=True)
    _DATA_CACHE[key] = out
    return out


# ---------------------------------------------------------------------------
# Evaluation (single (threshold, rule, window) → summary)
# ---------------------------------------------------------------------------
def evaluate(cache: Dict[str, Tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]],
             threshold: float, rule: ExitRule, is_quiet: bool,
             start: Optional[pd.Timestamp], end: Optional[pd.Timestamp],
             cost: float, since_years: float) -> dict:
    """주어진 thresh/rule/시기 윈도우에 대해 trades 시뮬레이션 후 summary 반환."""
    trades = []
    for symbol, (close, val, dt_idx) in cache.items():
        in_period = np.ones(len(dt_idx), dtype=bool)
        if start is not None:
            in_period &= (dt_idx >= start)
        if end is not None:
            in_period &= (dt_idx < end)
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
            if pos >= len(close) - 1:
                continue
            exit_pos, gross_ret = simulate(close, int(pos), rule)
            if exit_pos == pos:
                continue
            net_ret = gross_ret - cost
            trades.append({
                "symbol": symbol,
                "held": exit_pos - pos,
                "gross_ret": gross_ret,
                "net_ret": net_ret,
            })

    # patched summary with custom since_years for annualisation
    if not trades:
        summary = {"n": 0, "win%": 0, "mean%": 0, "median%": 0, "held": 0,
                   "total%": 0, "MDD%": 0, "Sharpe_ann": 0, "PF": 0}
    else:
        df = pd.DataFrame(trades)
        rets = df["net_ret"].to_numpy()
        win = float((rets > 0).mean() * 100)
        mean = float(rets.mean() * 100)
        median = float(np.median(rets) * 100)
        held = float(df["held"].mean())
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
        summary = {
            "n": int(len(rets)), "win%": round(win, 1),
            "mean%": round(mean, 2), "median%": round(median, 2),
            "held": round(held, 1), "total%": round(total, 1),
            "MDD%": round(dd, 1), "Sharpe_ann": round(sharpe_ann, 2),
            "PF": round(pf, 2) if pf != float("inf") else 99.99,
        }
    return summary


# ---------------------------------------------------------------------------
# Exit rule grids (sweeps to keep things manageable)
# ---------------------------------------------------------------------------
def task1_rule_grid(interval: str) -> List[ExitRule]:
    """Sweep grid: hold × TP × trail × SL × cut_3d_neg
    1d: hold {120,180,252,365} × TP {None,25,30,40} × trail {15,20,25}
        × SL {None,-15,-20} × cut3dneg {False,True}
    1w: hold {26,39,52,78}    × TP {None,25,30,40} × trail {15,20,25}
        × SL {None,-15,-20} × cut3wneg {False,True}
    To keep tractable: full = 4×4×3×3×2 = 288 per (strategy,interval). ~ok.
    """
    if interval == "1d":
        holds = [120, 180, 252, 365]
        cut_at = 3  # 3-day after entry check
    else:
        holds = [26, 39, 52, 78]
        cut_at = 2  # 2 weeks after entry
    tps = [None, 0.25, 0.30, 0.40]
    trails = [0.15, 0.20, 0.25]
    sls = [None, -0.15, -0.20]
    cuts = [False, True]

    rules: List[ExitRule] = []
    for hold in holds:
        for tp in tps:
            for tr in trails:
                for sl in sls:
                    for cut in cuts:
                        tp_str = "TPx" if tp is None else f"TP{int(tp*100)}"
                        sl_str = "SLx" if sl is None else f"SL{int(abs(sl)*100)}"
                        cut_str = "cutY" if cut else "cutN"
                        # SL encoded via cut_short_thr=-100 disable when sl is None
                        # We'll repurpose cut_short_at to act as a hard SL probe: easier to
                        # just check ret <= sl in simulate. ExitRule supports trailing_pct
                        # but no hard stop_loss; instead use cut_short_thr at hold=1 not ideal.
                        # Simpler: model stop-loss via large negative cut_short at every bar by
                        # piggy-backing on trailing? trailing only triggers from peak.
                        # We'll extend with our own wrapper rule via the simulate path.
                        # NOTE: simulate currently supports cut_1bar_neg + cut_short. SL is
                        # implemented below in evaluate2() using a custom sim.
                        rule = ExitRule(
                            name=f"h{hold}_tr{int(tr*100)}_{tp_str}_{sl_str}_{cut_str}",
                            max_hold=hold,
                            trailing_pct=tr,
                            take_profit_pct=(tp or 0.0),
                            cut_1bar_neg=False,
                            cut_short_thr=(-5.0 if cut else -999.0),
                            cut_short_at=cut_at,
                        )
                        # We attach SL via a non-dataclass attribute (used by simulate2 below)
                        rule._hard_sl = sl  # type: ignore[attr-defined]
                        rules.append(rule)
    return rules


def simulate2(close: np.ndarray, entry_pos: int, rule: ExitRule) -> Tuple[int, float]:
    """simulate + hard stop-loss check (rule._hard_sl)."""
    hard_sl = getattr(rule, "_hard_sl", None)
    n = len(close)
    ec = close[entry_pos]
    if not np.isfinite(ec) or ec <= 0:
        return entry_pos, 0.0
    peak = ec
    for i in range(entry_pos + 1, n):
        held = i - entry_pos
        ci = close[i]
        if not np.isfinite(ci):
            continue
        peak = max(peak, ci)
        ret = ci / ec - 1.0
        # hard stop-loss (closing basis)
        if hard_sl is not None and ret <= hard_sl:
            return i, ret
        if rule.take_profit_pct > 0 and ret >= rule.take_profit_pct:
            return i, ret
        if rule.trailing_pct > 0 and peak > ec:
            if ci / peak - 1.0 <= -rule.trailing_pct:
                return i, ret
        if rule.cut_1bar_neg and held == 1 and ret < 0:
            return i, ret
        if rule.cut_short_thr > -100 and held == rule.cut_short_at and ret * 100 < rule.cut_short_thr:
            return i, ret
        if rule.max_hold > 0 and held >= rule.max_hold:
            return i, ret
    last = n - 1
    if last <= entry_pos:
        return entry_pos, 0.0
    return last, close[last] / ec - 1.0


def evaluate2(cache, threshold, rule, is_quiet, start, end, cost, since_years):
    """evaluate variant that uses simulate2 (hard SL aware)."""
    trades = []
    for symbol, (close, val, dt_idx) in cache.items():
        in_period = np.ones(len(dt_idx), dtype=bool)
        if start is not None:
            in_period &= (dt_idx >= start)
        if end is not None:
            in_period &= (dt_idx < end)
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
            if pos >= len(close) - 1:
                continue
            exit_pos, gross_ret = simulate2(close, int(pos), rule)
            if exit_pos == pos:
                continue
            trades.append({"net_ret": gross_ret - cost,
                           "held": exit_pos - pos})
    if not trades:
        return {"n": 0, "win%": 0, "mean%": 0, "median%": 0, "held": 0,
                "total%": 0, "MDD%": 0, "Sharpe_ann": 0, "PF": 0}
    df = pd.DataFrame(trades)
    rets = df["net_ret"].to_numpy()
    win = float((rets > 0).mean() * 100)
    mean = float(rets.mean() * 100)
    median = float(np.median(rets) * 100)
    held = float(df["held"].mean())
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


# ---------------------------------------------------------------------------
# Task 1: fine exit-rule grid
# ---------------------------------------------------------------------------
def progress_append(msg: str):
    log = OUT_DIR / "PROGRESS.md"
    ts = pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M:%S")
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"- [{ts}] {msg}\n")


def task1(strategy: str, interval: str, universe_top: int = 300,
          since_years: float = 6.0):
    threshold = BEST_THRESHOLD.get((strategy, interval), 60)
    cost = COST_RT["kr"]
    is_quiet = (strategy == "quiet_bottom")
    since = NOW - pd.DateOffset(years=int(since_years))

    progress_append(f"task1 start: {strategy}/{interval} threshold={threshold} "
                    f"universe_top={universe_top}")

    cache = build_cache("kr", strategy, interval, universe_top)
    rules = task1_rule_grid(interval)
    print(f"\n=== Task1 KR {strategy}/{interval} threshold={threshold} "
          f"rules={len(rules)} ===", flush=True)

    rows = []
    t0 = time.time()
    for i, rule in enumerate(rules, 1):
        s = evaluate2(cache, threshold, rule, is_quiet,
                      start=since, end=None, cost=cost, since_years=since_years)
        row = {
            "strategy": strategy, "interval": interval,
            "threshold": threshold, "rule": rule.name,
            "max_hold": rule.max_hold,
            "trailing_pct": rule.trailing_pct,
            "take_profit_pct": rule.take_profit_pct,
            "hard_sl": getattr(rule, "_hard_sl", None),
            "cut_3bar_neg": rule.cut_short_thr > -100,
            **s,
        }
        rows.append(row)
        if i % 20 == 0 or i == len(rules):
            print(f"  [{i}/{len(rules)}] elapsed {time.time()-t0:.1f}s "
                  f"last rule={rule.name} n={s['n']} sharpe={s['Sharpe_ann']}",
                  flush=True)
    out = pd.DataFrame(rows).sort_values("Sharpe_ann", ascending=False)
    out_csv = OUT_DIR / f"task1_{strategy}_{interval}.csv"
    out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"  saved: {out_csv}", flush=True)
    top5 = out.head(5)[["rule", "n", "win%", "mean%", "MDD%", "Sharpe_ann", "PF"]]
    print(top5.to_string(index=False), flush=True)
    progress_append(f"task1 done: {strategy}/{interval} best_sharpe="
                    f"{out['Sharpe_ann'].iloc[0]} rule={out['rule'].iloc[0]} "
                    f"elapsed={time.time()-t0:.1f}s")
    return out


# ---------------------------------------------------------------------------
# Task 2: IS / OOS split
# ---------------------------------------------------------------------------
def task2(strategy: str, interval: str, universe_top: int = 300, top_k: int = 30,
          use_task1_topk: bool = True):
    """IS 2020-05~2024-04 으로 best 청산룰 top_k 선정 → OOS 2024-05~2026-05 평가.

    use_task1_topk=True 면 Task1 결과 csv 에서 Sharpe top_k 룰만 평가 (속도 30x).
    """
    threshold = BEST_THRESHOLD.get((strategy, interval), 60)
    cost = COST_RT["kr"]
    is_quiet = (strategy == "quiet_bottom")

    is_start = pd.Timestamp("2020-05-01")
    is_end = pd.Timestamp("2024-05-01")
    oos_start = pd.Timestamp("2024-05-01")
    oos_end = pd.Timestamp("2026-05-18")

    is_years = (is_end - is_start).days / 365.25
    oos_years = (oos_end - oos_start).days / 365.25

    progress_append(f"task2 start: {strategy}/{interval} threshold={threshold} "
                    f"IS={is_start.date()}~{is_end.date()} OOS={oos_start.date()}~{oos_end.date()} "
                    f"use_task1_topk={use_task1_topk}")

    cache = build_cache("kr", strategy, interval, universe_top)
    full_rules = task1_rule_grid(interval)
    if use_task1_topk:
        t1_csv = OUT_DIR / f"task1_{strategy}_{interval}.csv"
        if not t1_csv.exists():
            print(f"  WARN: task1 csv missing — falling back to full grid")
            rules = full_rules
        else:
            t1 = pd.read_csv(t1_csv).sort_values("Sharpe_ann", ascending=False).head(top_k)
            keep_names = set(t1["rule"].tolist())
            rules = [r for r in full_rules if r.name in keep_names]
            print(f"  using top {len(rules)}/{len(full_rules)} rules from task1 csv")
    else:
        rules = full_rules
    print(f"\n=== Task2 KR {strategy}/{interval} rules={len(rules)} IS/OOS split ===",
          flush=True)

    rows = []
    t0 = time.time()
    for i, rule in enumerate(rules, 1):
        is_s = evaluate2(cache, threshold, rule, is_quiet,
                        start=is_start, end=is_end, cost=cost, since_years=is_years)
        oos_s = evaluate2(cache, threshold, rule, is_quiet,
                         start=oos_start, end=oos_end, cost=cost, since_years=oos_years)
        rows.append({
            "strategy": strategy, "interval": interval,
            "threshold": threshold, "rule": rule.name,
            "max_hold": rule.max_hold, "trailing_pct": rule.trailing_pct,
            "take_profit_pct": rule.take_profit_pct,
            "hard_sl": getattr(rule, "_hard_sl", None),
            "cut_3bar_neg": rule.cut_short_thr > -100,
            "IS_n": is_s["n"], "IS_win%": is_s["win%"],
            "IS_mean%": is_s["mean%"], "IS_MDD%": is_s["MDD%"],
            "IS_Sharpe": is_s["Sharpe_ann"], "IS_PF": is_s["PF"],
            "OOS_n": oos_s["n"], "OOS_win%": oos_s["win%"],
            "OOS_mean%": oos_s["mean%"], "OOS_MDD%": oos_s["MDD%"],
            "OOS_Sharpe": oos_s["Sharpe_ann"], "OOS_PF": oos_s["PF"],
            "robust%": round(100 * oos_s["Sharpe_ann"] / is_s["Sharpe_ann"], 1)
            if is_s["Sharpe_ann"] not in (0, None) else 0.0,
        })
        if i % 30 == 0 or i == len(rules):
            print(f"  [{i}/{len(rules)}] elapsed {time.time()-t0:.1f}s",
                  flush=True)
    out = pd.DataFrame(rows)
    # rank by IS Sharpe (selection criterion), report OOS as out-of-sample
    out = out.sort_values("IS_Sharpe", ascending=False)
    out_csv = OUT_DIR / f"task2_{strategy}_{interval}.csv"
    out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"  saved: {out_csv}", flush=True)
    top = out.head(top_k)[["rule", "IS_n", "IS_Sharpe", "OOS_n", "OOS_Sharpe", "robust%"]]
    print(top.to_string(index=False), flush=True)
    progress_append(f"task2 done: {strategy}/{interval} "
                    f"IS_best_sharpe={out['IS_Sharpe'].iloc[0]} "
                    f"OOS_sharpe_at_IS_best={out['OOS_Sharpe'].iloc[0]} "
                    f"robust={out['robust%'].iloc[0]}% "
                    f"elapsed={time.time()-t0:.1f}s")
    return out


# ---------------------------------------------------------------------------
# Task 3: universe size sensitivity
# ---------------------------------------------------------------------------
def task3(strategy: str, interval: str, since_years: float = 6.0):
    """top 100 / 300 / 500 / all 로 universe 바꿔서 Sharpe 변화 확인.

    best 청산룰은 round1 결과 (h252/52w + tr20 + TP30) 고정.
    """
    threshold = BEST_THRESHOLD.get((strategy, interval), 60)
    cost = COST_RT["kr"]
    is_quiet = (strategy == "quiet_bottom")
    since = NOW - pd.DateOffset(years=int(since_years))

    if interval == "1d":
        rule = ExitRule(name="h252_tr20_TP30", max_hold=252,
                        trailing_pct=0.20, take_profit_pct=0.30)
    else:
        rule = ExitRule(name="h52w_tr20_TP30", max_hold=52,
                        trailing_pct=0.20, take_profit_pct=0.30)
    rule._hard_sl = None  # type: ignore[attr-defined]

    sizes = [100, 300, 500, 800, -1]  # -1 → all available KR parquets
    progress_append(f"task3 start: {strategy}/{interval} threshold={threshold} "
                    f"sizes={sizes} rule={rule.name}")

    rows = []
    t0 = time.time()
    for top in sizes:
        cache = build_cache("kr", strategy, interval, top)
        s = evaluate2(cache, threshold, rule, is_quiet,
                      start=since, end=None, cost=cost, since_years=since_years)
        rows.append({
            "strategy": strategy, "interval": interval,
            "threshold": threshold, "universe_top": top,
            "n_symbols": len(cache),
            "rule": rule.name,
            **s,
        })
        print(f"  top={top}: n_symbols={len(cache)} n_trades={s['n']} "
              f"sharpe={s['Sharpe_ann']} win={s['win%']}%", flush=True)
    out = pd.DataFrame(rows)
    out_csv = OUT_DIR / f"task3_{strategy}_{interval}.csv"
    out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"  saved: {out_csv}", flush=True)
    progress_append(f"task3 done: {strategy}/{interval} elapsed={time.time()-t0:.1f}s")
    return out


# ---------------------------------------------------------------------------
# Task 4: entry timing sensitivity (t vs t+1 vs t+2)
# ---------------------------------------------------------------------------
def task4(strategy: str, interval: str, universe_top: int = 300,
          since_years: float = 6.0):
    """진입 시점을 entry_pos vs entry_pos+1 vs entry_pos+2 로 바꿔서 Sharpe 변화.

    entry_pos+0: 시그널 봉(t) 종가 진입 (현재 default — 미세 룩어헤드)
    entry_pos+1: t+1 종가 진입 (룩어헤드 무관, 다음 봉 시그널 이미 확정 후)
    entry_pos+2: t+2 종가 진입 (시그널 후 1봉 지나 진입 → 슬리피지 보수적)
    """
    threshold = BEST_THRESHOLD.get((strategy, interval), 60)
    cost = COST_RT["kr"]
    is_quiet = (strategy == "quiet_bottom")
    since = NOW - pd.DateOffset(years=int(since_years))

    if interval == "1d":
        rule = ExitRule(name="h252_tr25_TP40", max_hold=252,
                        trailing_pct=0.25, take_profit_pct=0.40)
    else:
        rule = ExitRule(name="h78w_tr20_TP40", max_hold=78,
                        trailing_pct=0.20, take_profit_pct=0.40)
    rule._hard_sl = None  # type: ignore[attr-defined]

    progress_append(f"task4 start: {strategy}/{interval} threshold={threshold} "
                    f"rule={rule.name}")

    cache = build_cache("kr", strategy, interval, universe_top)

    rows = []
    t0 = time.time()
    for shift in (0, 1, 2):
        trades = []
        for symbol, (close, val, dt_idx) in cache.items():
            in_period = (dt_idx >= since)
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
                shifted = pos + shift
                if shifted >= len(close) - 1:
                    continue
                exit_pos, gross_ret = simulate2(close, int(shifted), rule)
                if exit_pos == shifted:
                    continue
                trades.append({"net_ret": gross_ret - cost,
                               "held": exit_pos - shifted})
        if not trades:
            s = {"n": 0, "Sharpe_ann": 0.0}
        else:
            d = pd.DataFrame(trades)
            r = d["net_ret"].to_numpy()
            sharpe_pt = r.mean() / r.std() if r.std() > 0 else 0.0
            annual_factor = np.sqrt(max(1, len(r)) / since_years)
            sharpe_ann = float(sharpe_pt * annual_factor)
            s = {"n": int(len(r)),
                 "win%": round(float((r > 0).mean() * 100), 1),
                 "mean%": round(float(r.mean() * 100), 2),
                 "Sharpe_ann": round(sharpe_ann, 2)}
        rows.append({"strategy": strategy, "interval": interval,
                     "threshold": threshold, "rule": rule.name,
                     "entry_shift_bars": shift, **s})
        print(f"  shift={shift}: n={s['n']} sharpe={s['Sharpe_ann']}", flush=True)
    out = pd.DataFrame(rows)
    out_csv = OUT_DIR / f"task4_{strategy}_{interval}.csv"
    out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"  saved: {out_csv}", flush=True)
    progress_append(f"task4 done: {strategy}/{interval} elapsed={time.time()-t0:.1f}s")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(prog="kr_round2")
    p.add_argument("task", choices=["task1", "task2", "task3", "task4"])
    p.add_argument("--strategy", choices=list(STRATEGIES), required=True)
    p.add_argument("--interval", choices=["1d", "1w"], required=True)
    p.add_argument("--universe-top", type=int, default=300)
    args = p.parse_args(argv)

    if args.task == "task1":
        task1(args.strategy, args.interval, args.universe_top)
    elif args.task == "task2":
        task2(args.strategy, args.interval, args.universe_top)
    elif args.task == "task3":
        task3(args.strategy, args.interval)
    elif args.task == "task4":
        task4(args.strategy, args.interval, args.universe_top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
