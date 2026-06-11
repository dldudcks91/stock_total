"""Bitget USDT-M universe 필터 — 주식/ETF perpetual 제외.

Bitget 은 진짜 코인 외에도 미국 주식·ETF perpetual 을 제공한다
(`AAPLUSDT`, `QQQUSDT`, `TSLAUSDT` 등). 본 모듈은 그들을 universe 에서 자동 제외.

리스트는 휴리스틱 (Bitget 상장 시점 확장 시 갱신 필요). 미명시 종목은 코인으로 가정.
"""
from __future__ import annotations

# 미국 주식 + ETF 티커 (Bitget USDT-M perpetual 으로 거래되는 것 위주).
# 변경 시 알파벳 순 유지 권장.
STOCK_TOKEN_TICKERS: frozenset = frozenset({
    # Mega-cap stocks
    "AAPL", "ADBE", "AMD", "AMZN", "AVGO", "COST", "CRM", "CSCO", "GOOG",
    "GOOGL", "INTC", "META", "MSFT", "NFLX", "NVDA", "ORCL", "PEP", "TMUS",
    "TSLA", "TXN",
    # Semiconductors
    "AMAT", "ARM", "ASML", "KLAC", "LRCX", "MRVL", "MU", "QCOM", "SMCI", "TSM",
    # Finance
    "BAC", "C", "COIN", "GS", "HOOD", "JPM", "MA", "MS", "PYPL", "SOFI", "SQ",
    "V", "WFC",
    # Healthcare
    "ABBV", "ABT", "BMY", "DHR", "JNJ", "LLY", "MRK", "NVO", "PFE", "TMO",
    "UNH",
    # Consumer
    "DIS", "HD", "KO", "LOW", "MCD", "NKE", "PG", "SBUX", "TGT", "WMT",
    # Energy
    "COP", "CVX", "OXY", "SLB", "XOM",
    # China / Foreign
    "BABA", "BIDU", "JD", "LYFT", "NIO", "PDD", "SHOP", "SNAP", "TCEHY",
    "UBER", "ZM",
    # Speculative / Meme stocks
    "AMC", "BB", "GME", "LCID", "MARA", "MSTR", "PATH", "PLTR", "RBLX",
    "RIOT", "RIVN",
    # ETF — leveraged / sector
    "ARKB", "ARKK", "EEM", "EWJ", "EWT", "EWY", "EWZ", "FXI", "NVDL",
    "QQQ", "SOXL", "SOXS", "SPXL", "SPXS", "SPY", "TQQQ", "TSLL",
    "XLE", "XLF", "XLI", "XLK", "XLP", "XLV",
    # ETF — BTC / crypto
    "BITO", "BITX", "BRRR", "FBTC", "GBTC", "IBIT",
    # ETF — broad market
    "DIA", "IVV", "IWM", "SCHD", "SCHX", "VEA", "VOO", "VTI", "VTV", "VUG",
    "VWO",
})


def is_stock_token(symbol: str) -> bool:
    """Bitget 심볼이 주식/ETF perpetual 인지 판정. 매칭은 USDT 접미사 제거 후 비교.

    예:
        >>> is_stock_token("AAPLUSDT")
        True
        >>> is_stock_token("BTCUSDT")
        False
    """
    if symbol.endswith("USDT"):
        return symbol[:-4] in STOCK_TOKEN_TICKERS
    return symbol in STOCK_TOKEN_TICKERS


def filter_crypto_universe(symbols):
    """symbol 리스트에서 주식 토큰 제거."""
    return [s for s in symbols if not is_stock_token(s)]
