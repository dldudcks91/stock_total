"""Agent U — US Round 2 미세 튜닝 + OOS + Universe 민감도.

기능:
  1. signal/score/close 캐시를 한 번 만들고 (build_cache) 메모리에 보관
  2. 임의의 (threshold, ExitRule, period_mask) 조합으로 빠르게 백테스트
  3. CLI 서브커맨드:
     - task1   : 청산룰 sweep 그리드 (TP × hold × SL × cut3d, trail 고정)
     - task2   : IS/OOS 분할 평가 (베스트 룰을 IS 에서 선정 → OOS 평가)
     - task3   : Universe 민감도 (top100/300/1000/all)
     - task4   : 섹터 분포 (signal 별 섹터 카운트, FDR 매핑 가능 시)

룩어헤드 안전:
  - signal/score 는 reset_index 한 raw df 에 적용 (각 strategy 가 t 시점까지만 본다)
  - 진입은 t 봉의 close 로 모델링, exit 는 entry+1 부터 시뮬레이션 (체결 lag)

CLI:
  .venv/Scripts/python.exe -m scripts.optimize.us_round2 task1 --strategy trend_pullback --interval 1d
  .venv/Scripts/python.exe -m scripts.optimize.us_round2 task2 --strategy trend_pullback --interval 1d
  .venv/Scripts/python.exe -m scripts.optimize.us_round2 task3 --strategy trend_pullback --interval 1d
  .venv/Scripts/python.exe -m scripts.optimize.us_round2 task4 --strategy trend_pullback --interval 1d
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.optimize.threshold_grid import (  # noqa: E402
    ExitRule, STRATEGIES, US_DIR, load_stock, simulate, strategy_params,
    _summarize_trades, BARS_PER_YEAR, COST_RT, MIN_BARS,
)

OUT_DIR = ROOT / "scripts" / "out" / "optimize" / "round2" / "us"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ASSET = "us"

# 기간 표준
PERIOD_FULL = (pd.Timestamp("2020-05-01"), pd.Timestamp("2026-05-18"))
PERIOD_IS = (pd.Timestamp("2020-05-01"), pd.Timestamp("2024-05-01"))
PERIOD_OOS = (pd.Timestamp("2024-05-01"), pd.Timestamp("2026-05-18"))


# ---------------------------------------------------------------------------
# universe (시총 + 거래대금 cuts)
# ---------------------------------------------------------------------------
_LISTING_CACHE_PATH = OUT_DIR / "_nasdaq_listing.parquet"


def _get_listing() -> pd.DataFrame:
    if _LISTING_CACHE_PATH.exists():
        return pd.read_parquet(_LISTING_CACHE_PATH)
    import FinanceDataReader as fdr
    import time as _time
    last_err = None
    for attempt in range(4):
        try:
            df = fdr.StockListing("NASDAQ")
            df.to_parquet(_LISTING_CACHE_PATH)
            return df
        except Exception as e:
            last_err = e
            _time.sleep(2 + attempt * 3)
    raise RuntimeError(f"FDR NASDAQ listing failed: {last_err}")


def us_top_universe(top_n: int) -> list[str]:
    """FDR NASDAQ 상위 N. listing 순서 기준 (캐시)."""
    df = _get_listing()
    return df["Symbol"].astype(str).head(top_n).tolist()


def us_all_universe() -> list[str]:
    return [p.stem for p in sorted(US_DIR.glob("*.parquet")) if not p.stem.startswith("_")]


# ---------------------------------------------------------------------------
# 캐시: 종목별 signal/score/close/dt 계산 1회
# ---------------------------------------------------------------------------
@dataclass
class SymCache:
    symbol: str
    close: np.ndarray       # 일봉 또는 주봉 close
    scores: np.ndarray      # 봉당 score (trend_*) 또는 binary*100 (quiet_bottom)
    mask_full: np.ndarray   # PERIOD_FULL 이내
    mask_is: np.ndarray     # IS 구간
    mask_oos: np.ndarray    # OOS 구간
    dt_arr: np.ndarray      # YYYY-MM-DD 문자열


def build_cache(strategy: str, interval: str, universe: list[str],
                verbose: bool = True) -> list[SymCache]:
    strat = STRATEGIES[strategy]
    base_params = strategy_params(strategy, ASSET, interval)
    is_binary = (strategy == "quiet_bottom")
    min_bars = MIN_BARS[interval]
    universe_set = set(universe)

    files = [p for p in sorted(US_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    cache: list[SymCache] = []
    n_skip = 0
    t0 = time.time()

    for p in files:
        if p.stem not in universe_set:
            continue
        try:
            df = load_stock(p, interval)
        except Exception:
            n_skip += 1
            continue
        if df is None or df.empty or len(df) < min_bars:
            n_skip += 1
            continue
        try:
            df_reset = df.reset_index(drop=True)
            if is_binary:
                sig = strat.signal(df_reset, base_params)
                score_arr = sig.astype("float64") * 100.0
            else:
                score_arr = strat.score(df_reset, base_params)
        except Exception:
            n_skip += 1
            continue
        close = df["close"].astype("float64").to_numpy()
        dt_index = pd.DatetimeIndex(df.index)
        dt_arr = np.array([d.strftime("%Y-%m-%d") for d in dt_index])
        m_full = (dt_index >= PERIOD_FULL[0]) & (dt_index < PERIOD_FULL[1])
        m_is = (dt_index >= PERIOD_IS[0]) & (dt_index < PERIOD_IS[1])
        m_oos = (dt_index >= PERIOD_OOS[0]) & (dt_index < PERIOD_OOS[1])
        cache.append(SymCache(
            symbol=p.stem,
            close=close,
            scores=np.asarray(pd.Series(score_arr).fillna(0).to_numpy(), dtype="float64"),
            mask_full=np.asarray(m_full),
            mask_is=np.asarray(m_is),
            mask_oos=np.asarray(m_oos),
            dt_arr=dt_arr,
        ))
        if verbose and len(cache) % 50 == 0:
            print(f"    cache {len(cache)} (skipped {n_skip}, "
                  f"elapsed {time.time()-t0:.1f}s)", flush=True)
    if verbose:
        print(f"  cache built: {len(cache)} symbols, skipped {n_skip}, "
              f"elapsed {time.time()-t0:.1f}s", flush=True)
    return cache


# ---------------------------------------------------------------------------
# 백테스트 (threshold + rule + period_mask attr)
# ---------------------------------------------------------------------------
def run_one(cache: list[SymCache], threshold: float, rule: ExitRule,
            period: str, interval: str) -> dict:
    """period ∈ {'full','is','oos'}."""
    cost = COST_RT[ASSET]
    trades = []
    for rec in cache:
        scores = rec.scores
        if period == "full":
            mask = rec.mask_full
        elif period == "is":
            mask = rec.mask_is
        elif period == "oos":
            mask = rec.mask_oos
        else:
            raise ValueError(period)
        sig_th = (scores >= threshold).astype("int8") * mask.astype("int8")
        if sig_th.sum() == 0:
            continue
        prev = np.concatenate([[0], sig_th[:-1]])
        entries_idx = np.where((sig_th == 1) & (prev == 0))[0]
        if len(entries_idx) == 0:
            continue
        last_exit = -1
        for pos in entries_idx:
            if pos <= last_exit:
                continue
            exit_pos, gross = simulate(rec.close, int(pos), rule)
            net = gross - cost
            trades.append({
                "symbol": rec.symbol,
                "entry_dt": rec.dt_arr[pos],
                "exit_dt": rec.dt_arr[exit_pos] if exit_pos < len(rec.dt_arr) else rec.dt_arr[-1],
                "held_bars": exit_pos - pos,
                "gross_ret": gross,
                "net_ret": net,
            })
            last_exit = exit_pos
    bars_per_year = BARS_PER_YEAR[interval]
    return _summarize_trades(trades, bars_per_year), trades


# ---------------------------------------------------------------------------
# Task 1 — 청산룰 sweep
# ---------------------------------------------------------------------------
def build_exit_grid(interval: str) -> list[ExitRule]:
    """trail 고정 20%, TP×hold×SL×cut_3d sweep.

    bar 환산: 1d → days, 1w → weeks.
    SL 은 simulate 에 없으므로 trailing 으로 근사 → 별도 stop_loss_pct 필드 추가가 필요.
    여기선 SL 을 trailing 의 dual rule 로 단순 처리 — net_ret < -SL_abs 시 exit (즉시).
    구현 단순화를 위해 cut_early_neg 변형(held<=3 & ret<-SL) 으로 대체.

    Actually we'll extend ExitRule via subclass below.
    """
    if interval == "1d":
        holds = [120, 180, 252, 365]
    else:  # 1w
        holds = [26, 39, 52, 78]
    tps = [0.20, 0.25, 0.30, 0.40, 0.50, 0.0]
    sls = [0.10, 0.15, 0.20, 0.0]
    trail_fixed = 0.20
    rules: list[Rule2] = []
    for h in holds:
        for tp in tps:
            for sl in sls:
                for cut3 in (False, True):
                    name = f"hold{h}_tr{int(trail_fixed*100)}_tp{int(tp*100)}_sl{int(sl*100)}_cut3{int(cut3)}"
                    rules.append(Rule2(
                        name=name,
                        max_hold=h,
                        trailing_pct=trail_fixed,
                        take_profit_pct=tp,
                        stop_loss_pct=sl,
                        cut3d_neg=cut3,
                    ))
    return rules


@dataclass
class Rule2:
    """확장 ExitRule — stop_loss_pct, cut3d_neg 추가."""
    name: str
    max_hold: int = 0
    trailing_pct: float = 0.0
    take_profit_pct: float = 0.0
    stop_loss_pct: float = 0.0  # 손절: ret <= -SL → exit
    cut3d_neg: bool = False     # held in (1,2,3) 이고 ret<0 이면 컷


def simulate2(close: np.ndarray, entry_pos: int, rule: Rule2) -> tuple[int, float]:
    n = len(close)
    if entry_pos >= n - 1:
        return entry_pos, 0.0
    ec = close[entry_pos]
    if not np.isfinite(ec) or ec <= 0:
        return entry_pos, 0.0
    peak = ec
    for i in range(entry_pos + 1, n):
        held = i - entry_pos
        ci = close[i]
        if not np.isfinite(ci) or ci <= 0:
            continue
        peak = max(peak, ci)
        ret = ci / ec - 1.0
        if rule.take_profit_pct > 0 and ret >= rule.take_profit_pct:
            return i, ret
        if rule.stop_loss_pct > 0 and ret <= -rule.stop_loss_pct:
            return i, ret
        if rule.trailing_pct > 0 and peak > ec:
            if ci / peak - 1.0 <= -rule.trailing_pct:
                return i, ret
        if rule.cut3d_neg and 1 <= held <= 3 and ret < 0:
            return i, ret
        if rule.max_hold > 0 and held >= rule.max_hold:
            return i, ret
    last = n - 1
    return last, close[last] / ec - 1.0


def run_one_rule2(cache: list[SymCache], threshold: float, rule: Rule2,
                  period: str, interval: str) -> dict:
    cost = COST_RT[ASSET]
    trades = []
    for rec in cache:
        scores = rec.scores
        if period == "full":
            mask = rec.mask_full
        elif period == "is":
            mask = rec.mask_is
        elif period == "oos":
            mask = rec.mask_oos
        else:
            raise ValueError(period)
        sig_th = (scores >= threshold).astype("int8") * mask.astype("int8")
        if sig_th.sum() == 0:
            continue
        prev = np.concatenate([[0], sig_th[:-1]])
        entries_idx = np.where((sig_th == 1) & (prev == 0))[0]
        if len(entries_idx) == 0:
            continue
        last_exit = -1
        for pos in entries_idx:
            if pos <= last_exit:
                continue
            exit_pos, gross = simulate2(rec.close, int(pos), rule)
            net = gross - cost
            trades.append({
                "symbol": rec.symbol,
                "held_bars": exit_pos - pos,
                "gross_ret": gross,
                "net_ret": net,
            })
            last_exit = exit_pos
    bars_per_year = BARS_PER_YEAR[interval]
    return _summarize_trades(trades, bars_per_year)


# ---------------------------------------------------------------------------
# 진행 로그
# ---------------------------------------------------------------------------
PROGRESS = OUT_DIR / "PROGRESS.md"


def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"- [{ts}] {msg}"
    print(line, flush=True)
    with PROGRESS.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Default thresholds per (strategy, interval)
# ---------------------------------------------------------------------------
DEFAULT_TH = {
    ("trend_pullback", "1d"): 70.0,
    ("trend_pullback", "1w"): 70.0,
    ("trend_chase",    "1d"): 60.0,
}


# ---------------------------------------------------------------------------
# Task 1 - exit-rule grid
# ---------------------------------------------------------------------------
def cmd_task1(strategy: str, interval: str, top_n: int = 300):
    log(f"task1 start — {strategy}/{interval}, top{top_n}")
    universe = us_top_universe(top_n)
    cache = build_cache(strategy, interval, universe)
    if not cache:
        log("task1: no cache built — abort")
        return
    th = DEFAULT_TH[(strategy, interval)]
    rules = build_exit_grid(interval)
    log(f"task1: threshold={th}, {len(rules)} rules over {len(cache)} symbols")
    rows = []
    t0 = time.time()
    for i, rule in enumerate(rules, 1):
        s = run_one_rule2(cache, th, rule, "full", interval)
        rows.append({
            "strategy": strategy, "interval": interval, "threshold": th,
            **asdict(rule), **s,
        })
        if i % 20 == 0 or i == len(rules):
            log(f"  task1 {i}/{len(rules)} elapsed {time.time()-t0:.1f}s")
    df = pd.DataFrame(rows)
    df = df.sort_values("sharpe", ascending=False)
    out_csv = OUT_DIR / f"task1_{strategy}_{interval}.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    log(f"task1 saved: {out_csv}  (best sharpe={df.iloc[0]['sharpe']:.2f}, rule={df.iloc[0]['name']})")


# ---------------------------------------------------------------------------
# Task 2 - IS/OOS
# ---------------------------------------------------------------------------
def cmd_task2(strategy: str, interval: str, top_n: int = 300):
    log(f"task2 start — {strategy}/{interval} IS/OOS")
    # Task1 결과가 있다면 그 best rule. 없으면 base rule.
    t1_csv = OUT_DIR / f"task1_{strategy}_{interval}.csv"
    if not t1_csv.exists():
        log(f"task2: {t1_csv} not found — run task1 first")
        return
    universe = us_top_universe(top_n)
    cache = build_cache(strategy, interval, universe)
    th = DEFAULT_TH[(strategy, interval)]

    t1 = pd.read_csv(t1_csv)
    # IS-best 룰을 다시 IS 에서 재평가, OOS 에서도 평가
    rows = []
    # IS Sharpe 로 정렬해 top 10 룰 추출
    is_rows = []
    log(f"task2: IS evaluating all {len(t1)} rules...")
    t0 = time.time()
    for _, r in t1.iterrows():
        rule = Rule2(
            name=r["name"], max_hold=int(r["max_hold"]),
            trailing_pct=float(r["trailing_pct"]), take_profit_pct=float(r["take_profit_pct"]),
            stop_loss_pct=float(r["stop_loss_pct"]), cut3d_neg=bool(r["cut3d_neg"]),
        )
        s_is = run_one_rule2(cache, th, rule, "is", interval)
        s_oos = run_one_rule2(cache, th, rule, "oos", interval)
        rows.append({
            "rule_name": rule.name,
            "max_hold": rule.max_hold, "trail": rule.trailing_pct,
            "tp": rule.take_profit_pct, "sl": rule.stop_loss_pct, "cut3d": rule.cut3d_neg,
            "IS_n": s_is["n"], "IS_win%": round(s_is["win_pct"], 1),
            "IS_mean%": round(s_is["mean_pct"], 2), "IS_Sharpe": round(s_is["sharpe"], 2),
            "IS_PF": round(s_is["profit_factor"], 2),
            "OOS_n": s_oos["n"], "OOS_win%": round(s_oos["win_pct"], 1),
            "OOS_mean%": round(s_oos["mean_pct"], 2), "OOS_Sharpe": round(s_oos["sharpe"], 2),
            "OOS_PF": round(s_oos["profit_factor"], 2),
        })
    log(f"  task2 done in {time.time()-t0:.1f}s")
    df = pd.DataFrame(rows).sort_values("IS_Sharpe", ascending=False)
    out_csv = OUT_DIR / f"task2_{strategy}_{interval}.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    top1 = df.iloc[0]
    log(f"task2 saved: {out_csv}  IS-best {top1['rule_name']} "
        f"IS Sharpe={top1['IS_Sharpe']:.2f} → OOS Sharpe={top1['OOS_Sharpe']:.2f}")


# ---------------------------------------------------------------------------
# Task 3 - Universe 민감도
# ---------------------------------------------------------------------------
def cmd_task3(strategy: str, interval: str):
    log(f"task3 start — universe sensitivity {strategy}/{interval}")
    th = DEFAULT_TH[(strategy, interval)]
    # Round 1 의 검증 룰 사용 — hold long, trail 20%, TP 30%
    if interval == "1d":
        rule = Rule2(name="hold252_tr20_tp30", max_hold=252,
                     trailing_pct=0.20, take_profit_pct=0.30)
    else:
        rule = Rule2(name="hold52w_tr20_tp30", max_hold=52,
                     trailing_pct=0.20, take_profit_pct=0.30)

    rows = []
    sizes = [
        ("top100", us_top_universe(100)),
        ("top300", us_top_universe(300)),
        ("top1000", us_top_universe(1000)),
        ("all", us_all_universe()),
    ]
    # 거래대금 컷: top1000 universe 안에서 평균 amount > 1M USD
    # (단순화: amount 컷용 cache 별도 빌드)
    for label, univ in sizes:
        log(f"  task3: {label} (n_universe={len(univ)})")
        cache = build_cache(strategy, interval, univ, verbose=False)
        if not cache:
            rows.append({"universe": label, "n_universe_in": len(univ),
                         "n_cached": 0, "n_trades": 0})
            continue
        s = run_one_rule2(cache, th, rule, "full", interval)
        rows.append({
            "universe": label,
            "n_universe_in": len(univ),
            "n_cached": len(cache),
            "n_trades": s["n"],
            "win%": round(s["win_pct"], 1),
            "mean%": round(s["mean_pct"], 2),
            "Sharpe": round(s["sharpe"], 2),
            "MDD%": round(s["mdd_pct"], 1),
            "PF": round(s["profit_factor"], 2),
        })
        log(f"    n={s['n']} mean%={s['mean_pct']:.2f} Sharpe={s['sharpe']:.2f}")

    # 거래대금 컷: top1000 cache 에서 mean amount 컷
    log("  task3: liquidity filter on top1000 (mean amount > 1M USD)")
    cache_1000 = build_cache(strategy, interval, us_top_universe(1000), verbose=False)
    # 종목별 평균 amount 추가 계산
    keep = []
    for rec in cache_1000:
        p = US_DIR / f"{rec.symbol}.parquet"
        try:
            raw = pd.read_parquet(p)
            if "Volume" in raw.columns and "Close" in raw.columns:
                amt = float((raw["Close"] * raw["Volume"]).tail(252).mean())
                if amt > 1e6:
                    keep.append(rec)
        except Exception:
            continue
    log(f"    liquid (amt>1M, top1000 base): {len(keep)} of {len(cache_1000)}")
    if keep:
        s = run_one_rule2(keep, th, rule, "full", interval)
        rows.append({
            "universe": "top1000_liquid1M",
            "n_universe_in": 1000,
            "n_cached": len(keep),
            "n_trades": s["n"],
            "win%": round(s["win_pct"], 1),
            "mean%": round(s["mean_pct"], 2),
            "Sharpe": round(s["sharpe"], 2),
            "MDD%": round(s["mdd_pct"], 1),
            "PF": round(s["profit_factor"], 2),
        })
    df = pd.DataFrame(rows)
    out_csv = OUT_DIR / f"task3_{strategy}_{interval}.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    log(f"task3 saved: {out_csv}")


# ---------------------------------------------------------------------------
# Task 4 - 섹터 분포 (옵션)
# ---------------------------------------------------------------------------
def cmd_task4(strategy: str, interval: str, top_n: int = 300):
    log(f"task4 start — sector distribution {strategy}/{interval}")
    try:
        import FinanceDataReader as fdr
        listing = fdr.StockListing("NASDAQ")
    except Exception as e:
        log(f"task4 BLOCKED: FDR NASDAQ listing fail: {e}")
        return
    # FDR NASDAQ 에 IndustryCode 또는 Industry 컬럼이 있는지 확인
    sector_col = None
    for c in ("Sector", "Industry", "IndustryCode", "SectorName", "IndustryName"):
        if c in listing.columns:
            sector_col = c
            break
    if sector_col is None:
        # 컬럼 명세 로깅하고 종료
        log(f"task4 BLOCKED: no sector column in FDR listing. cols={list(listing.columns)[:20]}")
        return
    log(f"task4: using FDR column '{sector_col}'")
    sym_to_sec = dict(zip(listing["Symbol"].astype(str), listing[sector_col].astype(str)))

    universe = us_top_universe(top_n)
    cache = build_cache(strategy, interval, universe, verbose=False)
    th = DEFAULT_TH[(strategy, interval)]
    if interval == "1d":
        rule = Rule2(name="hold252_tr20_tp30", max_hold=252, trailing_pct=0.20, take_profit_pct=0.30)
    else:
        rule = Rule2(name="hold52w_tr20_tp30", max_hold=52, trailing_pct=0.20, take_profit_pct=0.30)

    # 종목별 trade collect → 섹터별 집계
    cost = COST_RT[ASSET]
    by_sec: dict[str, list[float]] = {}
    for rec in cache:
        scores = rec.scores
        mask = rec.mask_full
        sig_th = (scores >= th).astype("int8") * mask.astype("int8")
        if sig_th.sum() == 0:
            continue
        prev = np.concatenate([[0], sig_th[:-1]])
        entries_idx = np.where((sig_th == 1) & (prev == 0))[0]
        last_exit = -1
        sec = sym_to_sec.get(rec.symbol, "Unknown")
        for pos in entries_idx:
            if pos <= last_exit:
                continue
            exit_pos, gross = simulate2(rec.close, int(pos), rule)
            net = gross - cost
            by_sec.setdefault(sec, []).append(net)
            last_exit = exit_pos
    rows = []
    for sec, rets in by_sec.items():
        if not rets:
            continue
        arr = np.array(rets)
        rows.append({
            "sector": sec, "n": len(arr),
            "win%": round(float((arr > 0).mean() * 100), 1),
            "mean%": round(float(arr.mean() * 100), 2),
            "median%": round(float(np.median(arr) * 100), 2),
        })
    df = pd.DataFrame(rows).sort_values("mean%", ascending=False)
    out_csv = OUT_DIR / f"task4_{strategy}_{interval}.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    log(f"task4 saved: {out_csv}  ({len(rows)} sectors)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    for c in ("task1", "task2", "task3", "task4"):
        s = sp.add_parser(c)
        s.add_argument("--strategy", required=True,
                       choices=["trend_pullback", "trend_chase"])
        s.add_argument("--interval", required=True, choices=["1d", "1w"])
        if c in ("task1", "task2", "task4"):
            s.add_argument("--top", type=int, default=300)
    args = ap.parse_args()

    if args.cmd == "task1":
        cmd_task1(args.strategy, args.interval, args.top)
    elif args.cmd == "task2":
        cmd_task2(args.strategy, args.interval, args.top)
    elif args.cmd == "task3":
        cmd_task3(args.strategy, args.interval)
    elif args.cmd == "task4":
        cmd_task4(args.strategy, args.interval, args.top)


if __name__ == "__main__":
    main()
