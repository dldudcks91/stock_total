"""일봉 데이터 수집. FDR 기반. 주/월봉은 항상 일봉에서 resample.

캐시는 KR(KOSPI 등) 6자리 종목코드 기준 ``data/cache/kr/``에 저장.
US 대량 수집은 ``data/sources/stocks.py``의 ThreadPool 파이프라인을 사용.
"""
from pathlib import Path
from typing import Optional
import FinanceDataReader as fdr
import pandas as pd

CACHE_ROOT = Path(__file__).resolve().parent.parent / "data" / "cache"
DATA_DIR = CACHE_ROOT / "kr"  # 하위호환: 기존 KR 단일 경로

OHLCV_AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def _cache_dir(market: str = "KR") -> Path:
    """시장별 캐시 디렉터리 (KR=data/cache/kr, US=data/cache/us)."""
    return CACHE_ROOT / str(market).lower()


def fetch_daily(ticker: str, start: str, end: Optional[str] = None) -> pd.DataFrame:
    df = fdr.DataReader(ticker, start, end)
    df.index = pd.to_datetime(df.index)
    return df


def save_daily(ticker: str, df: pd.DataFrame, market: str = "KR") -> Path:
    d = _cache_dir(market)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{ticker}.parquet"
    df.to_parquet(path)
    return path


def load_daily(ticker: str, market: str = "KR") -> pd.DataFrame:
    return pd.read_parquet(_cache_dir(market) / f"{ticker}.parquet")


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    return daily.resample("W-FRI").agg(OHLCV_AGG).dropna()


def to_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    return daily.resample("ME").agg(OHLCV_AGG).dropna()
