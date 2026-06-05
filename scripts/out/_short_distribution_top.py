"""2번 전략 백테스트 — Distribution Top (상승 추세 끝물의 Lower High + MA20 이탈).

대상 TF: 4h, 1h
MA: 해당 TF 의 MA20

룰:
1. 직전 N봉 동안 close > MA20 인 비율 ≥ 60% (= 상승 추세 진행 중)
2. 그 N봉 안의 high 최댓값 = peak1 (직전 swing high)
3. 그 후 최근 K봉의 high 최댓값 = peak2
4. peak2 < peak1 (= 다음 파동이 고점 갱신 실패)
5. 오늘 close < MA20 (= MA20 이탈 트리거)
→ 다음 봉 시가에 숏, hold H봉 후 청산

TF별 파라미터:
- 1h: N=48 (2일), K=12 (12시간), hold={6, 12, 24, 48} (6h~2일)
- 4h: N=42 (1주), K=6 (1일), hold={6, 12, 24} (1~4일)

신규 상장: 첫 200봉 컷
dedup: 1h 24봉, 4h 12봉
강제청산 -100% 캡
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
CACHE_1H = ROOT / "data" / "cache" / "crypto" / "1h"

TF_CONFIGS = {
    "4h": {
        "resample": "4H",
        "N_lookback": 42,
        "K_recent": 6,
        "hold_options": [6, 12, 24],
        "dedup": 12,
    },
    "1h": {
        "resample": None,  # 원본
        "N_lookback": 48,
        "K_recent": 12,
        "hold_options": [6, 12, 24, 48],
        "dedup": 24,
    },
}

UP_TREND_RATIO = 0.60  # close > MA20 인 봉 비율 ≥ 60%


def resample_ohlcv(df, rule):
    d = df.copy()
    d["dt"] = pd.to_datetime(d["timestamp"], unit="ms")
    d = d.set_index("dt").sort_index()
    r = d.resample(rule, label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()
    return r.reset_index(drop=True)


def dedup_signals(sig, days):
    idx = np.where(sig)[0]
    if len(idx) == 0:
        return np.zeros_like(sig, dtype=bool)
    keep = [idx[0]]
    for i in idx[1:]:
        if i - keep[-1] >= days:
            keep.append(i)
    out = np.zeros_like(sig, dtype=bool)
    out[keep] = True
    return out


def run_tf(files, tf_label, cfg):
    print(f"\n>>>>> {tf_label} 분석 시작")
    N = cfg["N_lookback"]
    K = cfg["K_recent"]
    holds = cfg["hold_options"]
    dedup_w = cfg["dedup"]

    # hold → list of short returns
    results = {h: [] for h in holds}
    total_signals = 0
    valid_symbols = 0

    for i, f in enumerate(files):
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if len(df) < 500:  # 1h 기준 충분 데이터
            continue
        df = df.sort_values("timestamp").reset_index(drop=True)

        if cfg["resample"] is not None:
            d = resample_ohlcv(df, cfg["resample"])
        else:
            d = df[["open", "high", "low", "close", "volume"]].reset_index(drop=True)

        if len(d) < N + K + 200:
            continue
        # 신규 상장 첫 200봉 컷
        d = d.iloc[200:].reset_index(drop=True)
        if len(d) < N + K + 50:
            continue

        valid_symbols += 1
        d["ma20"] = d["close"].rolling(20, min_periods=20).mean()
        n = len(d)

        # 조건 1: 직전 N봉 close > MA20 비율
        above_ma20 = (d["close"] > d["ma20"]).astype(int)
        up_trend_ratio = above_ma20.shift(K).rolling(N, min_periods=N).mean()

        # 조건 2,3: peak1 = 직전 N봉 (K봉 전부터) 의 high 최댓값
        peak1 = d["high"].shift(K).rolling(N, min_periods=N).max()
        # peak2 = 최근 K봉의 high 최댓값 (오늘 포함)
        peak2 = d["high"].rolling(K, min_periods=K).max()

        # 조건 4,5
        cond = (
            (up_trend_ratio >= UP_TREND_RATIO) &
            (peak2 < peak1) &
            (d["close"] < d["ma20"])
        )
        sig = dedup_signals(cond.fillna(False).values, dedup_w)
        total_signals += int(sig.sum())

        # 진입 = 다음 봉 시가
        entry = d["open"].shift(-1)
        sig_idx = np.where(sig)[0]
        for h in holds:
            for t in sig_idx:
                if t + 1 + h >= n:
                    continue
                e = entry.iloc[t]
                x = d["close"].iloc[t + 1 + h]
                if pd.isna(e) or pd.isna(x):
                    continue
                ret = -(x / e - 1)
                results[h].append(max(ret, -1.0))

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(files)} 처리")

    print(f"유효 심볼: {valid_symbols}, 총 신호: {total_signals}")
    rows = []
    for h, rets in results.items():
        if not rets:
            continue
        s = pd.Series(rets)
        rows.append({
            "TF": tf_label,
            "hold_봉": h,
            "표본수": int(len(s)),
            "윈율": float((s > 0).mean()),
            "평균_숏수익": float(s.mean()),
            "중위_숏수익": float(s.median()),
            "p25": float(s.quantile(0.25)),
            "p75": float(s.quantile(0.75)),
            "표준편차": float(s.std()),
            "최대손실": float(s.min()),
            "Sharpe": float(s.mean() / s.std()) if s.std() > 0 else np.nan,
            "squeeze_플20이상_손실_비율": float((s <= -0.20).mean()),
        })
    return pd.DataFrame(rows)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CACHE_1H.glob("*.parquet"))
    print(f"1h 캐시 심볼 수: {len(files)}")

    all_out = []
    for tf_label, cfg in TF_CONFIGS.items():
        df_tf = run_tf(files, tf_label, cfg)
        print(f"\n=== {tf_label} 결과 ===")
        print(df_tf.to_string(index=False, float_format=lambda x: f"{x:+.4f}"))
        all_out.append(df_tf)

    final = pd.concat(all_out, ignore_index=True)
    out_path = ROOT / "scripts" / "out" / "short_distribution_top.csv"
    final.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nCSV: {out_path}")


if __name__ == "__main__":
    main()
