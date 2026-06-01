"""ma20w_short Layer 0 — baseline (sanity check).

진입 룰: 다운트렌드 게이트 (close_1w<MA20w & slope_4w<0) + 일봉 high>=MA20w 첫 봉
청산 룰: 일봉 close >= MA20w(rolling latest completed weekly) → 다음 일봉 시가
비용: 진입+청산 fee 10bps + 슬리피지 5bps = 15bps round-trip
4 그룹 (trend/follower/whale/junk) 동일 파라미터.

출력:
  output/trades.parquet         — 전체 trades (symbol, group, entry/exit, ret_net, ...)
  output/summary_by_group.csv   — 그룹별 통계 (wide)
  output/summary.json           — 전체 + 그룹별 핵심 메트릭

사용:
  .venv/Scripts/python.exe -m scripts.crypto.ma20w_short.baseline \
      --config scripts/crypto/ma20w_short/runs/20260528-2236_baseline/config.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Windows 한글 깨짐 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from scripts._common.run_helper import parse_args, update_config, resolve_config_path
from scripts.crypto.ma20w_short._common import backtest_symbol, load_4groups


# ============================================================
# Summary stats
# ============================================================

def summarize_trades(trades: pd.DataFrame) -> dict:
    """trades DataFrame → 핵심 메트릭 dict."""
    if trades.empty:
        return {
            "n_trades": 0, "mean_ret": None, "median_ret": None, "std_ret": None,
            "win_rate": None, "payoff": None, "var_adj_ex": None,
            "mdd": None, "sharpe": None, "avg_holding_days": None,
        }

    r = trades["ret_net"].astype(float)
    wins = r[r > 0]
    losses = r[r <= 0]

    win_rate = len(wins) / len(r) if len(r) > 0 else None
    avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(losses.mean()) if len(losses) > 0 else 0.0
    payoff = abs(avg_win / avg_loss) if avg_loss < 0 else (float("inf") if avg_win > 0 else None)

    mean = float(r.mean())
    std = float(r.std(ddof=1)) if len(r) > 1 else 0.0
    var_adj = mean - 1.65 * std

    # Equity-based MDD (trades 순서대로 누적, 동일 비중 가정)
    sorted_trades = trades.sort_values("exit_dt").reset_index(drop=True)
    eq = (1 + sorted_trades["ret_net"].astype(float)).cumprod()
    peak = eq.cummax()
    dd = (eq / peak - 1).min()

    # Annualized Sharpe (per-trade, 연간 환산 = 252 / avg_holding_days)
    avg_hd = float(sorted_trades["holding_days"].mean())
    if avg_hd > 0 and std > 0:
        trades_per_year = 252.0 / avg_hd
        sharpe = (mean / std) * np.sqrt(trades_per_year)
    else:
        sharpe = None

    return {
        "n_trades": int(len(r)),
        "mean_ret": mean,
        "median_ret": float(r.median()),
        "std_ret": std,
        "win_rate": win_rate,
        "payoff": payoff,
        "var_adj_ex": var_adj,
        "mdd": float(dd),
        "sharpe": sharpe,
        "avg_holding_days": avg_hd,
    }


# ============================================================
# Main
# ============================================================

def main():
    def add_args(ap):
        ap.add_argument("--date-from", type=str, default=None)
        ap.add_argument("--date-to", type=str, default=None)
        ap.add_argument("--cooldown-days", type=int, default=None)
        ap.add_argument("--min-obs", type=int, default=None,
                        help="classification min_obs filter")

    defaults = {
        "gate": {"close_lt_ma20w": True, "slope_4w_lt": 0.0},
        "entry": {
            "rule": "intraday_high_ge_ma20w",
            "fill_price": "ma20w_limit",
            "cooldown_weeks": 4,
        },
        "exit": {"rule": "close_1d_ge_ma20w"},
        "cost": {"fee_bps_per_side": 5, "slippage_bps": 5, "funding_cost": None},
        "side": "short",
    }

    out_dir, params, args = parse_args(add_args, defaults, "ma20w_short baseline (Layer 0)")
    cfg_path = resolve_config_path(args)

    # Resolve runtime knobs
    date_from = args.date_from or (cfg_path and json.loads(cfg_path.read_text(encoding="utf-8"))
                                     .get("data", {}).get("date_from"))
    date_to = args.date_to or (cfg_path and json.loads(cfg_path.read_text(encoding="utf-8"))
                                 .get("data", {}).get("date_to"))
    cooldown_weeks = (params.get("entry") or {}).get("cooldown_weeks", 4)
    cooldown_days = args.cooldown_days or (cooldown_weeks * 7)
    min_obs = args.min_obs or 300
    cost = params.get("cost", {}) or {}
    fee_bps = float(cost.get("fee_bps_per_side", 5))
    slip_bps = float(cost.get("slippage_bps", 5))

    print(f"[ma20w_short baseline] date={date_from}..{date_to} cooldown={cooldown_days}d "
          f"fee={fee_bps}bps/side slip={slip_bps}bps min_obs={min_obs}")

    # Load 4 groups
    groups = load_4groups(min_obs=min_obs)
    total = sum(len(v) for v in groups.values())
    print(f"[universe] total symbols: {total}")
    for g, syms in groups.items():
        print(f"  {g}: {len(syms):>4d}  (e.g. {syms[:3]})")

    # Backtest each symbol
    all_trades = []
    for group, syms in groups.items():
        print(f"\n[backtest] group={group}  symbols={len(syms)}")
        n_done = 0
        for sym in syms:
            t = backtest_symbol(
                sym,
                date_from=date_from,
                date_to=date_to,
                cooldown_days=cooldown_days,
                fee_bps_per_side=fee_bps,
                slippage_bps=slip_bps,
            )
            if not t.empty:
                t["group"] = group
                all_trades.append(t)
            n_done += 1
            if n_done % 50 == 0:
                print(f"    {n_done}/{len(syms)} processed")

    if not all_trades:
        print("\n[!] No trades produced. Check cache / date range / gate logic.")
        return

    trades = pd.concat(all_trades, ignore_index=True)
    print(f"\n[trades] total {len(trades)} trades from {trades['symbol'].nunique()} symbols")

    # Save raw trades
    trades_path = out_dir / "trades.parquet"
    trades.to_parquet(trades_path, index=False)
    print(f"[save] {trades_path} ({len(trades)} rows)")

    # Summary by group
    rows = []
    for group in ("trend", "follower", "whale", "junk"):
        sub = trades[trades["group"] == group]
        s = summarize_trades(sub)
        s["group"] = group
        s["n_symbols"] = int(sub["symbol"].nunique()) if not sub.empty else 0
        rows.append(s)
    rows.append({"group": "ALL", **summarize_trades(trades),
                 "n_symbols": int(trades["symbol"].nunique())})

    summary_df = pd.DataFrame(rows).set_index("group").reindex(
        ["trend", "follower", "whale", "junk", "ALL"]
    )
    summary_path = out_dir / "summary_by_group.csv"
    summary_df.to_csv(summary_path)
    print(f"[save] {summary_path}")

    # JSON summary
    summary_json = {
        "params": {
            "date_from": date_from, "date_to": date_to,
            "cooldown_days": cooldown_days,
            "fee_bps_per_side": fee_bps, "slippage_bps": slip_bps,
            "min_obs": min_obs,
        },
        "groups": summary_df.reset_index().to_dict(orient="records"),
    }
    json_path = out_dir / "summary.json"
    json_path.write_text(json.dumps(summary_json, indent=2, ensure_ascii=False,
                                      allow_nan=False, default=str), encoding="utf-8")
    print(f"[save] {json_path}")

    # update config
    if cfg_path:
        results = {
            f"{g}_mean_ret": (summary_df.loc[g, "mean_ret"] if g in summary_df.index else None)
            for g in ("trend", "follower", "whale", "junk", "ALL")
        }
        results.update({
            f"{g}_n_trades": (int(summary_df.loc[g, "n_trades"]) if g in summary_df.index else 0)
            for g in ("trend", "follower", "whale", "junk", "ALL")
        })
        update_config(
            cfg_path,
            data={"symbol_count": int(total), "groups_n_symbols":
                    {g: len(syms) for g, syms in groups.items()}},
            results_summary=results,
        )
        print(f"[update_config] {cfg_path}")

    # Print summary table
    print("\n=== Baseline summary (per group) ===")
    cols = ["n_symbols", "n_trades", "mean_ret", "median_ret", "win_rate",
            "payoff", "var_adj_ex", "mdd", "sharpe", "avg_holding_days"]
    view = summary_df[cols].copy()
    for c in ("mean_ret", "median_ret", "win_rate", "var_adj_ex", "mdd"):
        view[c] = view[c].astype(float).round(4)
    view["payoff"] = view["payoff"].astype(float).round(2)
    view["sharpe"] = view["sharpe"].astype(float).round(2)
    view["avg_holding_days"] = view["avg_holding_days"].astype(float).round(1)
    print(view.to_string())


if __name__ == "__main__":
    main()
