"""
백테스팅 공통 유틸리티.

다른 모듈에서도 재사용 가능한 순수 계산 함수 모음.
외부 의존: yfinance, pandas, numpy
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf


def fetch_prices(
    tickers: list[str],
    start: str,
    end: str,
) -> tuple[pd.DataFrame, list[str]]:
    """
    yfinance로 종가(auto-adjust) 일별 데이터를 수집한다.

    Parameters
    ----------
    tickers : Yahoo Finance 티커 목록  (예: ["SPY", "005930.KS", "BTC-USD"])
    start   : "YYYY-MM-DD"
    end     : "YYYY-MM-DD"

    Returns
    -------
    prices : DataFrame  columns = 티커, index = 날짜
    errors : 조회 실패한 티커 목록
    """
    frames: dict[str, pd.Series] = {}
    errors: list[str] = []

    for ticker in tickers:
        try:
            raw = yf.download(
                ticker,
                start=start,
                end=end,
                auto_adjust=True,
                progress=False,
                multi_level_index=False,
            )
            if raw.empty:
                errors.append(f"{ticker}: 해당 기간 데이터 없음")
                continue
            close = raw["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            close.name = ticker
            frames[ticker] = close
        except Exception as e:
            errors.append(f"{ticker}: {e}")

    if not frames:
        return pd.DataFrame(), errors

    prices = pd.DataFrame(frames).dropna(how="all")
    prices = prices.ffill().bfill()
    return prices, errors


def calc_mdd_from_returns(returns: pd.Series) -> float:
    """일별 수익률 시리즈에서 최대낙폭(MDD)을 계산한다. 반환값은 음수(예: -0.25)."""
    if returns.empty:
        return 0.0
    cum = (1.0 + returns).cumprod()
    rolling_max = cum.cummax()
    return float((cum / rolling_max - 1.0).min())


def calc_sharpe_from_returns(
    returns: pd.Series, risk_free_rate: float = 0.03
) -> float:
    """일별 수익률 시리즈에서 연환산 샤프지수를 계산한다."""
    if returns.empty or len(returns) < 2:
        return 0.0
    daily_rf = (1.0 + risk_free_rate) ** (1.0 / 252) - 1.0
    excess = returns - daily_rf
    std = float(returns.std())
    if std == 0:
        return 0.0
    return float(excess.mean() / std * np.sqrt(252))


def calc_annual_vol_from_returns(returns: pd.Series) -> float:
    """일별 수익률 시리즈에서 연환산 변동성(표준편차)을 계산한다."""
    if returns.empty or len(returns) < 2:
        return 0.0
    return float(returns.std() * np.sqrt(252))
