from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from core.backtest_utils import (
    calc_annual_vol_from_returns,
    calc_mdd_from_returns,
    calc_sharpe_from_returns,
    fetch_prices,
)

MODULE_ID = "m1_5_nps_backtest"
MODULE_META = {
    "title": "국민연금 공시 수익률 검증",
    "step": 1,
    "icon": "📐",
    "default_visible": True,
    "description": "공시 종목 수익률 vs KOSPI 비교 — 신호 유효성 검증",
}

_KOSPI = "^KS11"
_PRESET_DAYS: dict[str, int] = {"3개월": 91, "6개월": 182, "1년": 365, "2년": 730}


# ── 유틸 ──────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _lookup_name(ticker: str) -> str:
    """yfinance로 종목명 조회. 실패 시 빈 문자열 반환."""
    try:
        info = yf.Ticker(ticker).info
        return info.get("longName") or info.get("shortName") or ""
    except Exception:
        return ""


@st.cache_data(ttl=300, show_spinner=False)
def _cached_fetch(ticker: str, start: str, end: str) -> tuple[pd.DataFrame, list[str]]:
    return fetch_prices([ticker, _KOSPI], start, end)


def _normalize_ticker(raw: str) -> str:
    """005930 → 005930.KS (6자리 숫자를 KOSPI 티커로 변환)."""
    raw = raw.strip()
    if not raw:
        return ""
    upper = raw.upper()
    if upper.endswith((".KS", ".KQ")):
        return upper
    if raw.isdigit() and len(raw) == 6:
        return f"{raw}.KS"
    return upper


def _color(val: float) -> str:
    return "#22c55e" if val >= 0 else "#ef4444"


def _card_html(label: str, value: str, color: str = "#e2e8f0") -> str:
    return (
        f'<div style="background:#1e293b;border-radius:8px;padding:12px 16px;'
        f'text-align:center;min-height:76px;display:flex;flex-direction:column;'
        f'justify-content:center">'
        f'<div style="color:#94a3b8;font-size:11px;margin-bottom:6px">{label}</div>'
        f'<div style="color:{color};font-size:20px;font-weight:700">{value}</div>'
        f'</div>'
    )


# ── on_change 콜백 ────────────────────────────────────────────────────────────

def _on_preset_change() -> None:
    """프리셋 선택 시 종료일 = 시작일 + 선택 기간으로 자동 계산."""
    preset = st.session_state.get("m1_5_preset", "직접 입력")
    if preset == "직접 입력":
        return
    delta = _PRESET_DAYS[preset]
    start = st.session_state.get("m1_5_start", date.today() - timedelta(days=365))
    new_end = start + timedelta(days=delta)
    st.session_state["m1_5_end"] = min(new_end, date.today())


def _on_cand_select() -> None:
    """공시 종목 selectbox 선택 시 티커 입력창에 자동 입력."""
    sel = st.session_state.get("m1_5_cand_sel", "")
    if sel and sel != "— 직접 입력 —":
        st.session_state["m1_5_ticker_raw"] = sel


# ── 메인 렌더 ─────────────────────────────────────────────────────────────────

