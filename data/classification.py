"""코인 행동 분류 (behavioral classification).

BTC를 벤치마크로 두고, 캐시에 있는 모든 심볼에 대해 6개 메트릭을 계산하여
4그룹(leader / beta_follower / whale_driven / pump_dump)으로 분류한다.

사용 예:
    python -m data.classification --start 2023-01-01 --end 2025-12-31

산출:
    data/cache/classification.parquet
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

CACHE_DIR = Path(__file__).parent / "cache"
DEFAULT_OUT = CACHE_DIR / "classification.parquet"

OHLCV_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
    "amount": "sum",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _cache_path(symbol: str) -> Path:
    return CACHE_DIR / f"bitget_{symbol}_1h.parquet"


def discover_symbols(cache_dir: Path = CACHE_DIR) -> list[str]:
    """캐시 디렉터리에서 사용 가능한 심볼 목록 추출."""
    if not cache_dir.exists():
        return []
    out = []
    for p in sorted(cache_dir.glob("bitget_*_1h.parquet")):
        name = p.stem  # bitget_BTCUSDT_1h
        if not name.startswith("bitget_") or not name.endswith("_1h"):
            continue
        sym = name[len("bitget_"):-len("_1h")]
        if sym:
            out.append(sym)
    return out


def load_daily(symbol: str, cache_dir: Path = CACHE_DIR) -> pd.DataFrame:
    """1h 캐시를 직접 읽어 일봉으로 리샘플 (resample.py의 timestamp 버그 회피).

    반환: DatetimeIndex, columns = open/high/low/close/volume/amount
    """
    path = cache_dir / f"bitget_{symbol}_1h.parquet"
    df = pd.read_parquet(path)
    if df.empty:
        return pd.DataFrame(columns=list(OHLCV_AGG.keys())).astype(float)
    df = df.copy()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("dt")
    out = df.resample("1D", label="left", closed="left").agg(OHLCV_AGG).dropna()
    return out


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def kurtosis_pearson(x: np.ndarray) -> float:
    """Pearson kurtosis (Fisher=False). 정규분포 = 3."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 4:
        return float("nan")
    m = x.mean()
    s = x.std(ddof=0)
    if s == 0:
        return float("nan")
    return float(((x - m) ** 4).mean() / (s ** 4))


def kurtosis_trimmed(x: np.ndarray, pct: float = 0.005) -> float:
    """양극단 ``pct`` 비율을 윈저화한 후 kurtosis 계산.

    단발 충격(예: TRX 단일봉)으로 인한 kurtosis 폭발을 억제.
    pct=0.005 → 상하 0.5%씩 컷오프.
    """
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 20:
        return kurtosis_pearson(x)
    lo = np.quantile(x, pct)
    hi = np.quantile(x, 1 - pct)
    x_w = np.clip(x, lo, hi)
    return kurtosis_pearson(x_w)


def pump_recurrence(ret: pd.Series, z_threshold: float = 5.0) -> float:
    """펌프 재발률: ``|z|>z_threshold`` 이벤트가 분포된 분기 비율.

    - 단발 충격: 1 분기에만 → 낮은 값
    - 반복 펌프: 여러 분기에 걸쳐 → 높은 값

    반환: 0~1. 펌프 이벤트가 0개면 0 반환.
    """
    ret = ret.dropna()
    if ret.empty:
        return 0.0
    mu = ret.mean()
    sd = ret.std(ddof=0)
    if sd == 0:
        return 0.0
    z = (ret - mu) / sd
    pump_mask = z.abs() > z_threshold
    if pump_mask.sum() == 0:
        return 0.0
    # 분기 단위 그룹핑 (DatetimeIndex 가정)
    if not isinstance(ret.index, pd.DatetimeIndex):
        return 0.0
    quarters = ret.index.to_period("Q")
    total_q = quarters.unique().size
    if total_q == 0:
        return 0.0
    pump_q = quarters[pump_mask].unique().size
    return float(pump_q / total_q)


