"""
백테스팅 공통 유틸리티.

다른 모듈에서도 재사용 가능한 순수 계산 함수 모음.
외부 의존: yfinance, pandas, numpy, requests
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# ── 시나리오 정의 ─────────────────────────────────────────────────────
# m2_2 제거로 미사용 — VaR 교체 후 정리 예정
SCENARIOS: dict[str, dict] = {
    "2008 금융위기": {
        "start": "2007-10-01",
        "end":   "2009-03-31",
        "desc":  "서브프라임 모기지 위기 · 리먼브러더스 파산",
        "color": "#E24B4A",
    },
    "2020 코로나": {
        "start": "2020-01-01",
        "end":   "2020-12-31",
        "desc":  "코로나19 팬데믹 · 역사적 급락 후 V자 반등",
        "color": "#EF9F27",
    },
    "2022 인플레 쇼크": {
        "start": "2022-01-01",
        "end":   "2022-12-31",
        "desc":  "연준 급격한 금리인상 · 주식·채권 동반 하락",
        "color": "#185FA5",
    },
}

# ── 참고용 기본 티커 매핑 ────────────────────────────────────────────
# m2_2 제거로 미사용 — VaR 교체 후 정리 예정
DEFAULT_TICKERS: dict[str, str] = {
    "주식":     "SPY",
    "채권":     "IEF",
    "대체자산": "VNQ",
    "현금":     "BIL",
}

# ── 리스크 레벨 기준 (MDD 기반) ──────────────────────────────────────
# m2_2 제거로 미사용 — VaR 교체 후 정리 예정
_RISK_THRESHOLDS = [
    (-0.05,  1, "매우 낮음", "#1D9E75"),
    (-0.15,  2, "낮음",     "#69B578"),
    (-0.25,  3, "보통",     "#EF9F27"),
    (-0.35,  4, "높음",     "#E07B3A"),
    (-1.00,  5, "매우 높음","#E24B4A"),
]


# m2_2 제거로 미사용 — VaR 교체 후 정리 예정
def calc_risk_level(mdd: float) -> tuple[int, str, str]:
    """MDD → (레벨 1~5, 레이블, 색상)."""
    for threshold, level, label, color in _RISK_THRESHOLDS:
        if mdd > threshold:
            return level, label, color
    return 5, "매우 높음", "#E24B4A"


# m2_2 제거로 미사용 — VaR 교체 후 정리 예정
def search_ticker(query: str) -> list[dict]:
    """
    종목명·키워드로 Yahoo Finance 티커를 검색한다.

    Returns
    -------
    list of {"이름", "티커", "종류", "거래소"}
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(
            "https://query2.finance.yahoo.com/v1/finance/search",
            params={
                "q":           query,
                "lang":        "ko-KR",
                "region":      "KR",
                "quotesCount": 10,
                "newsCount":   0,
                "listsCount":  0,
            },
            headers=headers,
            timeout=8,
        )
        resp.raise_for_status()
        quotes = resp.json().get("quotes", [])
        results = []
        for q in quotes:
            sym  = q.get("symbol", "")
            if not sym:
                continue
            name = q.get("longname") or q.get("shortname") or sym
            qt   = q.get("quoteType", "")
            exch = q.get("exchDisp") or q.get("exchange", "")
            results.append({"이름": name, "티커": sym, "종류": qt, "거래소": exch})
        return results
    except Exception:
        return []


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


# m2_2 제거로 미사용 — VaR 교체 후 정리 예정
def run_backtest(
    prices: pd.DataFrame,
    weights: dict[str, float],
    risk_free_rate: float = 0.03,
) -> dict:
    """
    매월 말 리밸런싱을 가정한 백테스팅.

    Parameters
    ----------
    prices          : fetch_prices() 반환 DataFrame (columns = 티커)
    weights         : {티커: 비중}  합산이 100이 아니어도 자동 정규화
    risk_free_rate  : 연간 무위험수익률 (예: 0.03 = 3%)

    Returns
    -------
    dict with:
      cumulative_returns : pd.Series  (시작=1.0 기준)
      portfolio_returns  : pd.Series  일별 수익률
      annual_return      : float
      total_return       : float
      mdd                : float  (음수)
      sharpe             : float
      risk_level         : tuple (level, label, color)
      n_days             : int
    """
    cols = [c for c in weights if c in prices.columns and weights[c] > 0]
    if not cols:
        raise ValueError("weights와 prices에 겹치는 자산이 없습니다.")

    prices = prices[cols].copy()
    w = pd.Series({c: float(weights[c]) for c in cols})
    w = w / w.sum()

    rets = prices.pct_change().fillna(0.0)
    month_end_dates: set = set(rets.resample("ME").last().index)

    current_w = w.copy()
    portfolio_daily: list[float] = []

    for date, row in rets.iterrows():
        port_ret = float((current_w * row).sum())
        portfolio_daily.append(port_ret)

        new_w = current_w * (1.0 + row)
        total = new_w.sum()
        current_w = new_w / total if total > 0 else w.copy()

        if date in month_end_dates:
            current_w = w.copy()

    port_rets = pd.Series(portfolio_daily, index=rets.index)
    cum_rets  = (1.0 + port_rets).cumprod()

    n_days     = len(port_rets)
    total_ret  = float(cum_rets.iloc[-1]) - 1.0
    annual_ret = (1.0 + total_ret) ** (252.0 / n_days) - 1.0 if n_days > 0 else 0.0

    rolling_max = cum_rets.cummax()
    mdd         = float((cum_rets / rolling_max - 1.0).min())

    daily_rf = (1.0 + risk_free_rate) ** (1.0 / 252) - 1.0
    excess   = port_rets - daily_rf
    std      = float(port_rets.std())
    sharpe   = float(excess.mean() / std * np.sqrt(252)) if std > 0 else 0.0

    return {
        "cumulative_returns": cum_rets,
        "portfolio_returns":  port_rets,
        "annual_return":      annual_ret,
        "total_return":       total_ret,
        "mdd":                mdd,
        "sharpe":             sharpe,
        "risk_level":         calc_risk_level(mdd),
        "n_days":             n_days,
    }


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


# m2_2 제거로 미사용 — VaR 교체 후 정리 예정
def run_scenario_backtest(
    scenario_key: str,
    tickers: list[str],
    weights: dict[str, float],
    risk_free_rate: float = 0.03,
) -> tuple[dict | None, list[str]]:
    """
    단일 시나리오에 대한 전체 파이프라인 실행.

    Returns (result_dict | None, error_list)
    """
    sc = SCENARIOS[scenario_key]
    prices, errors = fetch_prices(tickers, sc["start"], sc["end"])
    if prices.empty:
        return None, errors

    try:
        result = run_backtest(prices, weights, risk_free_rate)
        result["scenario"] = scenario_key
        result["start"]    = sc["start"]
        result["end"]      = sc["end"]
        result["color"]    = sc["color"]
        return result, errors
    except Exception as e:
        errors.append(str(e))
        return None, errors
