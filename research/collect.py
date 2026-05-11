"""일봉 데이터 수집. FDR 기반. 주/월봉은 항상 일봉에서 resample.

캐시는 KR(KOSPI 등) 6자리 종목코드 기준 ``data/cache/kr/``에 저장.
US 대량 수집은 ``data/sources/stocks.py``의 ThreadPool 파이프라인을 사용.
"""
from pathlib import Path
from typing import Optional
import FinanceDataReader as fdr
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "kr"

OHLCV_AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


def fetch_daily(ticker: str, start: str, end: Optional[str] = None) -> pd.DataFrame:
    df = fdr.DataReader(ticker, start, end)
    df.index = pd.to_datetime(df.index)
    return df


def save_daily(ticker: str, df: pd.DataFrame) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{ticker}.parquet"
    df.to_parquet(path)
    return path


def load_daily(ticker: str) -> pd.DataFrame:
    return pd.read_parquet(DATA_DIR / f"{ticker}.parquet")


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    return daily.resample("W-FRI").agg(OHLCV_AGG).dropna()


def to_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    return daily.resample("ME").agg(OHLCV_AGG).dropna()