def hurst_rs(x: np.ndarray, lags: Iterable[int] = (10, 20, 40, 80, 160)) -> float:
    """R/S 분석으로 Hurst 지수 추정. 시계열은 returns(또는 log price diff).

    R/S(n) ~ c * n^H 의 로그회귀 기울기.
    """
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n_total = x.size
    if n_total < 32:
        return float("nan")

    log_n = []
    log_rs = []
    for n in lags:
        if n < 8 or n > n_total // 2:
            continue
        # 비중첩 윈도우들
        n_chunks = n_total // n
        if n_chunks < 1:
            continue
        rs_vals = []
        for i in range(n_chunks):
            seg = x[i * n:(i + 1) * n]
            mean = seg.mean()
            dev = seg - mean
            cumdev = np.cumsum(dev)
            R = cumdev.max() - cumdev.min()
            S = seg.std(ddof=0)
            if S > 0 and R > 0:
                rs_vals.append(R / S)
        if not rs_vals:
            continue
        log_n.append(np.log(n))
        log_rs.append(np.log(np.mean(rs_vals)))

    if len(log_n) < 2:
        return float("nan")
    slope, _ = np.polyfit(np.array(log_n), np.array(log_rs), 1)
    return float(slope)


def max_drawdown(close: pd.Series) -> float:
    if close.empty:
        return float("nan")
    cummax = close.cummax()
    dd = close / cummax - 1.0
    return float(dd.min())


