"""진입 타이밍 최적화 — score_threshold × exit_rule 그리드 백테스트.

핵심 아이디어:
  - 전략(trend_chase / trend_pullback / quiet_bottom) 의 신호 *진입* 시점만 사용.
  - 진입 후 보유/청산은 ExitRule 로 시뮬레이트 (max_hold, trailing, take_profit, cut_1w_neg).
  - score_threshold 와 ExitRule 을 그리드로 돌려 자산별 최적 조합을 찾는다.

룩어헤드 안전:
  - signal/score 는 reset_index 된 raw df 에 적용 → 각 strategy 모듈이 t 시점까지만 본다.
  - 진입은 signal=1 의 첫 봉 (0→1 전환). 같은 신호의 연속 1 은 무시.
  - exit 시뮬레이션은 entry+1 부터 시작 (체결 lag).

성과 지표 (per-trade compounded equity):
  n_trades, win_rate, mean_ret, median_ret, total_ret, MDD, Sharpe(annualized), profit_factor
  Sharpe 연환산 factor = sqrt( n_trades / lookback_years )

CLI:
  python -m scripts.optimize.threshold_grid \
      --asset kr --strategy trend_chase --interval 1d \
      --thresholds 60,70,75,80,85,90 \
      --exit "hold=8w,trail=0.15,tp=0.30"

  python -m scripts.optimize.threshold_grid --preset stage1
    → 각 (asset, strategy, interval) 에 대해 default exit + threshold 그리드 실행
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backtest.strategies import quiet_bottom, trend_chase, trend_pullback  # noqa: E402

CACHE_DIR = ROOT / "data" / "cache"
CRYPTO_1H_DIR = CACHE_DIR / "crypto" / "1h"
CRYPTO_1D_DIR = CACHE_DIR / "crypto" / "1d"
KR_DIR = CACHE_DIR / "kr"
US_DIR = CACHE_DIR / "us"

OUT_DIR = ROOT / "scripts" / "out" / "optimize"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 분석 기간 — 6 년 (충분한 trade 수와 다양한 시장 상황)
NOW = pd.Timestamp.utcnow().tz_localize(None).normalize()
LOOKBACK_YEARS = 6
SINCE = NOW - pd.DateOffset(years=LOOKBACK_YEARS)

STRATEGIES = {
    "trend_chase": trend_chase,
    "trend_pullback": trend_pullback,
    "quiet_bottom": quiet_bottom,
}

# 자산별 왕복 비용 (수수료 + 슬리피지)
COST_RT = {"crypto": 0.002, "kr": 0.003, "us": 0.002}

# 자산별 universe top-N
UNIVERSE_TOP = {"crypto": 200, "kr": 300, "us": 300}

# 인터벌별 봉/년 (Sharpe 연환산용; exit hold bar 수 환산용)
BARS_PER_YEAR = {"1h": 8760, "4h": 2190, "1d": 252, "1w": 52}

# 인터벌별 min_bars (워밍업)
MIN_BARS = {
    "1h": 720,    # ~30일
    "4h": 240,    # ~40일
    "1d": 120,    # ~6개월
    "1w": 120,    # ~2.3년 (quiet_bottom dd_lookback 104 충족)
}

CRYPTO_AGG = {
    "open": "first", "high": "max", "low": "min",
    "close": "last", "volume": "sum", "amount": "sum",
}
STOCK_AGG = {"Open": "first", "High": "max", "Low": "min",
             "Close": "last", "Volume": "sum"}


# ---------------------------------------------------------------------------
# data loaders
# ---------------------------------------------------------------------------
def _norm_stock_cols(df: pd.DataFrame) -> pd.DataFrame:
    rename = {c: c.lower() for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns}
    out = df.rename(columns=rename)
    if "amount" not in out.columns and "close" in out.columns and "volume" in out.columns:
        out["amount"] = out["close"].astype("float64") * out["volume"].astype("float64")
    return out


def load_stock(path: Path, interval: str) -> pd.DataFrame:
    """KR/US FDR 캐시 → interval 별 OHLCV (소문자, dt 인덱스)."""
    df = pd.read_parquet(path)
    if "Close" not in df.columns:
        return pd.DataFrame()
    df = df.sort_index()
    if interval == "1d":
        return _norm_stock_cols(df)
    if interval == "1w":
        w = df.resample("W-FRI").agg(STOCK_AGG).dropna()
        return _norm_stock_cols(w)
    raise ValueError(f"stock interval not supported: {interval}")


def load_crypto(path: Path, interval: str) -> pd.DataFrame:
    """Crypto Bitget 캐시 → interval 별 OHLCV (소문자, dt 인덱스).

    1h / 4h 는 1h raw 에서, 1d 는 1d 캐시 우선·없으면 1h 리샘플, 1w 는 1d 에서.
    """
    df = pd.read_parquet(path)
    if "timestamp" not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df = df.set_index("dt").sort_index()

    cols = [c for c in CRYPTO_AGG if c in df.columns]
    agg = {c: CRYPTO_AGG[c] for c in cols}

    if interval == "1h":
        return df[cols]
    if interval == "4h":
        return df.resample("4h", label="left", closed="left").agg(agg).dropna()
    if interval == "1d":
        return df.resample("1D", label="left", closed="left").agg(agg).dropna()
    if interval == "1w":
        return df.resample("W-MON", label="left", closed="left").agg(agg).dropna()
    raise ValueError(f"crypto interval not supported: {interval}")


# ---------------------------------------------------------------------------
# universe builders
# ---------------------------------------------------------------------------
def kr_universe(top_n: int) -> set:
    import FinanceDataReader as fdr
    df = fdr.StockListing("KOSPI").dropna(subset=["Marcap"]).sort_values("Marcap", ascending=False)
    return set(df["Code"].head(top_n).astype(str).tolist())


def us_universe(top_n: int) -> set:
    import FinanceDataReader as fdr
    df = fdr.StockListing("NASDAQ")
    return set(df["Symbol"].head(top_n).astype(str).tolist())


def crypto_universe(top_n: int) -> set:
    """1h 캐시 amount 합 상위 N."""
    scores: list[tuple[str, float]] = []
    for p in sorted(CRYPTO_1H_DIR.glob("*.parquet")):
        try:
            amt = pd.read_parquet(p, columns=["amount"])["amount"].sum()
            scores.append((p.stem, float(amt)))
        except Exception:
            continue
    scores.sort(key=lambda x: x[1], reverse=True)
    return {s for s, _ in scores[:top_n]}


def _files_for(asset: str, interval: str) -> list[Path]:
    if asset == "crypto":
        if interval == "1d":
            files = sorted(CRYPTO_1D_DIR.glob("*.parquet"))
            return files if files else sorted(CRYPTO_1H_DIR.glob("*.parquet"))
        return sorted(CRYPTO_1H_DIR.glob("*.parquet"))
    if asset == "kr":
        return [p for p in sorted(KR_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    if asset == "us":
        return [p for p in sorted(US_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    raise ValueError(asset)


def _loader(asset: str):
    if asset == "crypto":
        return load_crypto
    return load_stock


def _universe(asset: str, top_n: Optional[int] = None) -> set:
    n = top_n or UNIVERSE_TOP[asset]
    if asset == "kr":
        return kr_universe(n)
    if asset == "us":
        return us_universe(n)
    if asset == "crypto":
        return crypto_universe(n)
    raise ValueError(asset)


# ---------------------------------------------------------------------------
# spec lookup — dashboards/_recommendation.py 와 동일 파라미터 사용
# ---------------------------------------------------------------------------
def strategy_params(strategy: str, asset: str, interval: str) -> dict:
    """대시보드 _recommendation 의 spec dict 와 같은 TF별 파라미터 반환.

    threshold 는 호출자가 override 하므로 여기선 base 파라미터만.
    """
    is_stock = asset in ("kr", "us")

    if strategy == "trend_chase":
        if is_stock:
            if interval == "1d":
                return {}
            if interval == "1w":
                return {"base_lookback": 26, "fresh_big_th": 0.10, "max_prior_extension": 0.60}
        else:
            if interval == "1h":
                return {"ret_th": [0.010, 0.015, 0.020, 0.030], "base_lookback": 240,
                        "fresh_big_th": 0.015, "max_prior_extension": 0.20,
                        "amount_lookback": 720}
            if interval == "4h":
                return {"ret_th": [0.020, 0.030, 0.040, 0.060], "base_lookback": 60,
                        "fresh_big_th": 0.030, "max_prior_extension": 0.25,
                        "amount_lookback": 180}
            if interval == "1d":
                return {"ret_th": [0.04, 0.06, 0.09, 0.13], "base_lookback": 60,
                        "fresh_big_th": 0.06, "max_prior_extension": 0.40}
            if interval == "1w":
                return {"ret_th": [0.08, 0.12, 0.17, 0.25], "base_lookback": 26,
                        "fresh_big_th": 0.13, "max_prior_extension": 0.80,
                        "amount_lookback": 100}
    if strategy == "trend_pullback":
        if is_stock:
            if interval == "1d":
                return {}
            if interval == "1w":
                return {"rally_lookback": 26}
        else:
            if interval == "1h":
                return {"rally_lookback": 168, "rally_min_gain": 0.10, "depth_lookback": 48}
            if interval == "4h":
                return {"rally_lookback": 42, "rally_min_gain": 0.15, "depth_lookback": 30}
            if interval == "1d":
                return {}
            if interval == "1w":
                return {"rally_lookback": 26, "rally_min_gain": 0.60}
    if strategy == "quiet_bottom":
        return {}
    return {}


# ---------------------------------------------------------------------------
# exit-rule simulator (per-trade)
# ---------------------------------------------------------------------------
@dataclass
class ExitRule:
    name: str
    max_hold: int = 0              # 0 = no limit (bar 단위, interval 에 따라 의미 다름)
    trailing_pct: float = 0.0      # peak 대비 -x → exit
    take_profit_pct: float = 0.0   # entry 대비 +x → exit
    cut_early_neg: int = 0         # held==cut_early_neg 일 때 음수면 exit (0=off)


def simulate(close: np.ndarray, entry_pos: int, rule: ExitRule) -> tuple[int, float]:
    """진입 위치 entry_pos 부터 청산 위치/수익률 반환.

    체결 lag: 진입은 entry_pos 의 close, exit 도 close. (alert 발생 = entry_pos 다음 봉의 open 이
    이상적이나 close-to-close 로 단순화. simulate 내부에서 entry+1 부터 평가.)
    """
    n = len(close)
    if entry_pos >= n - 1:
        return entry_pos, 0.0
    ec = close[entry_pos]
    peak = ec
    for i in range(entry_pos + 1, n):
        held = i - entry_pos
        ci = close[i]
        if not np.isfinite(ci) or ci <= 0:
            continue
        peak = max(peak, ci)
        ret = ci / ec - 1.0
        # 1) take profit
        if rule.take_profit_pct > 0 and ret >= rule.take_profit_pct:
            return i, ret
        # 2) trailing from peak
        if rule.trailing_pct > 0 and peak > ec:
            if ci / peak - 1.0 <= -rule.trailing_pct:
                return i, ret
        # 3) cut early neg
        if rule.cut_early_neg > 0 and held == rule.cut_early_neg and ret < 0:
            return i, ret
        # 4) max hold
        if rule.max_hold > 0 and held >= rule.max_hold:
            return i, ret
    last = n - 1
    return last, close[last] / ec - 1.0


def collect_signals(
    asset: str, interval: str, strategy: str,
    universe: set, verbose: bool = True,
) -> pd.DataFrame:
    """각 심볼·전략의 (entry_pos, entry_dt, score, close_array_idx) 들 수집.

    return: rows of {symbol, entry_pos, entry_dt, score, close_array_id} +
            symbol->close_array dict 는 외부 호출자가 따로 보관.
    """
    raise NotImplementedError("use collect_entries instead")


def collect_entries(
    asset: str, interval: str, strategy: str,
    universe: set, verbose: bool = True,
) -> list[dict]:
    """심볼별 진입 시점 + close 시계열 수집.

    return: [
      {symbol, entry_pos, entry_dt, score, close_arr (np.ndarray)},
      ...
    ]
    close_arr 는 종목당 1번만 전달 (메모리 절약 위해 dict 로도 됨).
    여기선 entry 별로 close_arr 참조 (object reference 공유, 복사 X).
    """
    strat = STRATEGIES[strategy]
    base_params = strategy_params(strategy, asset, interval)
    loader = _loader(asset)
    files = _files_for(asset, interval)
    min_bars = MIN_BARS[interval]
    is_binary = (strategy == "quiet_bottom")

    out: list[dict] = []
    n_files = len(files)
    n_proc = 0
    n_skip = 0
    if verbose:
        print(f"  collect_entries[{asset}/{interval}/{strategy}]: {n_files} files, universe={len(universe)}", flush=True)

    for p in files:
        symbol = p.stem
        if symbol not in universe:
            continue
        try:
            df = loader(p, interval)
        except Exception as e:
            if verbose:
                print(f"    ! {symbol}: load fail {type(e).__name__}: {e}", flush=True)
            continue
        if df is None or df.empty or len(df) < min_bars:
            n_skip += 1
            continue
        try:
            df_reset = df.reset_index(drop=True)
            if is_binary:
                sig = strat.signal(df_reset, base_params)
                score_arr = sig.astype("float64") * 100.0  # binary: 진입=100
            else:
                score_arr = strat.score(df_reset, base_params)
                sig = (score_arr.fillna(0) > 0).astype("int8")
        except Exception as e:
            if verbose:
                print(f"    ! {symbol}: signal fail {type(e).__name__}: {e}", flush=True)
            continue
        sig = pd.Series(sig).reset_index(drop=True).astype("int8")
        score_arr = pd.Series(score_arr).reset_index(drop=True).astype("float64")
        # 0→1 전환만 (re-trigger 는 score-cut 단계에서 처리)
        sig_prev = sig.shift(1).fillna(0).astype("int8")

        # 전체 score 계열은 threshold 단계에서 필터링하므로, 여기선 "score>0" 또는 "binary signal=1"
        # 인 시점을 모두 entry candidate 로 저장하고 entry edge 처리는 threshold 적용 후에 한다.
        # → 더 단순한 방식: candidate 모두 저장 + 별도 timestamp 비교로 dedup.
        # 하지만 그러면 metadata 비대 → 일단 모든 봉의 (pos, score) 를 보관 (np 압축).

        close = df["close"].astype("float64").to_numpy()
        dt_index = df.index

        # 최근 LOOKBACK_YEARS 년 범위 안만
        if isinstance(dt_index, pd.DatetimeIndex):
            mask_recent = np.asarray(dt_index >= SINCE)
        else:
            mask_recent = np.array([pd.Timestamp(d) >= SINCE for d in dt_index])

        rec = {
            "symbol": symbol,
            "close": close,
            "scores": score_arr.to_numpy(),  # 봉마다 score (>0 또는 binary 100)
            "dt": [str(d.date()) if hasattr(d, "date") else str(d) for d in dt_index],
            "mask_recent": mask_recent,
        }
        out.append(rec)
        n_proc += 1
        if verbose and n_proc % 50 == 0:
            print(f"    [{asset}/{interval}/{strategy}] {n_proc} done...", flush=True)
    if verbose:
        print(f"    [{asset}/{interval}/{strategy}] processed={n_proc}, short={n_skip}", flush=True)
    return out


def run_grid(
    asset: str, interval: str, strategy: str,
    thresholds: list[float], exit_rules: list[ExitRule],
    universe: Optional[set] = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """(threshold × exit_rule) 그리드 백테스트. 결과 행: 하나의 (asset, strategy, interval, threshold, exit_rule)."""
    if universe is None:
        universe = _universe(asset)

    is_binary = (strategy == "quiet_bottom")
    if is_binary:
        # quiet_bottom 은 binary signal. threshold 무시 (signal=1 이 곧 entry).
        thresholds = [100.0]

    entries_data = collect_entries(asset, interval, strategy, universe, verbose=verbose)
    cost = COST_RT[asset]

    rows = []
    bars_per_year = BARS_PER_YEAR[interval]

    for th in thresholds:
        for rule in exit_rules:
            trades = []
            for rec in entries_data:
                scores = rec["scores"]
                mask = rec["mask_recent"]
                close = rec["close"]
                dts = rec["dt"]
                # threshold 통과한 봉의 0→1 전환 (re-trigger 처리)
                sig_th = (scores >= th).astype("int8")
                sig_th = sig_th * mask.astype("int8")  # 최근 N년만
                if sig_th.sum() == 0:
                    continue
                # 0→1 전환점
                prev = np.concatenate([[0], sig_th[:-1]])
                entries_idx = np.where((sig_th == 1) & (prev == 0))[0]
                if len(entries_idx) == 0:
                    continue
                # 중복 진입 방지 — 직전 trade exit 시점 이후만 새 entry 로 허용
                last_exit = -1
                for pos in entries_idx:
                    if pos <= last_exit:
                        continue
                    exit_pos, gross = simulate(close, int(pos), rule)
                    net = gross - cost
                    trades.append({
                        "symbol": rec["symbol"],
                        "entry_dt": dts[pos],
                        "exit_dt": dts[exit_pos] if exit_pos < len(dts) else dts[-1],
                        "held_bars": exit_pos - pos,
                        "gross_ret": gross,
                        "net_ret": net,
                    })
                    last_exit = exit_pos
            summary = _summarize_trades(trades, bars_per_year)
            row = {
                "asset": asset, "strategy": strategy, "interval": interval,
                "threshold": th, "exit_rule": rule.name,
                "max_hold": rule.max_hold, "trailing_pct": rule.trailing_pct,
                "take_profit_pct": rule.take_profit_pct, "cut_early_neg": rule.cut_early_neg,
                **summary,
            }
            rows.append(row)
            if verbose:
                print(f"    th={th:>5.1f} {rule.name:<28} "
                      f"n={summary['n']:>4d} win%={summary['win_pct']:>5.1f} "
                      f"mean%={summary['mean_pct']:>+6.2f} "
                      f"total%={summary['total_pct']:>+8.1f} "
                      f"MDD%={summary['mdd_pct']:>+6.1f} "
                      f"Sharpe={summary['sharpe']:>+5.2f}", flush=True)
    return pd.DataFrame(rows)


def _summarize_trades(trades: list[dict], bars_per_year: int) -> dict:
    if not trades:
        return {
            "n": 0, "win_pct": 0.0, "mean_pct": 0.0, "median_pct": 0.0,
            "total_pct": 0.0, "mdd_pct": 0.0, "sharpe": 0.0,
            "profit_factor": 0.0, "avg_held_bars": 0.0,
        }
    df = pd.DataFrame(trades)
    rets = df["net_ret"].to_numpy()
    win = float((rets > 0).mean() * 100)
    mean = float(rets.mean() * 100)
    median = float(np.median(rets) * 100)
    held = float(df["held_bars"].mean())
    eq = np.cumprod(1.0 + rets)
    total = float((eq[-1] - 1.0) * 100)
    peak = np.maximum.accumulate(eq)
    dd = float((eq / peak - 1.0).min() * 100)
    # per-trade Sharpe 연환산 — 시그널 빈도(평균 hold bar 수) 기반
    # trades/yr ≈ bars_per_year / avg_held_bars
    if rets.std() > 0 and held > 0:
        trades_per_year = bars_per_year / max(held, 1)
        sharpe = float(rets.mean() / rets.std() * np.sqrt(trades_per_year))
    else:
        sharpe = 0.0
    gains = float(rets[rets > 0].sum())
    losses = float(-rets[rets < 0].sum())
    pf = float(gains / losses) if losses > 0 else float("inf")
    return {
        "n": int(len(rets)), "win_pct": win, "mean_pct": mean, "median_pct": median,
        "total_pct": total, "mdd_pct": dd, "sharpe": sharpe,
        "profit_factor": pf, "avg_held_bars": held,
    }


# ---------------------------------------------------------------------------
# preset grids
# ---------------------------------------------------------------------------
def stage_a_exit_default(asset: str, strategy: str, interval: str) -> ExitRule:
    """Stage A 의 baseline exit rule. 자산·전략 의도에 맞춤."""
    # bar 수 환산 — 인터벌별로 "N주" 의미 봉수
    if interval == "1w":
        wk = 1
    elif interval == "1d":
        wk = 5
    elif interval == "4h":
        wk = 42
    elif interval == "1h":
        wk = 168
    else:
        wk = 5

    if strategy == "trend_chase":
        # 단기 추격 — 짧게 잡고 trailing
        if asset == "crypto":
            return ExitRule("chase_default", max_hold=8 * wk, trailing_pct=0.15, take_profit_pct=0.30)
        return ExitRule("chase_default", max_hold=13 * wk, trailing_pct=0.20, take_profit_pct=0.30)
    if strategy == "trend_pullback":
        # 중기 — pullback 후 추세 재개
        if asset == "crypto":
            return ExitRule("pullback_default", max_hold=13 * wk, trailing_pct=0.15, take_profit_pct=0.30)
        return ExitRule("pullback_default", max_hold=26 * wk, trailing_pct=0.20, take_profit_pct=0.30)
    if strategy == "quiet_bottom":
        # 장기 — QUIET_BOTTOM.md 베스트
        if asset == "crypto":
            return ExitRule("quiet_default", max_hold=13 * wk, trailing_pct=0.15, cut_early_neg=1)
        return ExitRule("quiet_default", max_hold=52 * wk, trailing_pct=0.20, take_profit_pct=0.30)
    return ExitRule("none")


def stage_b_exit_grid(asset: str, strategy: str, interval: str) -> list[ExitRule]:
    """Stage B 의 exit rule grid (Stage A 의 best threshold 에서 sweep)."""
    if interval == "1w":
        wk = 1
    elif interval == "1d":
        wk = 5
    elif interval == "4h":
        wk = 42
    elif interval == "1h":
        wk = 168
    else:
        wk = 5

    rules: list[ExitRule] = []
    if strategy == "trend_chase":
        for h in (4, 8, 13):
            for tr in (0.10, 0.15, 0.20):
                for tp in (0.20, 0.30, 0.50):
                    rules.append(ExitRule(f"hold{h}w_tr{int(tr*100)}_tp{int(tp*100)}",
                                          max_hold=h * wk, trailing_pct=tr, take_profit_pct=tp))
    elif strategy == "trend_pullback":
        for h in (8, 13, 26):
            for tr in (0.10, 0.15, 0.20):
                for tp in (0.30, 0.50):
                    rules.append(ExitRule(f"hold{h}w_tr{int(tr*100)}_tp{int(tp*100)}",
                                          max_hold=h * wk, trailing_pct=tr, take_profit_pct=tp))
    elif strategy == "quiet_bottom":
        if asset == "crypto":
            for h in (8, 13, 26):
                for tr in (0.10, 0.15, 0.20):
                    for cut in (0, 1):
                        rules.append(ExitRule(
                            f"hold{h}w_tr{int(tr*100)}_cut{cut}",
                            max_hold=h * wk, trailing_pct=tr, cut_early_neg=cut))
        else:
            for h in (26, 52):
                for tr in (0.15, 0.20, 0.25):
                    for tp in (0.30, 0.50, 0.0):
                        rules.append(ExitRule(
                            f"hold{h}w_tr{int(tr*100)}_tp{int(tp*100)}",
                            max_hold=h * wk, trailing_pct=tr, take_profit_pct=tp))
    return rules


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_exit_arg(s: str) -> ExitRule:
    """예: 'hold=8w,trail=0.15,tp=0.30,cut=1' → ExitRule.

    hold N + (w|d|h) 인 경우는 호출자가 interval 환산. 여기선 bar 수.
    """
    parts = dict(p.split("=") for p in s.split(","))
    return ExitRule(
        name=s,
        max_hold=int(parts.get("hold", 0)),
        trailing_pct=float(parts.get("trail", 0.0)),
        take_profit_pct=float(parts.get("tp", 0.0)),
        cut_early_neg=int(parts.get("cut", 0)),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", choices=["kr", "us", "crypto"])
    ap.add_argument("--strategy", choices=list(STRATEGIES.keys()))
    ap.add_argument("--interval")
    ap.add_argument("--thresholds", default="60,70,75,80,85,90")
    ap.add_argument("--exit", default=None,
                    help="bar-count exit rule, e.g. 'hold=40,trail=0.15,tp=0.30'")
    ap.add_argument("--stage", choices=["A", "B", "both"], default="A",
                    help="A: threshold sweep (default exit). B: exit grid at best threshold.")
    args = ap.parse_args()

    if not args.asset or not args.strategy or not args.interval:
        ap.error("--asset, --strategy, --interval all required (or use stage_runner.py for preset)")

    thresholds = [float(x) for x in args.thresholds.split(",")]
    if args.exit:
        exit_rules = [_parse_exit_arg(args.exit)]
    else:
        exit_rules = [stage_a_exit_default(args.asset, args.strategy, args.interval)]

    df = run_grid(args.asset, args.interval, args.strategy, thresholds, exit_rules)
    out_csv = OUT_DIR / f"grid_{args.asset}_{args.strategy}_{args.interval}.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\nsaved: {out_csv}")


if __name__ == "__main__":
    main()
