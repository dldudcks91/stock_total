"""진입 타이밍 최적화 그리드 러너 — trend_chase / trend_pullback / quiet_bottom × KR/US/Crypto.

전략 시그널 진입 + 자산별 청산 룰 시뮬레이션 → per-trade 메트릭.

원리:
  1) 자산·인터벌별 universe 로드 (상위 300).
  2) 종목별로 score 시계열을 한 번만 계산 (trend_chase/pullback) / signal 한 번만 (quiet_bottom).
  3) score_threshold 그리드 (60/70/75/80/85/90) 별로 진입 인덱스만 추출.
  4) 각 진입에 대해 청산 룰(simulate) 적용해 per-trade 결과 누적.
  5) (asset, strategy, interval, score_threshold, exit_rule) 단위로 summarize.

사용:
  python -m scripts.optimize_grid --asset kr --strategy trend_chase --interval 1d
  python -m scripts.optimize_grid --all                 # 모든 조합 (오래 걸림)

산출:
  scripts/out/optimize/{asset}_{strategy}_{interval}_grid.csv
  scripts/out/optimize/_all_grids.csv (누적)
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.strategies import trend_chase, trend_pullback, quiet_bottom  # noqa: E402
from scripts.trend_strategies.forward_returns import (  # noqa: E402
    load_crypto, load_stock, kr_universe, us_universe, crypto_universe,
    CRYPTO_1H_DIR, CRYPTO_1D_DIR, KR_DIR, US_DIR,
)

OUT_DIR = ROOT / "scripts" / "out" / "optimize"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NOW = pd.Timestamp.utcnow().tz_localize(None).normalize()
SINCE_YEARS = 6
SINCE = NOW - pd.DateOffset(years=SINCE_YEARS)

# 왕복 수수료+슬리피지
COST_RT = {"crypto": 0.002, "kr": 0.003, "us": 0.002}

STRATEGIES = {
    "trend_chase": trend_chase,
    "trend_pullback": trend_pullback,
    "quiet_bottom": quiet_bottom,
}

# threshold 그리드 (quiet_bottom 은 binary 라 단일 dummy 사용)
SCORE_GRID = [60, 70, 75, 80, 85, 90]
QUIET_GRID = [1]  # placeholder

UNIVERSE_TOP = 300

MIN_BARS = {"1h": 500, "4h": 200, "1d": 80, "1w": 30}


# ---------------------------------------------------------------------------
# Exit-rule definition (compatible with scripts/quiet_bottom/exit_rule_grid.py)
# ---------------------------------------------------------------------------
@dataclass
class ExitRule:
    name: str
    max_hold: int = 0
    trailing_pct: float = 0.0
    take_profit_pct: float = 0.0
    cut_1bar_neg: bool = False         # 첫 1봉 음수 컷
    cut_short_thr: float = -999        # held==cut_short_at 봉에 ret(%) < thr 면 컷
    cut_short_at: int = 2


def simulate(close: np.ndarray, entry_pos: int, rule: ExitRule) -> Tuple[int, float]:
    """단순 long simulate. close[entry_pos] 에 진입, 청산 봉 idx + gross_ret 반환."""
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
        # 1) take profit
        if rule.take_profit_pct > 0 and ret >= rule.take_profit_pct:
            return i, ret
        # 2) trailing
        if rule.trailing_pct > 0 and peak > ec:
            if ci / peak - 1.0 <= -rule.trailing_pct:
                return i, ret
        # 3) cut on first bar negative
        if rule.cut_1bar_neg and held == 1 and ret < 0:
            return i, ret
        # 4) cut short threshold
        if rule.cut_short_thr > -100 and held == rule.cut_short_at and ret * 100 < rule.cut_short_thr:
            return i, ret
        # 5) max hold
        if rule.max_hold > 0 and held >= rule.max_hold:
            return i, ret
    last = n - 1
    if last <= entry_pos:
        return entry_pos, 0.0
    return last, close[last] / ec - 1.0


def summarize_trades(trades: List[dict], asset: str) -> dict:
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
        # 연환산: signals/year 평균
        annual_factor = np.sqrt(max(1, len(rets)) / float(SINCE_YEARS))
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
# 자산·인터벌별 청산 룰 카탈로그
# ---------------------------------------------------------------------------
def exit_rules_for(asset: str, interval: str) -> List[ExitRule]:
    """1차 그리드: 검증된 베이스 + 변형 2~3개."""
    if asset in ("kr", "us"):
        if interval == "1d":
            # 252d ≈ 52w
            return [
                ExitRule("hold_252d_trail20_TP30", max_hold=252, trailing_pct=0.20, take_profit_pct=0.30),
                ExitRule("hold_60d_trail15", max_hold=60, trailing_pct=0.15),
                ExitRule("hold_120d_trail20_TP25", max_hold=120, trailing_pct=0.20, take_profit_pct=0.25),
                ExitRule("hold_252d_trail15", max_hold=252, trailing_pct=0.15),
            ]
        else:  # 1w
            return [
                ExitRule("hold_52w_trail20_TP30", max_hold=52, trailing_pct=0.20, take_profit_pct=0.30),
                ExitRule("hold_26w_trail15", max_hold=26, trailing_pct=0.15),
                ExitRule("hold_52w_trail15", max_hold=52, trailing_pct=0.15),
                ExitRule("hold_26w_trail20_TP25", max_hold=26, trailing_pct=0.20, take_profit_pct=0.25),
            ]
    # crypto
    if interval == "1h":
        return [
            ExitRule("hold_500h_trail15_cut5h", max_hold=500, trailing_pct=0.15,
                     cut_short_at=5, cut_short_thr=-3),
            ExitRule("hold_200h_trail10", max_hold=200, trailing_pct=0.10),
            ExitRule("hold_500h_trail20_TP30", max_hold=500, trailing_pct=0.20, take_profit_pct=0.30),
        ]
    if interval == "4h":
        return [
            ExitRule("hold_120bars_trail15_cut24h", max_hold=120, trailing_pct=0.15,
                     cut_short_at=6, cut_short_thr=-4),
            ExitRule("hold_60bars_trail10", max_hold=60, trailing_pct=0.10),
            ExitRule("hold_120bars_trail20_TP30", max_hold=120, trailing_pct=0.20, take_profit_pct=0.30),
        ]
    if interval == "1d":
        return [
            ExitRule("hold_60d_trail15_cut3d", max_hold=60, trailing_pct=0.15,
                     cut_short_at=3, cut_short_thr=-5),
            ExitRule("hold_30d_trail10", max_hold=30, trailing_pct=0.10),
            ExitRule("hold_60d_trail20_TP30", max_hold=60, trailing_pct=0.20, take_profit_pct=0.30),
        ]
    # 1w
    return [
        ExitRule("hold_13w_trail15_cut1w", max_hold=13, trailing_pct=0.15, cut_1bar_neg=True),
        ExitRule("hold_8w_trail15", max_hold=8, trailing_pct=0.15),
        ExitRule("hold_13w_trail20_TP30", max_hold=13, trailing_pct=0.20, take_profit_pct=0.30),
    ]


# ---------------------------------------------------------------------------
# 데이터 로드 + 시그널 1회 캐싱
# ---------------------------------------------------------------------------
def _build_universe(asset: str) -> set:
    if asset == "kr":
        return kr_universe(UNIVERSE_TOP)
    if asset == "us":
        return us_universe(UNIVERSE_TOP)
    if asset == "crypto":
        return crypto_universe(UNIVERSE_TOP)
    raise ValueError(asset)


def _files_for(asset: str, interval: str) -> List[Path]:
    if asset == "crypto":
        if interval in ("1h", "4h"):
            return sorted(CRYPTO_1H_DIR.glob("*.parquet"))
        # 1d / 1w: 1d 캐시 우선
        if CRYPTO_1D_DIR.exists():
            files = sorted(CRYPTO_1D_DIR.glob("*.parquet"))
            if files:
                return files
        return sorted(CRYPTO_1H_DIR.glob("*.parquet"))
    if asset == "kr":
        return [p for p in sorted(KR_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    if asset == "us":
        return [p for p in sorted(US_DIR.glob("*.parquet")) if not p.stem.startswith("_")]
    raise ValueError(asset)


def _load_one(asset: str, path: Path, interval: str) -> pd.DataFrame:
    if asset == "crypto":
        return load_crypto(path, interval)
    return load_stock(path, interval)


def _resample_crypto_4h(path: Path) -> pd.DataFrame:
    """4h 는 1h 에서 직접 리샘플 (forward_returns.load_crypto 가 1d/1w 만 지원)."""
    df = pd.read_parquet(path)
    if "timestamp" not in df.columns:
        return pd.DataFrame()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df = df.set_index("dt").sort_index()
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    if "amount" in df.columns:
        agg["amount"] = "sum"
    return df.resample("4H", label="left", closed="left").agg(agg).dropna()


def _resample_crypto_1h(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if "timestamp" not in df.columns:
        return pd.DataFrame()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df = df.set_index("dt").sort_index()
    return df[["open", "high", "low", "close", "volume"] + (["amount"] if "amount" in df.columns else [])]


def load_symbol(asset: str, path: Path, interval: str) -> pd.DataFrame:
    if asset == "crypto":
        if interval == "1h":
            return _resample_crypto_1h(path)
        if interval == "4h":
            return _resample_crypto_4h(path)
        return load_crypto(path, interval)
    return load_stock(path, interval)


# ---------------------------------------------------------------------------
# 그리드 실행
# ---------------------------------------------------------------------------
def run_grid(asset: str, strategy_name: str, interval: str,
             max_symbols: Optional[int] = None) -> pd.DataFrame:
    strat = STRATEGIES[strategy_name]
    cost = COST_RT[asset]
    min_bars = MIN_BARS[interval]
    rules = exit_rules_for(asset, interval)
    universe = _build_universe(asset)
    files = _files_for(asset, interval)

    is_quiet = (strategy_name == "quiet_bottom")
    grid = QUIET_GRID if is_quiet else SCORE_GRID

    t0 = time.time()
    print(f"\n=== {asset.upper()} / {strategy_name} / {interval} "
          f"(universe={len(universe)}, files={len(files)}, rules={len(rules)}, "
          f"thresholds={grid}) ===", flush=True)

    # 종목별 (close, score-or-signal) 캐시
    cache: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
    n_done = 0
    n_skip = 0
    n_proc = 0
    for p in files:
        symbol = p.stem
        if symbol not in universe:
            continue
        n_proc += 1
        if max_symbols is not None and n_done >= max_symbols:
            break
        try:
            df = load_symbol(asset, p, interval)
        except Exception as e:
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
        except Exception as e:
            n_skip += 1
            continue
        close = df["close"].astype("float64").to_numpy()
        # 시기 필터용 dt mask (entry >= SINCE)
        dt_idx = pd.DatetimeIndex(df.index)
        in_period = np.asarray(dt_idx >= SINCE)
        cache[symbol] = (close, val, in_period)
        n_done += 1
        if n_done % 50 == 0:
            print(f"  loaded {n_done}/{len(universe)} (skipped {n_skip})", flush=True)

    print(f"  loaded total: {n_done} symbols, skipped {n_skip}. "
          f"elapsed {time.time()-t0:.1f}s", flush=True)

    if n_done == 0:
        return pd.DataFrame()

    # 그리드 × 청산 룰
    rows = []
    for th in grid:
        for rule in rules:
            trades = []
            for symbol, (close, val, in_period) in cache.items():
                # 진입 인덱스: signal 0->1 (quiet_bottom 은 val 자체가 0/1)
                if is_quiet:
                    sig01 = val
                else:
                    sig01 = (val >= float(th)).astype("int8")
                # 0->1 전환
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
            summary = summarize_trades(trades, asset)
            rows.append({
                "asset": asset, "strategy": strategy_name, "interval": interval,
                "score_th": th if not is_quiet else "binary",
                "rule": rule.name,
                **summary,
                **{f"_{k}": v for k, v in asdict(rule).items() if k != "name"},
            })
            print(f"  th={th:>6} rule={rule.name:<32s} "
                  f"n={summary['n']:>4} win={summary['win%']:>4.1f}% "
                  f"mean={summary['mean%']:>+5.1f}% total={summary['total%']:>+7.1f}% "
                  f"MDD={summary['MDD%']:>+6.1f}% Sharpe={summary['Sharpe_ann']:>+5.2f} "
                  f"PF={summary['PF']:>5.2f}", flush=True)

    out = pd.DataFrame(rows)
    out_csv = OUT_DIR / f"{asset}_{strategy_name}_{interval}_grid.csv"
    out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"  saved: {out_csv}", flush=True)
    return out


def append_to_master(df: pd.DataFrame):
    if df is None or df.empty:
        return
    master = OUT_DIR / "_all_grids.csv"
    if master.exists():
        prev = pd.read_csv(master)
        combined = pd.concat([prev, df], ignore_index=True)
    else:
        combined = df
    combined.to_csv(master, index=False, encoding="utf-8-sig")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
ALL_COMBOS = []
for _asset, _intervals in [("kr", ["1d", "1w"]),
                            ("us", ["1d", "1w"]),
                            ("crypto", ["1h", "4h", "1d", "1w"])]:
    for _iv in _intervals:
        for _st in ["trend_chase", "trend_pullback", "quiet_bottom"]:
            ALL_COMBOS.append((_asset, _st, _iv))


def _build_parser():
    p = argparse.ArgumentParser(prog="optimize_grid")
    p.add_argument("--asset", choices=["kr", "us", "crypto"])
    p.add_argument("--strategy", choices=list(STRATEGIES))
    p.add_argument("--interval", choices=["1h", "4h", "1d", "1w"])
    p.add_argument("--all", action="store_true", help="모든 조합 실행")
    p.add_argument("--max-symbols", type=int, default=None,
                   help="디버깅용 종목 수 제한")
    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)
    if args.all:
        combos = ALL_COMBOS
    else:
        if not (args.asset and args.strategy and args.interval):
            print("either --all or (--asset --strategy --interval) required", file=sys.stderr)
            return 2
        combos = [(args.asset, args.strategy, args.interval)]

    for asset, strategy, interval in combos:
        # 인터벌 호환 체크
        if asset in ("kr", "us") and interval not in ("1d", "1w"):
            print(f"skip {asset}/{strategy}/{interval}: unsupported")
            continue
        try:
            df = run_grid(asset, strategy, interval, max_symbols=args.max_symbols)
            append_to_master(df)
        except Exception as e:
            print(f"FAIL {asset}/{strategy}/{interval}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            import traceback
            traceback.print_exc()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