@dataclass
class CoinMetrics:
    symbol: str
    r2_btc: float
    beta_btc: float
    hurst: float
    kurtosis: float
    kurt_trimmed: float
    pump_count_per_year: float
    pump_recurrence: float
    realized_vol_annual: float
    volume_score_3y: float
    listing_days: int
    last_price: float
    max_drawdown_3y: float
    n_obs: int

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def compute_metrics(
    daily: pd.DataFrame,
    btc_ret: pd.Series,
    symbol: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> CoinMetrics:
    """단일 코인의 일봉으로 6개 + 보조 메트릭 계산."""
    df = daily.copy()
    if start is not None:
        df = df[df.index >= start]
    if end is not None:
        df = df[df.index <= end]

    if df.empty or "close" not in df.columns:
        return _empty_metrics(symbol, daily)

    close = df["close"].astype(float)
    ret = close.pct_change().dropna()
    n_obs = int(ret.size)

    if n_obs < 5:
        return _empty_metrics(symbol, daily)

    # Volatility (annualized)
    realized_vol_annual = float(ret.std(ddof=0) * np.sqrt(365))

    # Pump count per year (|z| > 5)
    mu, sd = ret.mean(), ret.std(ddof=0)
    if sd > 0:
        z = (ret - mu) / sd
        pump_count = int((z.abs() > 5).sum())
    else:
        pump_count = 0
    years = max(n_obs / 365.0, 1e-6)
    pump_count_per_year = pump_count / years

    # Kurtosis (raw + trimmed/winsorized to suppress single-bar shocks)
    kurt = kurtosis_pearson(ret.values)
    kurt_t = kurtosis_trimmed(ret.values, pct=0.005)

    # Pump recurrence (분기별 분포)
    pump_rec = pump_recurrence(ret, z_threshold=5.0)

    # Hurst on returns
    hurst = hurst_rs(ret.values)

    # R^2 / beta vs BTC: align on date index
    aligned = pd.concat([ret.rename("c"), btc_ret.rename("b")], axis=1, sort=False).dropna()
    if aligned.shape[0] >= 5 and aligned["b"].std(ddof=0) > 0 and aligned["c"].std(ddof=0) > 0:
        cov = float(((aligned["c"] - aligned["c"].mean()) * (aligned["b"] - aligned["b"].mean())).mean())
        var_b = float(aligned["b"].var(ddof=0))
        beta = cov / var_b if var_b > 0 else float("nan")
        corr = float(aligned["c"].corr(aligned["b"]))
        r2 = float(corr ** 2) if np.isfinite(corr) else float("nan")
    else:
        beta = float("nan")
        r2 = float("nan")

    # Volume score 3y (sum of amount)
    vol_score = float(df["amount"].sum()) if "amount" in df.columns else float("nan")

    # Listing days = # of daily bars in cache (full, not truncated by --start/--end? we use windowed)
    listing_days = int(df.shape[0])
    last_price = float(close.iloc[-1])
    mdd = max_drawdown(close)

    return CoinMetrics(
        symbol=symbol,
        r2_btc=r2,
        beta_btc=beta,
        hurst=hurst,
        kurtosis=kurt,
        kurt_trimmed=kurt_t,
        pump_count_per_year=pump_count_per_year,
        pump_recurrence=pump_rec,
        realized_vol_annual=realized_vol_annual,
        volume_score_3y=vol_score,
        listing_days=listing_days,
        last_price=last_price,
        max_drawdown_3y=mdd,
        n_obs=n_obs,
    )


def _empty_metrics(symbol: str, daily: pd.DataFrame) -> CoinMetrics:
    listing = int(daily.shape[0])
    last = float(daily["close"].iloc[-1]) if not daily.empty else float("nan")
    return CoinMetrics(
        symbol=symbol,
        r2_btc=float("nan"),
        beta_btc=float("nan"),
        hurst=float("nan"),
        kurtosis=float("nan"),
        kurt_trimmed=float("nan"),
        pump_count_per_year=float("nan"),
        pump_recurrence=float("nan"),
        realized_vol_annual=float("nan"),
        volume_score_3y=float("nan"),
        listing_days=listing,
        last_price=last,
        max_drawdown_3y=float("nan"),
        n_obs=0,
    )


# ---------------------------------------------------------------------------
# Rule-based classification
# ---------------------------------------------------------------------------
def classify_rules(df: pd.DataFrame, btc_symbol: str = "BTCUSDT") -> pd.Series:
    """메트릭 데이터프레임 → tier_rule Series.

    티어 규칙 (위에서 아래 우선):
        benchmark        : BTC 자체
        stable           : realized_vol < 0.05 (스테이블)
        unclassified_new : listing_days < 365  (1년 미만)
        pump_dump        : kurt_trimmed > 20 AND pump_recurrence > 0.3
                           (윈저화 후에도 두꺼운 꼬리 + 반복 펌프 → 진짜 주작)
        co_leader        : 0.5 ≤ R² ≤ 0.75 AND volume 상위 5% AND kurt_trimmed < 10
                           (ETH/SOL 류: BTC와 동조하지만 자기 시장 리드)
        leader           : R² < 0.5 AND hurst > 0.55 AND kurt_trimmed < 8
                           AND volume 상위 30%
        beta_follower    : R² > 0.6 AND beta > 1.0 AND kurt_trimmed < 8
                           (volume 상위 5%는 co_leader가 먼저 잡음)
        whale_driven     : 8 ≤ kurt_trimmed < 20 AND pump_count > 2
                           (단발 충격 흡수)
        mixed            : 그 외
    """
    out = pd.Series(index=df.index, dtype="object")

    # Volume thresholds
    vs = df["volume_score_3y"]
    valid = vs.notna()
    vs_top30_thr = float(vs[valid].quantile(0.7)) if valid.sum() >= 5 else float("-inf")
    vs_top05_thr = float(vs[valid].quantile(0.95)) if valid.sum() >= 20 else float("inf")

    for sym, row in df.iterrows():
        if sym == btc_symbol:
            out[sym] = "benchmark"
            continue

        rv = row.get("realized_vol_annual")
        if pd.notna(rv) and rv < 0.05:
            out[sym] = "stable"
            continue

        ld = row.get("listing_days", 0)
        if pd.notna(ld) and ld < 365:
            out[sym] = "unclassified_new"
            continue

        r2 = row.get("r2_btc")
        beta = row.get("beta_btc")
        hurst = row.get("hurst")
        kurt_t = row.get("kurt_trimmed")
        pcount = row.get("pump_count_per_year")
        prec = row.get("pump_recurrence")
        v_score = row.get("volume_score_3y", float("nan"))
        v_top30 = pd.notna(v_score) and v_score >= vs_top30_thr
        v_top05 = pd.notna(v_score) and v_score >= vs_top05_thr

        # 1) pump_dump — 두꺼운 꼬리 + 반복 펌프 모두 충족해야
        if (
            pd.notna(kurt_t) and kurt_t > 20
            and pd.notna(prec) and prec > 0.3
        ):
            out[sym] = "pump_dump"
            continue

        # 2) co_leader — BTC와 동조하지만 거래량 압도적, 클린한 메이저 알트
        if (
            pd.notna(r2) and 0.5 <= r2 <= 0.75
            and v_top05
            and pd.notna(kurt_t) and kurt_t < 10
        ):
            out[sym] = "co_leader"
            continue

        # 3) leader — 독립 추세 + 거래량 상위 + 클린
        if (
            pd.notna(r2) and r2 < 0.5
            and pd.notna(hurst) and hurst > 0.55
            and pd.notna(kurt_t) and kurt_t < 8
            and v_top30
        ):
            out[sym] = "leader"
            continue

        # 4) beta_follower — BTC 추종 + 베타 > 1 + 클린
        if (
            pd.notna(r2) and r2 > 0.6
            and pd.notna(beta) and beta > 1.0
            and pd.notna(kurt_t) and kurt_t < 8
        ):
            out[sym] = "beta_follower"
            continue

        # 5) whale_driven — 두꺼운 꼬리지만 재발률 낮음 (단발 충격) 또는 적당한 펌프
        if (
            pd.notna(kurt_t) and 8 <= kurt_t < 20
            and pd.notna(pcount) and pcount > 2
        ):
            out[sym] = "whale_driven"
            continue

        out[sym] = "mixed"

    return out


# ---------------------------------------------------------------------------
# K-means (no sklearn)
# ---------------------------------------------------------------------------
def _zscore(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mu = np.nanmean(X, axis=0)
    sd = np.nanstd(X, axis=0, ddof=0)
    sd = np.where(sd == 0, 1.0, sd)
    Z = (X - mu) / sd
    return Z, mu, sd


def _kmeans(X: np.ndarray, k: int, n_init: int = 10, max_iter: int = 200, seed: int = 42):
    rng = np.random.default_rng(seed)
    best_labels = None
    best_centers = None
    best_inertia = np.inf
    n = X.shape[0]
    if n < k:
        # Trivial
        labels = np.arange(n) % k
        centers = np.zeros((k, X.shape[1]))
        for i in range(k):
            members = X[labels == i]
            centers[i] = members.mean(axis=0) if members.size else 0.0
        return labels, centers

    for init in range(n_init):
        # k-means++ ish: random start
        idx = rng.choice(n, size=k, replace=False)
        centers = X[idx].copy()
        prev_labels = None
        for _ in range(max_iter):
            # Assign
            d2 = ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
            labels = d2.argmin(axis=1)
            if prev_labels is not None and np.array_equal(labels, prev_labels):
                break
            prev_labels = labels
            # Update
            for j in range(k):
                members = X[labels == j]
                if members.size:
                    centers[j] = members.mean(axis=0)
                else:
                    centers[j] = X[rng.integers(0, n)]
        # Inertia
        d2 = ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        labels = d2.argmin(axis=1)
        inertia = d2[np.arange(n), labels].sum()
        if inertia < best_inertia:
            best_inertia = inertia
            best_labels = labels
            best_centers = centers.copy()
    return best_labels, best_centers


KM_FEATURES = [
    "r2_btc",
    "beta_btc",
    "hurst",
    "kurt_trimmed",
    "pump_count_per_year",
    "realized_vol_annual",
]


def classify_kmeans(df: pd.DataFrame, btc_symbol: str = "BTCUSDT", seed: int = 42) -> pd.Series:
    """6 메트릭 z-score → KMeans(k=4) → 자동 라벨 매핑.

    매핑 규칙(중심값 기준):
        - kurtosis 가장 큰 클러스터 → pump_dump
        - r2_btc 가장 작은 클러스터(남은 것 중) → leader
        - r2_btc 가장 큰 클러스터(남은 것 중) → beta_follower
        - 나머지 → whale_driven
    """
    feats = df.copy()
    # Pre-filter symbols that should not be clustered
    excludable = (
        (feats.index == btc_symbol)
        | (feats["realized_vol_annual"] < 0.05)
        | (feats["listing_days"] < 365)
    )

    out = pd.Series(index=feats.index, dtype="object")
    out[feats.index == btc_symbol] = "benchmark"
    stable_mask = feats["realized_vol_annual"] < 0.05
    out[stable_mask & (feats.index != btc_symbol)] = "stable"
    new_mask = (feats["listing_days"] < 365) & ~stable_mask & (feats.index != btc_symbol)
    out[new_mask] = "unclassified_new"

    # Cluster only the remainder with full metrics
    cand = feats.loc[~excludable, KM_FEATURES].dropna()
    if cand.shape[0] < 4:
        out.loc[cand.index] = "mixed"
        return out

    X = cand.values.astype(float)
    Z, _, _ = _zscore(X)
    labels, centers = _kmeans(Z, k=4, seed=seed)

    # Centers are in z-space; we use them to rank
    # Convert centers back to original feature space for interpretability
    mu = X.mean(axis=0)
    sd = X.std(axis=0, ddof=0)
    sd = np.where(sd == 0, 1.0, sd)
    centers_orig = centers * sd + mu

    cdf = pd.DataFrame(centers_orig, columns=KM_FEATURES)
    name_map: dict[int, str] = {}

    # 1) pump_dump = highest kurt_trimmed
    pump_idx = int(cdf["kurt_trimmed"].idxmax())
    name_map[pump_idx] = "pump_dump"
    remaining = [i for i in range(4) if i not in name_map]

    # 2) leader = lowest r2_btc among remaining
    sub = cdf.loc[remaining, "r2_btc"]
    leader_idx = int(sub.idxmin())
    name_map[leader_idx] = "leader"
    remaining = [i for i in remaining if i != leader_idx]

    # 3) beta_follower = highest r2_btc among remaining
    sub = cdf.loc[remaining, "r2_btc"]
    bf_idx = int(sub.idxmax())
    name_map[bf_idx] = "beta_follower"
    remaining = [i for i in remaining if i != bf_idx]

    # 4) Last → whale_driven
    name_map[remaining[0]] = "whale_driven"

    label_series = pd.Series([name_map[int(l)] for l in labels], index=cand.index)
    out.loc[cand.index] = label_series

    # Anything still NaN -> mixed
    out = out.fillna("mixed")
    return out


# ---------------------------------------------------------------------------
# 7-tier → 4-group consolidation
# ---------------------------------------------------------------------------
# 사용자 합의: 최종 노출은 4그룹 (+ 시스템 2개)
#   trend    = 추세추종형 (자기 시장 가진 메이저)
#   follower = 큰형 추종형 (BTC와 강하게 동조)
#   whale    = 세력형 (단발 충격 또는 적당한 펌프)
#   junk     = 잡코인 (주작 의심 + 신규 미검증 + 분류 불가)
GROUP4_MAP: dict[str, str] = {
    "leader": "trend",
    "co_leader": "trend",
    "beta_follower": "follower",
    "whale_driven": "whale",
    "pump_dump": "junk",
    "unclassified_new": "junk",
    "mixed": "junk",
    # 시스템 라벨은 그대로 유지
    "benchmark": "benchmark",
    "stable": "stable",
}


def to_group4(tier: str) -> str:
    return GROUP4_MAP.get(tier, "junk")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def build_features(
    symbols: list[str],
    btc_symbol: str = "BTCUSDT",
    start: str | None = None,
    end: str | None = None,
    cache_dir: Path = CACHE_DIR,
    verbose: bool = False,
    daily_loader=None,
) -> pd.DataFrame:
    """Returns a DataFrame indexed by symbol with all metric columns."""
    if daily_loader is None:
        def daily_loader(sym: str) -> pd.DataFrame:
            return load_daily(sym, cache_dir=cache_dir)

    start_ts = pd.Timestamp(start, tz="UTC") if start else None
    end_ts = pd.Timestamp(end, tz="UTC") if end else None

    # Need BTC first
    if btc_symbol not in symbols:
        raise ValueError(f"benchmark {btc_symbol} not in symbol list")

    btc_daily = daily_loader(btc_symbol)
    if btc_daily.empty:
        raise ValueError(f"benchmark {btc_symbol} has no data")
    btc_close = btc_daily["close"].astype(float)
    btc_ret = btc_close.pct_change().dropna()
    if start_ts is not None:
        btc_ret = btc_ret[btc_ret.index >= start_ts]
    if end_ts is not None:
        btc_ret = btc_ret[btc_ret.index <= end_ts]

    rows = []
    for i, sym in enumerate(symbols):
        try:
            daily = daily_loader(sym)
        except Exception as e:
            if verbose:
                print(f"[skip] {sym}: load error {e}", file=sys.stderr)
            continue
        if daily.empty:
            continue
        m = compute_metrics(daily, btc_ret, sym, start=start_ts, end=end_ts)
        rows.append(m.to_dict())
        if verbose and (i + 1) % 25 == 0:
            print(f"  processed {i + 1}/{len(symbols)}", file=sys.stderr)

    if not rows:
        raise RuntimeError("No symbols produced metrics; cache appears empty.")

    out = pd.DataFrame(rows).set_index("symbol")
    return out


def classify(
    symbols: list[str] | None = None,
    btc_symbol: str = "BTCUSDT",
    start: str | None = "2023-01-01",
    end: str | None = "2025-12-31",
    method: str = "both",
    cache_dir: Path = CACHE_DIR,
    out_path: Path | None = DEFAULT_OUT,
    verbose: bool = False,
    daily_loader=None,
) -> pd.DataFrame:
    """End-to-end: 메트릭 빌드 → tier 부여 → parquet 저장 (out_path가 있으면).

    daily_loader: 테스트용 주입. 시그니처 (symbol)->DataFrame.
    """
    if symbols is None:
        symbols = discover_symbols(cache_dir)
    if not symbols:
        raise FileNotFoundError(
            f"Empty symbol list (cache_dir={cache_dir}). "
            "캐시가 비어있는지 확인하세요. 다른 세션에서 데이터 다운로드 중이라면 완료를 기다리세요."
        )
    if btc_symbol not in symbols:
        raise FileNotFoundError(
            f"Benchmark {btc_symbol} not found in cache ({cache_dir}). "
            "BTCUSDT 1h parquet이 필요합니다."
        )

    feats = build_features(
        symbols,
        btc_symbol=btc_symbol,
        start=start,
        end=end,
        cache_dir=cache_dir,
        verbose=verbose,
        daily_loader=daily_loader,
    )

    tier_rule = classify_rules(feats, btc_symbol=btc_symbol) if method in ("rules", "both") else pd.Series(index=feats.index, dtype="object")
    tier_kmeans = classify_kmeans(feats, btc_symbol=btc_symbol) if method in ("kmeans", "both") else pd.Series(index=feats.index, dtype="object")

    # tier_final: prefer rule (excluding mixed) else kmeans
    if method == "rules":
        tier_final = tier_rule
    elif method == "kmeans":
        tier_final = tier_kmeans
    else:  # both
        tier_final = tier_rule.copy()
        # If rule says "mixed", fall back to kmeans
        mask = tier_final == "mixed"
        tier_final[mask] = tier_kmeans[mask]

    out = feats.copy()
    out["tier_rule"] = tier_rule
    out["tier_kmeans"] = tier_kmeans
    out["tier_detail"] = tier_final  # 7-way (leader/co_leader/...)
    out["tier_final"] = tier_final.map(GROUP4_MAP).fillna("junk")  # 4-way
    out["classified_at"] = datetime.now(timezone.utc).isoformat()
    out = out.reset_index().rename(columns={"index": "symbol"})

    # Column order
    cols = [
        "symbol", "tier_final", "tier_detail", "tier_rule", "tier_kmeans",
        "r2_btc", "beta_btc", "hurst", "kurtosis", "kurt_trimmed",
        "pump_count_per_year", "pump_recurrence", "realized_vol_annual",
        "volume_score_3y", "listing_days", "last_price", "max_drawdown_3y",
        "classified_at",
    ]
    extras = [c for c in out.columns if c not in cols]
    out = out[cols + extras]

    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(out_path, index=False)

    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="크립토 코인 행동 분류")
    p.add_argument("--start", default="2023-01-01")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--method", choices=["rules", "kmeans", "both"], default="both")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--btc-symbol", default="BTCUSDT")
    p.add_argument("--symbol", action="append", help="명시 심볼 (반복 가능). 미지정 시 캐시 전체")
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        df = classify(
            symbols=args.symbol,
            btc_symbol=args.btc_symbol,
            start=args.start,
            end=args.end,
            method=args.method,
            out_path=Path(args.out),
            verbose=args.verbose,
        )
    except FileNotFoundError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2
    counts = df["tier_final"].value_counts().to_dict()
    print(f"saved: {args.out}  ({len(df)} symbols)")
    print(f"tier_final counts: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