def render(state) -> None:
    st.markdown(
        '<div class="inv-card"><div class="inv-card-title">📐 국민연금 공시 수익률 검증</div>',
        unsafe_allow_html=True,
    )

    today = date.today()

    # 날짜 세션 상태 초기화 (최초 1회)
    if "m1_5_start" not in st.session_state:
        st.session_state["m1_5_start"] = today - timedelta(days=365)
    if "m1_5_end" not in st.session_state:
        st.session_state["m1_5_end"] = today

    # ── 입력 섹션 ─────────────────────────────────────────────────────────
    with st.container(border=True):

        # 행 1 — 티커 입력 + 공시 종목 선택
        nps_cands = st.session_state.get("nps_candidates", [])
        col_l, col_r = st.columns([1, 2])

        with col_l:
            ticker_raw = st.text_input(
                "티커 (예: 005930)",
                placeholder="005930",
                key="m1_5_ticker_raw",
            )

        if nps_cands:
            with col_r:
                st.selectbox(
                    "국민연금 공시 종목에서 선택",
                    options=["— 직접 입력 —"] + list(nps_cands),
                    key="m1_5_cand_sel",
                    on_change=_on_cand_select,
                )

        # 종목명 실시간 조회
        yf_ticker = _normalize_ticker(ticker_raw)
        if yf_ticker:
            name = _lookup_name(yf_ticker)
            if name:
                st.markdown(
                    f'<p style="color:#60a5fa;font-size:13px;margin:0 0 8px 0">📌 {name}</p>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<p style="color:#f87171;font-size:12px;margin:0 0 8px 0">'
                    f'⚠️ 종목 정보를 찾을 수 없습니다 ({yf_ticker})</p>',
                    unsafe_allow_html=True,
                )

        # 행 2 — 기간 입력
        col_s, col_e, col_p = st.columns(3)
        with col_s:
            start_date = st.date_input("시작일", key="m1_5_start", max_value=today)
        with col_e:
            end_date = st.date_input("종료일", key="m1_5_end", max_value=today)
        with col_p:
            st.selectbox(
                "프리셋",
                ["직접 입력", "3개월", "6개월", "1년", "2년"],
                key="m1_5_preset",
                on_change=_on_preset_change,
            )

        # 날짜 유효성 즉시 검증
        date_valid = True
        if start_date >= end_date:
            st.warning("⚠️ 시작일이 종료일 이후입니다. 날짜를 다시 설정하세요.")
            date_valid = False

        run_btn = st.button(
            "📐 분석 실행",
            type="primary",
            key="m1_5_run",
            disabled=not (ticker_raw.strip() and date_valid),
        )

    # ── 분석 실행 ─────────────────────────────────────────────────────────
    if not run_btn:
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if not yf_ticker:
        st.error("티커를 입력하세요.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    with st.spinner("데이터 수집 중…"):
        prices, errors = _cached_fetch(yf_ticker, str(start_date), str(end_date))

    for e in errors:
        st.warning(e)

    if prices.empty:
        st.error("해당 기간 데이터 없음 — 기간이나 티커를 확인하세요.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if yf_ticker not in prices.columns:
        st.error(f"'{yf_ticker}' 데이터를 불러오지 못했습니다. 티커를 확인하세요.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if len(prices) < 5:
        st.error(f"최소 5거래일 이상 필요합니다 (현재 {len(prices)}일).")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    has_kospi = _KOSPI in prices.columns

    # ── 수익률 계산 ────────────────────────────────────────────────────────
    stock_p = prices[yf_ticker]
    stock_r = stock_p.pct_change().dropna()
    stock_cum = (1 + stock_r).cumprod() - 1

    s_ret = float((stock_p.iloc[-1] / stock_p.iloc[0]) - 1) * 100
    s_mdd = float(calc_mdd_from_returns(stock_r)) * 100
    s_vol = float(calc_annual_vol_from_returns(stock_r)) * 100
    s_sharpe = float(calc_sharpe_from_returns(stock_r))

    if has_kospi:
        kospi_p = prices[_KOSPI]
        kospi_r = kospi_p.pct_change().dropna()
        kospi_cum = (1 + kospi_r).cumprod() - 1
        k_ret = float((kospi_p.iloc[-1] / kospi_p.iloc[0]) - 1) * 100
        k_mdd = float(calc_mdd_from_returns(kospi_r)) * 100
        k_vol = float(calc_annual_vol_from_returns(kospi_r)) * 100
        k_sharpe = float(calc_sharpe_from_returns(kospi_r))
        excess = s_ret - k_ret
    else:
        k_ret = k_mdd = k_vol = k_sharpe = excess = None

    # ── [1] 핵심 지표 카드 ────────────────────────────────────────────────
    st.markdown("#### 핵심 지표")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            _card_html("수익률", f"{s_ret:+.2f}%", _color(s_ret)),
            unsafe_allow_html=True,
        )
    with c2:
        if k_ret is not None:
            st.markdown(
                _card_html("KOSPI 수익률", f"{k_ret:+.2f}%", _color(k_ret)),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(_card_html("KOSPI 수익률", "데이터 없음"), unsafe_allow_html=True)
    with c3:
        if excess is not None:
            st.markdown(
                _card_html("초과수익률", f"{excess:+.2f}%p", _color(excess)),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(_card_html("초과수익률", "—"), unsafe_allow_html=True)
    with c4:
        st.markdown(
            _card_html("MDD", f"{s_mdd:.2f}%", _color(s_mdd)),
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ── [2] 누적수익률 차트 ───────────────────────────────────────────────
    st.markdown("#### 누적 수익률 차트")
    fig = go.Figure()

    stock_label = _lookup_name(yf_ticker) or yf_ticker
    fig.add_trace(go.Scatter(
        x=stock_cum.index,
        y=(stock_cum * 100).values,
        name=stock_label,
        line=dict(color="#3b82f6", width=2),
        mode="lines",
    ))

    if has_kospi:
        fig.add_trace(go.Scatter(
            x=kospi_cum.index,
            y=(kospi_cum * 100).values,
            name="KOSPI",
            line=dict(color="#9ca3af", width=1.5, dash="dot"),
            mode="lines",
        ))

    # y=0 기준선
    fig.add_hline(y=0, line_width=1, line_dash="dot", line_color="#475569")

    # 공시일 수직 점선
    fig.add_vline(
        x=str(start_date),
        line_width=1.5,
        line_dash="dash",
        line_color="#f59e0b",
        annotation_text="공시일",
        annotation_position="top right",
        annotation_font_size=11,
        annotation_font_color="#f59e0b",
    )

    fig.update_layout(
        plot_bgcolor="#0f172a",
        paper_bgcolor="#0f172a",
        font=dict(color="#e2e8f0"),
        xaxis=dict(title="날짜", gridcolor="#1e293b", showgrid=True),
        yaxis=dict(title="누적수익률 (%)", gridcolor="#1e293b", showgrid=True),
        legend=dict(bgcolor="#1e293b", bordercolor="#334155", borderwidth=1),
        height=380,
        margin=dict(l=40, r=20, t=40, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── [3] 상세 비교 테이블 ─────────────────────────────────────────────
    st.markdown("#### 상세 비교")

    def _fmt_ret(v: float) -> str:
        return f"{v:+.2f}%"

    def _fmt_excess_ret(v: float) -> str:
        return f"{v:+.2f}%p"

    def _fmt_excess_num(v: float) -> str:
        return f"{v:+.2f}"

    rows = [
        {
            "지표": "수익률",
            "해당 종목": _fmt_ret(s_ret),
            "KOSPI": _fmt_ret(k_ret) if k_ret is not None else "—",
            "초과": _fmt_excess_ret(s_ret - k_ret) if k_ret is not None else "—",
        },
        {
            "지표": "MDD",
            "해당 종목": f"{s_mdd:.2f}%",
            "KOSPI": f"{k_mdd:.2f}%" if k_mdd is not None else "—",
            "초과": _fmt_excess_ret(s_mdd - k_mdd) if k_mdd is not None else "—",
        },
        {
            "지표": "연환산 변동성",
            "해당 종목": f"{s_vol:.2f}%",
            "KOSPI": f"{k_vol:.2f}%" if k_vol is not None else "—",
            "초과": _fmt_excess_ret(s_vol - k_vol) if k_vol is not None else "—",
        },
        {
            "지표": "샤프지수",
            "해당 종목": f"{s_sharpe:.2f}",
            "KOSPI": f"{k_sharpe:.2f}" if k_sharpe is not None else "—",
            "초과": _fmt_excess_num(s_sharpe - k_sharpe) if k_sharpe is not None else "—",
        },
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── [4] 자동 판정 코멘트 ─────────────────────────────────────────────
    if excess is not None:
        if excess > 10:
            msg = f"✅ KOSPI 대비 {excess:.2f}%p 초과 — 공시 신호 유효"
            bg, fg = "#14532d", "#86efac"
        elif excess >= 0:
            msg = "🔶 소폭 초과 — 추가 확인 필요"
            bg, fg = "#78350f", "#fde68a"
        else:
            msg = f"⚠️ KOSPI 대비 {abs(excess):.2f}%p 하회 — 신호 유효성 낮음"
            bg, fg = "#450a0a", "#fca5a5"

        st.markdown(
            f'<div style="background:{bg};color:{fg};padding:14px 18px;'
            f'border-radius:8px;font-size:14px;font-weight:600;margin-top:8px">'
            f'{msg}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)
