"""
M-2-3 · 대체자산 편입 신호 (m2_3_alt_signal)

편입 기준 (스펙 docs/module_spec.md):
  리츠ETF  : 배당수익률 스프레드 ≥ 1.5%p (10년물 국채 대비)
  금ETF    : 실질금리 ≤ 0% AND DXY 3개월 수익률 ≤ -3%
  BTC      : 현재가 ≥ 200일 이동평균
  인프라ETF: 배당수익률 스프레드 ≥ 1.5%p (10년물 국채 대비, 리츠와 동일 로직)

데이터 소스:
  yfinance  — BTC-USD, GLD, VNQ, IGF
  FRED API  — 실질금리(DFII10), 10년물(DGS10), 달러지수(DTWEXBGS)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

MODULE_ID = "m2_3_alt_signal"
MODULE_META = {
    "title": "대체자산 편입 신호",
    "step": 2,
    "icon": "🌐",
    "default_visible": True,
    "description": "금·BTC·리츠·인프라 편입 트리거 자동 체크 (FRED + yfinance)",
}

# ── 기준값 ────────────────────────────────────────────────────────────
REIT_SPREAD_MIN   = 1.5   # 배당수익률 - 10Y 국채 ≥ 1.5%p
INFRA_SPREAD_MIN  = 1.5
REAL_RATE_MAX     = 0.0   # 실질금리 ≤ 0%
DXY_CHANGE_MAX    = -3.0  # DXY 3개월 수익률 ≤ -3%
BTC_MA_DAYS       = 200

# ── FRED 시리즈 ID ────────────────────────────────────────────────────
FRED_REAL_RATE = "DFII10"    # 10년 물가연동국채 실질금리
FRED_10Y       = "DGS10"     # 10년물 명목금리
FRED_2Y        = "DGS2"      # 2년물 명목금리
FRED_10Y2Y     = "T10Y2Y"    # 장단기 금리차 (10Y-2Y)
FRED_DXY       = "DTWEXBGS"  # 달러지수 (Broad)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


# ════════════════════════════════════════════════════════════════════
# 데이터 수집
# ════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=1800, show_spinner=False)
def _fred_latest(series_id: str, api_key: str) -> float | None:
    """FRED에서 최신 관측값 1개를 반환."""
    try:
        resp = requests.get(
            FRED_BASE,
            params={
                "series_id":       series_id,
                "api_key":         api_key,
                "file_type":       "json",
                "sort_order":      "desc",
                "limit":           5,
                "observation_end": datetime.today().strftime("%Y-%m-%d"),
            },
            timeout=10,
        )
        resp.raise_for_status()
        obs = resp.json().get("observations", [])
        for o in obs:
            val = o.get("value", ".")
            if val != ".":
                return float(val)
    except Exception:
        pass
    return None


@st.cache_data(ttl=1800, show_spinner=False)
def _fred_series(series_id: str, api_key: str, days: int = 100) -> pd.Series | None:
    """FRED에서 최근 n일 시계열 반환 (DatetimeIndex)."""
    try:
        start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
        resp = requests.get(
            FRED_BASE,
            params={
                "series_id":        series_id,
                "api_key":          api_key,
                "file_type":        "json",
                "observation_start": start,
                "sort_order":       "asc",
            },
            timeout=10,
        )
        resp.raise_for_status()
        obs = resp.json().get("observations", [])
        records = {}
        for o in obs:
            if o["value"] != ".":
                records[pd.to_datetime(o["date"])] = float(o["value"])
        if not records:
            return None
        return pd.Series(records)
    except Exception:
        return None


@st.cache_data(ttl=1800, show_spinner=False)
def _yf_ticker_info(ticker: str) -> dict:
    """yfinance Ticker.info 반환 (실패 시 빈 dict)."""
    try:
        return yf.Ticker(ticker).info
    except Exception:
        return {}


@st.cache_data(ttl=1800, show_spinner=False)
def _btc_with_ma(ma_days: int = 200) -> tuple[float | None, float | None]:
    """BTC 현재가와 200일 이동평균 반환."""
    try:
        hist = yf.Ticker("BTC-USD").history(period=f"{ma_days + 30}d")
        if hist.empty:
            return None, None
        price = float(hist["Close"].iloc[-1])
        ma    = float(hist["Close"].rolling(ma_days).mean().iloc[-1])
        return price, ma
    except Exception:
        return None, None


@st.cache_data(ttl=1800, show_spinner=False)
def _dxy_3m_change(api_key: str) -> float | None:
    """DXY 3개월(약 65거래일) 변화율(%) 반환."""
    s = _fred_series(FRED_DXY, api_key, days=100)
    if s is None or len(s) < 2:
        return None
    # 약 65 거래일 = 3개월
    idx_start = max(0, len(s) - 65)
    val_now   = s.iloc[-1]
    val_3m    = s.iloc[idx_start]
    if val_3m == 0:
        return None
    return round((val_now - val_3m) / val_3m * 100, 2)


def fetch_signals(fred_key: str) -> dict:
    """실제 데이터를 수집해 신호 dict 반환."""
    errors: list[str] = []

    # ── FRED 공통 지표 ───────────────────────────────────────────────
    real_rate  = _fred_latest(FRED_REAL_RATE, fred_key)
    rate_10y   = _fred_latest(FRED_10Y, fred_key)
    rate_2y    = _fred_latest(FRED_2Y, fred_key)
    spread_10y2y = _fred_latest(FRED_10Y2Y, fred_key)
    dxy_3m     = _dxy_3m_change(fred_key)

    # T10Y2Y가 없으면 직접 계산
    if spread_10y2y is None and rate_10y is not None and rate_2y is not None:
        spread_10y2y = round(rate_10y - rate_2y, 2)

    if real_rate is None:
        errors.append("FRED 실질금리(DFII10) 조회 실패")
    if rate_10y is None:
        errors.append("FRED 10년물(DGS10) 조회 실패")
    if dxy_3m is None:
        errors.append("FRED 달러지수(DTWEXBGS) 조회 실패")

    # ── VNQ (리츠) ───────────────────────────────────────────────────
    vnq_info  = _yf_ticker_info("VNQ")
    vnq_price = vnq_info.get("currentPrice") or vnq_info.get("regularMarketPrice")
    vnq_yield = (vnq_info.get("dividendYield") or 0.0) * 100  # % 단위로 변환
    vnq_spread = round(vnq_yield - (rate_10y or 0.0), 2) if rate_10y is not None else None

    # ── IGF (인프라) ─────────────────────────────────────────────────
    igf_info  = _yf_ticker_info("IGF")
    igf_price = igf_info.get("currentPrice") or igf_info.get("regularMarketPrice")
    igf_yield = (igf_info.get("dividendYield") or 0.0) * 100
    igf_spread = round(igf_yield - (rate_10y or 0.0), 2) if rate_10y is not None else None

    # ── BTC ──────────────────────────────────────────────────────────
    btc_price, btc_ma = _btc_with_ma(BTC_MA_DAYS)
    if btc_price is None:
        errors.append("yfinance BTC-USD 조회 실패")

    # ── 신호 판정 ────────────────────────────────────────────────────
    assets: dict[str, dict] = {
        "리츠ETF (VNQ)": {
            "현재가": round(vnq_price, 2) if vnq_price else None,
            "배당수익률(%)": round(vnq_yield, 2),
            "스프레드(vs 10Y, %p)": vnq_spread,
            "기준값(스프레드 ≥ %p)": REIT_SPREAD_MIN,
            "충족": (vnq_spread is not None and vnq_spread >= REIT_SPREAD_MIN),
            "icon": "🏢",
        },
        "인프라ETF (IGF)": {
            "현재가": round(igf_price, 2) if igf_price else None,
            "배당수익률(%)": round(igf_yield, 2),
            "스프레드(vs 10Y, %p)": igf_spread,
            "기준값(스프레드 ≥ %p)": INFRA_SPREAD_MIN,
            "충족": (igf_spread is not None and igf_spread >= INFRA_SPREAD_MIN),
            "icon": "🏗️",
        },
        "금ETF (GLD)": {
            "현재가": None,  # GLD 가격은 판정에 불필요, 참고용 생략
            "실질금리(%)": real_rate,
            "DXY_3M(%)": dxy_3m,
            "기준값": f"실질금리 ≤ {REAL_RATE_MAX}% AND DXY 3개월 ≤ {DXY_CHANGE_MAX}%",
            "충족": (
                real_rate is not None and dxy_3m is not None
                and real_rate <= REAL_RATE_MAX
                and dxy_3m <= DXY_CHANGE_MAX
            ),
            "icon": "🥇",
        },
        "BTC (BTC-USD)": {
            "현재가": round(btc_price) if btc_price else None,
            f"200일MA": round(btc_ma) if btc_ma else None,
            "현재가/MA(%)": round(btc_price / btc_ma * 100, 1) if (btc_price and btc_ma) else None,
            "기준값": f"현재가 ≥ {BTC_MA_DAYS}일 이동평균",
            "충족": bool(btc_price and btc_ma and btc_price >= btc_ma),
            "icon": "₿",
        },
    }

    return {
        "10Y_국채금리":  round(rate_10y, 2) if rate_10y is not None else None,
        "2Y_국채금리":   round(rate_2y, 2) if rate_2y is not None else None,
        "장단기금리차":  round(spread_10y2y, 2) if spread_10y2y is not None else None,
        "실질금리":      round(real_rate, 2) if real_rate is not None else None,
        "DXY_3M변화율": dxy_3m,
        "assets":       assets,
        "갱신시각":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        "errors":       errors,
    }


# ════════════════════════════════════════════════════════════════════
# 렌더링
# ════════════════════════════════════════════════════════════════════

def _badge(충족: bool, unknown: bool = False) -> str:
    if unknown:
        return "<span style='background:#555;color:#fff;padding:2px 8px;border-radius:4px;font-size:13px'>⚠ 데이터 없음</span>"
    if 충족:
        return "<span style='background:#1D9E75;color:#fff;padding:2px 8px;border-radius:4px;font-size:13px'>✓ 편입 유지</span>"
    return "<span style='background:#C0392B;color:#fff;padding:2px 8px;border-radius:4px;font-size:13px'>✗ 편입 불가</span>"


def _fmt(val, suffix="", none_str="—") -> str:
    if val is None:
        return none_str
    return f"{val:,.2f}{suffix}" if isinstance(val, float) else f"{val:,}{suffix}"


def render(state) -> None:
    fred_key = os.environ.get("FRED_API_KEY", "")
    has_key  = bool(fred_key)

    st.subheader("🌐 대체자산 편입 신호", divider="gray")

    # ── 데이터 로드 ──────────────────────────────────────────────────
    if not has_key:
        st.warning(
            "**FRED API 키 없음** — 설정 탭에서 `FRED_API_KEY`를 저장하면 "
            "리츠·금·BTC·인프라 편입 신호가 실제 시장 데이터로 계산됩니다.",
            icon="⚠️",
        )
        return

    with st.spinner("시장 데이터 수집 중…"):
        data = fetch_signals(fred_key)

    if data.get("errors"):
        for e in data["errors"]:
            st.warning(e, icon="⚠️")

    # ── 새로고침 버튼 ────────────────────────────────────────────────
    col_info, col_btn = st.columns([6, 1])
    with col_info:
        st.caption(f"갱신: {data.get('갱신시각', '—')}")
    with col_btn:
        if st.button("🔄 새로고침", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # ── 공통 거시지표 ────────────────────────────────────────────────
    st.markdown("#### 거시 환경")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "미국 10년물 국채",
        f"{_fmt(data.get('10Y_국채금리'))}%",
        delta=f"2Y {_fmt(data.get('2Y_국채금리'))}%" if data.get("2Y_국채금리") else None,
        delta_color="off",
    )
    spread_val = data.get("장단기금리차")
    m2.metric(
        "장단기 금리차 (10Y-2Y)",
        f"{_fmt(spread_val)}%p" if spread_val is not None else "—",
        delta="역전" if spread_val is not None and spread_val < 0 else (
            "정상" if spread_val is not None else None
        ),
        delta_color="inverse" if spread_val is not None and spread_val < 0 else "normal",
    )
    real = data.get("실질금리")
    m3.metric(
        "실질금리 (TIPS 10Y)",
        f"{_fmt(real)}%",
        delta="기준 초과" if real is not None and real > REAL_RATE_MAX else (
            "기준 충족" if real is not None else None
        ),
        delta_color="inverse" if real is not None and real > REAL_RATE_MAX else "normal",
    )
    dxy = data.get("DXY_3M변화율")
    m4.metric(
        "달러지수 3개월 변화",
        f"{_fmt(dxy)}%",
        delta="기준 초과" if dxy is not None and dxy > DXY_CHANGE_MAX else (
            "기준 충족" if dxy is not None else None
        ),
        delta_color="inverse" if dxy is not None and dxy > DXY_CHANGE_MAX else "normal",
    )

    st.divider()
    st.markdown("#### 자산별 편입 판정")

    assets: dict = data.get("assets", {})

    for name, info in assets.items():
        충족 = info.get("충족", False)
        unknown = info.get("현재가") is None and name not in ("금ETF (GLD)",)

        with st.container(border=True):
            hc1, hc2 = st.columns([5, 2])
            with hc1:
                st.markdown(f"**{info['icon']} {name}**")
            with hc2:
                st.markdown(_badge(충족, unknown=unknown), unsafe_allow_html=True)

            # ── 리츠 / 인프라 ───────────────────────────────────────
            if "스프레드(vs 10Y, %p)" in info:
                spread  = info.get("스프레드(vs 10Y, %p)")
                div_yld = info.get("배당수익률(%)")
                thresh  = info.get("기준값(스프레드 ≥ %p)", REIT_SPREAD_MIN)
                price   = info.get("현재가")

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("현재가 (USD)", _fmt(price, "$") if price else "—")
                c2.metric("배당수익률", f"{_fmt(div_yld)}%")
                c3.metric(
                    "스프레드 (vs 10Y)",
                    f"{_fmt(spread)}%p" if spread is not None else "—",
                    delta=f"기준 {thresh:+.1f}%p" if spread is not None else None,
                    delta_color="normal" if spread is not None and spread >= thresh else "inverse",
                )
                c4.metric("편입 기준", f"≥ {thresh}%p")

                if spread is not None:
                    gap = spread - thresh
                    if gap >= 0:
                        st.success(f"스프레드 {spread:.2f}%p — 기준 대비 **+{gap:.2f}%p** 상회")
                    else:
                        st.error(f"스프레드 {spread:.2f}%p — 기준 대비 **{gap:.2f}%p** 미달")

            # ── 금 ──────────────────────────────────────────────────
            elif "실질금리(%)" in info:
                r     = info.get("실질금리(%)")
                dxy_v = info.get("DXY_3M(%)")
                crit  = info.get("기준값", "")

                c1, c2, c3 = st.columns(3)
                c1.metric(
                    "실질금리",
                    f"{_fmt(r)}%" if r is not None else "—",
                    delta=f"기준 ≤ {REAL_RATE_MAX}%",
                    delta_color="normal" if r is not None and r <= REAL_RATE_MAX else "inverse",
                )
                c2.metric(
                    "DXY 3개월 변화",
                    f"{_fmt(dxy_v)}%" if dxy_v is not None else "—",
                    delta=f"기준 ≤ {DXY_CHANGE_MAX}%",
                    delta_color="normal" if dxy_v is not None and dxy_v <= DXY_CHANGE_MAX else "inverse",
                )
                c3.metric("편입 기준", "AND 조건 모두")

                r_ok   = r is not None and r <= REAL_RATE_MAX
                dxy_ok = dxy_v is not None and dxy_v <= DXY_CHANGE_MAX

                status_lines = [
                    f"{'✅' if r_ok else '❌'} 실질금리 {_fmt(r)}% {'≤' if r_ok else '>'} {REAL_RATE_MAX}%",
                    f"{'✅' if dxy_ok else '❌'} DXY 3개월 {_fmt(dxy_v)}% {'≤' if dxy_ok else '>'} {DXY_CHANGE_MAX}%",
                ]
                if r_ok and dxy_ok:
                    st.success("  \n".join(status_lines))
                else:
                    st.error("  \n".join(status_lines))

            # ── BTC ─────────────────────────────────────────────────
            elif "현재가/MA(%)" in info or f"{BTC_MA_DAYS}일MA" in info:
                price  = info.get("현재가")
                ma     = info.get(f"{BTC_MA_DAYS}일MA")
                pct    = info.get("현재가/MA(%)")

                c1, c2, c3 = st.columns(3)
                c1.metric("BTC 현재가", f"${_fmt(price)}" if price else "—")
                c2.metric(
                    f"{BTC_MA_DAYS}일 이동평균",
                    f"${_fmt(ma)}" if ma else "—",
                )
                c3.metric(
                    "현재가 / MA",
                    f"{pct}%" if pct else "—",
                    delta=f"{'상회' if 충족 else '하회'} (기준: 100%)",
                    delta_color="normal" if 충족 else "inverse",
                )

                if price and ma:
                    diff = price - ma
                    if 충족:
                        st.success(f"현재가 ${price:,.0f} ≥ 200일MA ${ma:,.0f}  (+${diff:,.0f})")
                    else:
                        st.error(f"현재가 ${price:,.0f} < 200일MA ${ma:,.0f}  (${diff:,.0f})")

    st.divider()
    st.caption(
        "편입 기준 — "
        f"리츠·인프라: 배당수익률 스프레드 ≥ {REIT_SPREAD_MIN}%p  ·  "
        f"금: 실질금리 ≤ {REAL_RATE_MAX}% AND DXY 3M ≤ {DXY_CHANGE_MAX}%  ·  "
        f"BTC: 현재가 ≥ {BTC_MA_DAYS}일 이동평균"
    )
