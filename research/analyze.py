"""정량 지표 계산. 일봉 입력 → 리포트용 핵심 지표 dict."""
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["MA20"] = out["Close"].rolling(20).mean()
    out["MA60"] = out["Close"].rolling(60).mean()
    out["MA120"] = out["Close"].rolling(120).mean()
    out["ret_1d"] = out["Close"].pct_change()
    out["vol_20d_ann"] = out["ret_1d"].rolling(20).std() * (252 ** 0.5)
    out["RSI14"] = rsi(out["Close"], 14)
    return out


def report_metrics(df: pd.DataFrame, market: str = "KR") -> dict:
    """리포트의 정량 섹션에 그대로 들어갈 핵심 지표.

    market: "KR" 은 원(정수) 가격, 그 외("US" 등)는 달러(소수점 2자리).
    KR 만 int 로 반올림하고 US 는 소수점을 보존한다 (예: $150.34 가 150 으로
    잘리던 버그 방지).
    """
    df = add_indicators(df)
    last = df.iloc[-1]
    close = last["Close"]

    is_kr = str(market).upper() == "KR"

    def _price(v):
        """가격류 값을 시장에 맞게 정규화 (KR=정수, US=소수점 2자리)."""
        if v is None or pd.isna(v):
            return None
        return int(round(v)) if is_kr else round(float(v), 2)

    def ret_over(window: int):
        if len(df) <= window:
            return None
        return df["Close"].iloc[-1] / df["Close"].iloc[-1 - window] - 1

    last_year = df.tail(252)
    high_52w = last_year["High"].max()
    low_52w = last_year["Low"].min()

    def ma_pos(ma_val):
        if pd.isna(ma_val):
            return "데이터부족"
        return "위" if close > ma_val else "아래"

    rsi_val = last["RSI14"]
    if pd.isna(rsi_val):
        rsi_label = "데이터부족"
    elif rsi_val >= 70:
        rsi_label = "과매수"
    elif rsi_val <= 30:
        rsi_label = "과매도"
    else:
        rsi_label = "중립"

    return {
        "as_of": last.name.strftime("%Y-%m-%d"),
        "market": "KR" if is_kr else "US",
        "close": _price(close),
        "high_52w": _price(high_52w),
        "low_52w": _price(low_52w),
        "ma20": _price(last["MA20"]),
        "ma60": _price(last["MA60"]),
        "ma120": _price(last["MA120"]),
        "ma20_pos": ma_pos(last["MA20"]),
        "ma60_pos": ma_pos(last["MA60"]),
        "ma120_pos": ma_pos(last["MA120"]),
        "ret_1m": ret_over(20),
        "ret_3m": ret_over(60),
        "ret_1y": ret_over(252),
        "vol_20d_ann": None if pd.isna(last["vol_20d_ann"]) else float(last["vol_20d_ann"]),
        "rsi14": None if pd.isna(rsi_val) else float(rsi_val),
        "rsi14_label": rsi_label,
    }
