"""Accumulation vs Continuation discriminator features on existing trigger events.

Input: B (pullback) events from breakout_mtf_stack (default: body=0.03 vol=3.0
timeout=24h) — these have ts_trigger / ts_pullback / ts_entry per event.

For each event, re-load the symbol's 1H cache and compute:

A. Trigger-bar structure (no lookahead):
   upper_wick_ratio, lower_wick_ratio, body_to_range, close_to_high_pct

B. Pre-trigger context (no lookahead):
   vs_24h_high_pct, vs_72h_low_pct, pre_24h_range_pct, pre_consec_up_h,
   pre_vol_quiet_ratio

C. Post-trigger confirmation (uses bars t+1..t+N -> delayed entry at t+N+1):
   next_Nh_held, next_Nh_max_close_above_trigger, next_Nh_avg_vol_ratio,
   next_Nh_body_sum

Forward returns are computed two ways:
  fwd_*h_at_buy: from the original B entry (pullback BUY, no delay)
  fwd_*h_post_confirm: from open of bar t+N+1 (after confirmation window)

Univariate quintile sweep + winner/loser group means.

Run:
  .venv/Scripts/python.exe -m scripts.trend_pullback.accumulation_classifier \\
      --config scripts/trend_pullback/runs/<ts>_<name>/config.json
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_1H = PROJECT_ROOT / "data" / "cache" / "crypto" / "1h"


def load_1h(symbol: str) -> Optional[pd.DataFrame]:
    p = CACHE_1H / f"{symbol}.parquet"
    if not p.exists():
        return None
    try:
        return pd.read_parquet(p).sort_values("timestamp").reset_index(drop=True)
    except Exception:
        return None


def compute_features(events: pd.DataFrame, post_confirm_bars: int,
                       pre_ctx_h_24: int = 24, pre_ctx_h_72: int = 72,
                       pre_consec_lookback_h: int = 8,
                       pre_vol_quiet_lookback_h: int = 8,
                       horizons_h: list = [4, 24, 72, 168, 336, 672]) -> pd.DataFrame:
    """For each event, compute A/B/C features + post-confirm forward returns."""
    out_rows = []
    syms = events["symbol"].unique()
    print(f"computing features for {len(syms)} symbols, {len(events)} events, post_confirm_bars={post_confirm_bars}")
    t0 = time.time()
    for si, sym in enumerate(syms, 1):
        d = load_1h(sym)
        if d is None:
            continue
        ts = d["timestamp"].astype("int64").to_numpy()
        op = d["open"].astype("float64").to_numpy()
        hi = d["high"].astype("float64").to_numpy()
        lo = d["low"].astype("float64").to_numpy()
        cl = d["close"].astype("float64").to_numpy()
        vol = d["volume"].astype("float64").to_numpy()
        n = len(d)
        sym_ev = events[events["symbol"] == sym]
        for _, e in sym_ev.iterrows():
            ti = int(np.searchsorted(ts, e["ts_trigger"]))
            if ti >= n or ts[ti] != int(e["ts_trigger"]):
                # ts mismatch — skip
                continue
            # A: structure of trigger bar
            T_o, T_h, T_l, T_c, T_v = op[ti], hi[ti], lo[ti], cl[ti], vol[ti]
            rng = T_h - T_l
            body_top = max(T_o, T_c)
            body_bot = min(T_o, T_c)
            upper_wick = (T_h - body_top) / rng if rng > 0 else 0.0
            lower_wick = (body_bot - T_l) / rng if rng > 0 else 0.0
            body_to_range = (body_top - body_bot) / rng if rng > 0 else 0.0
            close_to_high_pct = (T_h - T_c) / T_c if T_c > 0 else np.nan

            # B: pre-trigger context (windows must fit in data)
            start_24 = max(0, ti - pre_ctx_h_24)
            start_72 = max(0, ti - pre_ctx_h_72)
            start_consec = max(0, ti - pre_consec_lookback_h)
            start_volq = max(0, ti - pre_vol_quiet_lookback_h)
            # 24h high/low EXCLUDING trigger bar itself
            h24 = hi[start_24:ti].max() if ti - start_24 >= 6 else np.nan
            l24 = lo[start_24:ti].min() if ti - start_24 >= 6 else np.nan
            l72 = lo[start_72:ti].min() if ti - start_72 >= 12 else np.nan
            avg_close_24 = cl[start_24:ti].mean() if ti - start_24 >= 6 else np.nan
            vs_24h_high_pct = (T_c / h24 - 1.0) if np.isfinite(h24) and h24 > 0 else np.nan
            vs_72h_low_pct = (T_c / l72 - 1.0) if np.isfinite(l72) and l72 > 0 else np.nan
            pre_24h_range_pct = ((h24 - l24) / avg_close_24) if (np.isfinite(h24) and np.isfinite(l24) and np.isfinite(avg_close_24) and avg_close_24 > 0) else np.nan
            # pre consec up bars (count consecutive close > prev close, ending at ti-1)
            cu = 0
            for k in range(ti - 1, start_consec, -1):
                if cl[k] > cl[k - 1]:
                    cu += 1
                else:
                    break
            pre_consec_up_h = cu
            # pre vol quiet: trigger vol / mean(vol over prev N bars excluding trigger)
            prev_vol_mean = vol[start_volq:ti].mean() if ti - start_volq >= 4 else np.nan
            pre_vol_quiet_ratio = (T_v / prev_vol_mean) if (np.isfinite(prev_vol_mean) and prev_vol_mean > 0) else np.nan

            # C: post-trigger confirmation (bars ti+1..ti+N)
            N = post_confirm_bars
            end_confirm = ti + 1 + N
            if end_confirm > n:
                # not enough bars for confirmation window — keep event but mark NaN
                next_held = np.nan; next_max_close = np.nan
                next_avg_vol = np.nan; next_body_sum = np.nan
            else:
                next_bars = slice(ti + 1, end_confirm)
                next_lows = lo[next_bars]
                next_closes = cl[next_bars]
                next_vols = vol[next_bars]
                next_opens = op[next_bars]
                next_held = bool((next_lows >= T_l).all())
                next_max_close = float(next_closes.max() / T_c - 1.0) if T_c > 0 else np.nan
                next_avg_vol = float(next_vols.mean() / T_v) if T_v > 0 else np.nan
                # body sum: sum of (close-open)/open across next N bars
                bsum = 0.0
                for j in range(N):
                    if np.isfinite(next_opens[j]) and next_opens[j] > 0:
                        bsum += (next_closes[j] - next_opens[j]) / next_opens[j]
                next_body_sum = bsum

            # Forward returns at original BUY (pullback entry) - already in events
            row = {**e.to_dict(),
                    "upper_wick_ratio": float(upper_wick),
                    "lower_wick_ratio": float(lower_wick),
                    "body_to_range": float(body_to_range),
                    "close_to_high_pct": float(close_to_high_pct),
                    "vs_24h_high_pct": float(vs_24h_high_pct) if np.isfinite(vs_24h_high_pct) else np.nan,
                    "vs_72h_low_pct": float(vs_72h_low_pct) if np.isfinite(vs_72h_low_pct) else np.nan,
                    "pre_24h_range_pct": float(pre_24h_range_pct) if np.isfinite(pre_24h_range_pct) else np.nan,
                    "pre_consec_up_h": int(pre_consec_up_h),
                    "pre_vol_quiet_ratio": float(pre_vol_quiet_ratio) if np.isfinite(pre_vol_quiet_ratio) else np.nan,
                    "next_held": next_held,
                    "next_max_close_above": float(next_max_close) if np.isfinite(next_max_close) else np.nan,
                    "next_avg_vol_ratio": float(next_avg_vol) if np.isfinite(next_avg_vol) else np.nan,
                    "next_body_sum": float(next_body_sum) if np.isfinite(next_body_sum) else np.nan,
                    "post_confirm_bars": int(N),
            }
            # Post-confirm entry forward returns
            post_entry_idx = ti + 1 + N
            if post_entry_idx < n:
                post_entry = op[post_entry_idx]
                if np.isfinite(post_entry) and post_entry > 0:
                    row["post_entry_price"] = float(post_entry)
                    for h in horizons_h:
                        tgt = post_entry_idx + h - 1
                        if tgt < n and np.isfinite(cl[tgt]):
                            row[f"fwd_ret_{h}h_post"] = float(cl[tgt] / post_entry - 1.0)
                        else:
                            row[f"fwd_ret_{h}h_post"] = np.nan
            out_rows.append(row)
        if si % 100 == 0:
            print(f"  {si}/{len(syms)} ({time.time()-t0:.1f}s) {len(out_rows)} events processed")
    return pd.DataFrame(out_rows)


def _cell_stats(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"n": 0, "mean": np.nan, "median": np.nan, "win": np.nan, "std": np.nan}
    return {"n": int(len(s)), "mean": float(s.mean()),
            "median": float(s.median()), "win": float((s > 0).mean()),
            "std": float(s.std())}


def quintile_table(events: pd.DataFrame, feature: str, fwd_cols: list, q: int = 5) -> pd.DataFrame:
    s = events[feature].dropna()
    if len(s) < q * 30:
        return pd.DataFrame()
    try:
        cats = pd.qcut(s, q=q, duplicates="drop")
    except ValueError:
        return pd.DataFrame()
    full = pd.Series(pd.NA, index=events.index, dtype="object")
    full.loc[s.index] = cats.astype(str)
    rows = []
    for cat, idx in full.dropna().groupby(full.dropna()).indices.items():
        sub = events.loc[list(idx)]
        for col in fwd_cols:
            if col not in sub.columns:
                continue
            rows.append({"feature": feature, "quantile": cat,
                          "horizon": col, **_cell_stats(sub[col])})
    return pd.DataFrame(rows)


def winner_loser_compare(events: pd.DataFrame, fwd_col: str, win_th: float, lose_th: float,
                          features: list) -> pd.DataFrame:
    s = events[fwd_col]
    win_mask = s > win_th
    lose_mask = s < lose_th
    rows = []
    for feat in features:
        if feat not in events.columns:
            continue
        f = events[feat]
        w_vals = f[win_mask].dropna()
        l_vals = f[lose_mask].dropna()
        if len(w_vals) < 30 or len(l_vals) < 30:
            continue
        rows.append({
            "feature": feat,
            "win_n": len(w_vals), "win_mean": float(w_vals.mean()), "win_median": float(w_vals.median()),
            "lose_n": len(l_vals), "lose_mean": float(l_vals.mean()), "lose_median": float(l_vals.median()),
            "mean_diff_WL": float(w_vals.mean() - l_vals.mean()),
            "median_diff_WL": float(w_vals.median() - l_vals.median()),
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out["abs_mean_diff"] = out["mean_diff_WL"].abs()
        out = out.sort_values("abs_mean_diff", ascending=False)
    return out


def main():
    from scripts._common.run_helper import parse_args, update_config, resolve_config_path

    def add_args(ap):
        ap.add_argument("--post-confirm-bars", type=int, default=None)

    out_dir, params, args = parse_args(add_args, {
        "input_events": "scripts/trend_pullback/runs/20260519-0300_strong_breakout/output/events_B.parquet",
        "filter": "body_ret_min=0.03 AND vol_ratio_min=3.0 AND pullback_timeout_h=24",
        "n_quantiles": 5,
        "winner_threshold_pct": 0.05,
        "loser_threshold_pct": -0.05,
        "post_confirm_bars": 4,
        "horizons_hours": [4, 24, 72, 168, 336, 672],
    }, __doc__.splitlines()[0])

    in_path = Path(params.get("input_events"))
    if not in_path.is_absolute():
        in_path = PROJECT_ROOT / in_path
    print(f"loading events from {in_path}")
    src = pd.read_parquet(in_path)
    print(f"  total source events: {len(src)}")

    # Filter
    sub = src[(src["body_ret_min"] == 0.03) & (src["vol_ratio_min"] == 3.0)
              & (src["pullback_timeout_h"] == 24)].copy()
    print(f"  filtered to body=0.03 vol=3.0 timeout=24h: n={len(sub)}")

    horizons_h = list(params.get("horizons_hours", [4, 24, 72, 168, 336, 672]))
    n_q = int(params.get("n_quantiles", 5))
    win_th = float(params.get("winner_threshold_pct", 0.05))
    lose_th = float(params.get("loser_threshold_pct", -0.05))

    # Compute features for each post_confirm_bars value in sweep
    cfg_path = resolve_config_path(args)
    sweep = None
    if cfg_path:
        import json
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        sweep = cfg.get("sweep")
    sweep_pc_bars = (sweep or {}).get("post_confirm_bars", [int(params.get("post_confirm_bars", 4))])

    all_aug = []
    for pcb in sweep_pc_bars:
        aug = compute_features(sub, post_confirm_bars=pcb, horizons_h=horizons_h)
        aug["post_confirm_bars"] = pcb
        all_aug.append(aug)
    aug_all = pd.concat(all_aug, ignore_index=True)
    aug_all.to_parquet(out_dir / "events_with_features.parquet", index=False)
    print(f"\naugmented events saved: {len(aug_all)} rows (across {len(sweep_pc_bars)} post_confirm_bars values)")

    # Take post_confirm_bars=4 as primary for univariate analysis
    primary_pcb = sweep_pc_bars[0] if sweep_pc_bars else 4
    ev_primary = aug_all[aug_all["post_confirm_bars"] == primary_pcb].copy()
    print(f"\nprimary subset (post_confirm_bars={primary_pcb}): {len(ev_primary)}")

    fwd_at_buy_cols = [f"fwd_ret_{h}h" for h in horizons_h if f"fwd_ret_{h}h" in ev_primary.columns]
    fwd_post_cols = [f"fwd_ret_{h}h_post" for h in horizons_h if f"fwd_ret_{h}h_post" in ev_primary.columns]

    structural = ["upper_wick_ratio", "lower_wick_ratio", "body_to_range", "close_to_high_pct"]
    context = ["vs_24h_high_pct", "vs_72h_low_pct", "pre_24h_range_pct",
                "pre_consec_up_h", "pre_vol_quiet_ratio"]
    post = ["next_max_close_above", "next_avg_vol_ratio", "next_body_sum"]
    all_features = structural + context + post

    # Univariate quintile at fwd_ret_168h (at-buy)
    print("\n=== Univariate quintile (forward returns measured from B BUY entry) ===")
    qrows = []
    for feat in all_features:
        q = quintile_table(ev_primary, feat, fwd_at_buy_cols, n_q)
        if not q.empty:
            qrows.append(q)
    if qrows:
        qdf = pd.concat(qrows, ignore_index=True)
        qdf.to_csv(out_dir / "quintile_at_buy.csv", index=False)

        # Print 168h table for each feature
        print("\nfeature x quintile @ 168h (at-buy):")
        for feat in all_features:
            sub = qdf[(qdf.feature == feat) & (qdf.horizon == "fwd_ret_168h")]
            if not sub.empty:
                print(f"\n  {feat}:")
                print(sub[["quantile", "n", "mean", "median", "win"]].to_string(index=False))

    # Univariate quintile at fwd_ret_168h_post (post-confirm entry, delayed)
    print("\n=== Univariate quintile (forward returns measured from POST-CONFIRM entry) ===")
    qrows = []
    for feat in all_features:
        q = quintile_table(ev_primary, feat, fwd_post_cols, n_q)
        if not q.empty:
            qrows.append(q)
    if qrows:
        qdf_post = pd.concat(qrows, ignore_index=True)
        qdf_post.to_csv(out_dir / "quintile_post_confirm.csv", index=False)
        print("\nfeature x quintile @ 168h (post-confirm):")
        for feat in all_features:
            sub = qdf_post[(qdf_post.feature == feat) & (qdf_post.horizon == "fwd_ret_168h_post")]
            if not sub.empty:
                print(f"\n  {feat}:")
                print(sub[["quantile", "n", "mean", "median", "win"]].to_string(index=False))

    # Winner vs Loser group comparison (fwd_ret_168h at-buy)
    print(f"\n=== Winner (fwd_ret_168h > +{win_th*100:.0f}%) vs Loser (< {lose_th*100:.0f}%) ===")
    wlcomp = winner_loser_compare(ev_primary, "fwd_ret_168h", win_th, lose_th, all_features)
    wlcomp.to_csv(out_dir / "winner_loser_compare.csv", index=False)
    print(wlcomp.to_string(index=False))

    # Also for post-confirm
    print(f"\n=== Winner vs Loser (fwd_ret_168h_post) ===")
    wlcomp_post = winner_loser_compare(ev_primary, "fwd_ret_168h_post", win_th, lose_th, all_features)
    wlcomp_post.to_csv(out_dir / "winner_loser_compare_post.csv", index=False)
    print(wlcomp_post.to_string(index=False))

    # next_held boolean: simple True/False group compare
    print("\n=== next_held=True vs False (post-confirm 4h held above trigger low) ===")
    rows_nh = []
    for fwd in fwd_at_buy_cols + fwd_post_cols:
        if fwd not in ev_primary.columns: continue
        for label, mask in [("held=True", ev_primary["next_held"] == True),
                              ("held=False", ev_primary["next_held"] == False)]:
            s = ev_primary.loc[mask, fwd].dropna()
            if len(s) == 0: continue
            rows_nh.append({"group": label, "fwd": fwd, **_cell_stats(s)})
    nh_df = pd.DataFrame(rows_nh)
    nh_df.to_csv(out_dir / "next_held_compare.csv", index=False)
    print(nh_df.to_string(index=False))

    if cfg_path:
        update_config(cfg_path,
                       params={"n_quantiles": n_q,
                                "winner_threshold_pct": win_th,
                                "loser_threshold_pct": lose_th,
                                "horizons_hours": horizons_h,
                                "post_confirm_bars": int(primary_pcb)},
                       data={"symbol_count": int(sub["symbol"].nunique())},
                       results_summary={"n_events_processed": int(len(ev_primary)),
                                        "n_winners": int((ev_primary["fwd_ret_168h"] > win_th).sum()),
                                        "n_losers": int((ev_primary["fwd_ret_168h"] < lose_th).sum())})


if __name__ == "__main__":
    main()
