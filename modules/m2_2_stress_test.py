"""
M-2-2 · VaR 리스크 분석 (m2_2_stress_test)

포트폴리오의 역사적 VaR(Value at Risk)와 CVaR(Conditional VaR)를 계산한다.
방법론: 역사적 시뮬레이션 (Historical Simulation)
데이터: yfinance (국내 종목 코드 → 자동으로 .KS 접미사 추가)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

MODULE_ID = "m2_2_stress_test"
MODULE_META = {
    "title": "VaR 리스크 분석",
    "step": 2,
    "icon": "🎯",
    "default_visible": True,
    "description": "포트폴리오 최대 예상 손실(VaR·CVaR) 계산",
}

_PERIOD_DAYS = {"1일": 1, "1주": 5, "1개월": 21}
_DATA_PERIOD = {"1년": "1y", "2년": "2y", "3년": "3y"}
_CACHE_KEY = "m2_2_var_cache"


# ════════════════════════════════════════════════════════════════════
# 유틸리티
# ════════════════════════════════════════════════════════════════════

def _to_yf_ticker(code: str) -> str:
    """한국 종목코드(6자리 숫자) → yfinance 티커. 이미 .KS/.KQ 등이 붙어있으면 그대로."""
    code = code.strip()
    if not code:
        return ""
    if "." in code:
        return code
    if code.isdigit() and len(code) == 6:
        return f"{code}.KS"
    return code


def _fetch_prices(tickers: list[str], period: str) -> pd.DataFrame:
    """yfinance Ticker.history()로 종목별 종가 수집. 실패한 종목은 조용히 건너뜀."""
    result: dict[str, pd.Series] = {}
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period=period, auto_adjust=True)
            if not hist.empty and "Close" in hist.columns:
                # timezone 제거 (pd.concat 오류 방지)
                close = hist["Close"]
                if hasattr(close.index, "tz") and close.index.tz is not None:
                    close.index = close.index.tz_localize(None)
                result[t] = close
        except Exception:
            pass
    if not result:
        return pd.DataFrame()
    return pd.DataFrame(result).dropna(how="all")


def _calc_var(returns: pd.Series, confidence: int) -> tuple[float, float]:
    """1일 역사적 VaR, CVaR 반환. 둘 다 음수 (손실 방향)."""
    pct = 100 - confidence
    var = float(np.percentile(returns, pct))
    mask = returns <= var
    cvar = float(returns[mask].mean()) if mask.any() else var
    return var, cvar


def _fetch_kospi_var(period: str, confidence: int) -> tuple[float, float]:
    """KOSPI(^KS11) VaR·CVaR 계산. 실패 시 (None, None) 반환."""
    try:
        hist = yf.Ticker("^KS11").history(period=period, auto_adjust=True)
        if hist.empty or len(hist) < 20:
            return None, None
        rets = hist["Close"].pct_change().dropna()
        return _calc_var(rets, confidence)
    except Exception:
        return None, None


def _portfolio_returns(prices: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """포트폴리오 일별 수익률 = Σ(종목 수익률 × 비중)."""
    rets = prices.pct_change().dropna()
    common = [t for t in weights if t in rets.columns]
    if not common:
        return pd.Series(dtype=float)
    w = np.array([weights[t] for t in common])
    w = w / w.sum()
    return (rets[common] * w).sum(axis=1)


# ════════════════════════════════════════════════════════════════════
# 렌더 헬퍼
# ════════════════════════════════════════════════════════════════════

def _red_card(col, label: str, value: str, note: str = "") -> None:
    sub = (
        f"<div style='font-size:11px;color:#9ca3af;margin-top:3px'>{note}</div>"
        if note else ""
    )
    col.markdown(
        f"""<div style='background:#fff5f5;border:1px solid #fecaca;border-radius:8px;
        padding:16px;text-align:center;min-height:80px'>
        <div style='font-size:11px;color:#6b7280;letter-spacing:0.3px'>{label}</div>
        <div style='font-size:26px;font-weight:700;color:#dc2626;margin-top:6px'>{value}</div>
        {sub}</div>""",
        unsafe_allow_html=True,
    )


def _comparison_html(
    port_rets: pd.Series,
    sel_conf: int,
    sel_period: str,
    total_value: int,
    data_period: str,
) -> str:
    """6가지 파라미터 조합 비교표 HTML (선택 행 파란 배경)."""
    kospi_cache = {}
    for conf in [95, 99]:
        kv, kc = _fetch_kospi_var(data_period, conf)
        kospi_cache[conf] = (kv, kc)

    rows_html = ""
    for conf in [95, 99]:
        var1, cvar1 = _calc_var(port_rets, conf)
        for period in ["1일", "1주", "1개월"]:
            n = _PERIOD_DAYS[period]
            var_n = var1 * np.sqrt(n)
            cvar_n = cvar1 * np.sqrt(n)
            amount = int(abs(var_n) * total_value) if total_value > 0 else 0
            selected = (conf == sel_conf and period == sel_period)
            bg = "#dbeafe" if selected else "white"
            fw = "font-weight:700;" if selected else ""
            amount_str = f"{amount:,}원" if total_value > 0 else "-"

            kv_n, kc_n = None, None
            if kospi_cache[conf][0] is not None:
                kv_n = kospi_cache[conf][0] * np.sqrt(n)
                kc_n = kospi_cache[conf][1] * np.sqrt(n)

            kospi_str = f"{abs(kv_n)*100:.2f}%" if kv_n is not None else "-"

            if kv_n is not None:
                color = "#dc2626" if abs(var_n) > abs(kv_n) else "#16a34a"
            else:
                color = "#dc2626"

            rows_html += (
                f"<tr style='background:{bg};{fw}'>"
                f"<td style='padding:7px 14px;text-align:center'>{conf}%</td>"
                f"<td style='padding:7px 14px;text-align:center'>{period}</td>"
                f"<td style='padding:7px 14px;text-align:center;color:{color}'>"
                f"{abs(var_n) * 100:.2f}%</td>"
                f"<td style='padding:7px 14px;text-align:center;color:#6b7280'>{kospi_str}</td>"
                f"<td style='padding:7px 14px;text-align:center;color:#dc2626'>"
                f"{abs(cvar_n) * 100:.2f}%</td>"
                f"<td style='padding:7px 14px;text-align:right'>{amount_str}</td>"
                f"</tr>"
            )
    th = "padding:7px 14px;border-bottom:2px solid #dee2e6;font-size:12px"
    return (
        "<div style='overflow-x:auto'>"
        "<table style='width:100%;border-collapse:collapse;font-size:13px'>"
        "<thead><tr style='background:#f8f9fa'>"
        f"<th style='{th};text-align:center'>신뢰수준</th>"
        f"<th style='{th};text-align:center'>보유기간</th>"
        f"<th style='{th};text-align:center'>내 포트 VaR(%)</th>"
        f"<th style='{th};text-align:center'>KOSPI VaR(%)</th>"
        f"<th style='{th};text-align:center'>CVaR(%)</th>"
        f"<th style='{th};text-align:right'>금액(원)</th>"
        f"</tr></thead><tbody>{rows_html}</tbody></table></div>"
    )


def _histogram(port_rets: pd.Series) -> go.Figure:
    """수익률 분포 히스토그램 + 95%/99% VaR 선."""
    var_95, _ = _calc_var(port_rets, 95)
    var_99, _ = _calc_var(port_rets, 99)
    x = port_rets.values * 100

    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=x, nbinsx=60, name="일별 수익률",
        marker_color="#93c5fd", opacity=0.85,
    ))
    x_tail = x[x <= var_99 * 100]
    if len(x_tail) > 0:
        fig.add_trace(go.Histogram(
            x=x_tail, nbinsx=20, name="극단 손실 구간 (99% VaR 이하)",
            marker_color="#ef4444", opacity=0.75,
        ))
    fig.add_vline(
        x=var_95 * 100, line_dash="dash", line_color="#f97316", line_width=2,
        annotation_text=f"95% VaR {abs(var_95)*100:.2f}%",
        annotation_position="top right", annotation_font_color="#f97316",
    )
    fig.add_vline(
        x=var_99 * 100, line_dash="dash", line_color="#dc2626", line_width=2,
        annotation_text=f"99% VaR {abs(var_99)*100:.2f}%",
        annotation_position="bottom right", annotation_font_color="#dc2626",
    )
    fig.update_layout(
        height=310, bargap=0.04, barmode="overlay",
        margin=dict(l=0, r=0, t=36, b=0),
        xaxis_title="일별 수익률 (%)", yaxis_title="빈도 (거래일)",
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        font=dict(size=12),
    )
    return fig


def _contribution_html(
    prices: pd.DataFrame,
    weights: dict[str, float],
    confidence: int,
    names: dict[str, str],
) -> str:
    """종목별 VaR 기여도 테이블 HTML."""
    rets = prices.pct_change().dropna()
    common = [t for t in weights if t in rets.columns]
    if not common:
        return ""

    total_w = sum(weights[t] for t in common) or 1.0
    rows_data = []
    for t in common:
        w = weights[t] / total_w
        var_i, _ = _calc_var(rets[t], confidence)
        rows_data.append({
            "name": names.get(t, t),
            "weight_pct": round(w * 100, 1),
            "var_pct": round(abs(var_i) * 100, 2),
            "contrib_raw": abs(w * var_i),
        })

    total_contrib = sum(r["contrib_raw"] for r in rows_data) or 1.0
    max_raw = max(r["contrib_raw"] for r in rows_data)

    th = "padding:7px 14px;border-bottom:2px solid #dee2e6;font-size:12px"
    rows_html = ""
    for r in rows_data:
        contrib_pct = round(r["contrib_raw"] / total_contrib * 100, 1)
        warn = " ⚠️" if r["contrib_raw"] == max_raw else ""
        rows_html += (
            "<tr>"
            f"<td style='padding:6px 14px'>{r['name']}{warn}</td>"
            f"<td style='padding:6px 14px;text-align:center'>{r['weight_pct']:.1f}%</td>"
            f"<td style='padding:6px 14px;text-align:center;color:#dc2626'>{r['var_pct']:.2f}%</td>"
            f"<td style='padding:6px 14px;text-align:center'>{contrib_pct:.1f}%</td>"
            "</tr>"
        )
    return (
        "<div style='overflow-x:auto'>"
        "<table style='width:100%;border-collapse:collapse;font-size:13px'>"
        "<thead><tr style='background:#f8f9fa'>"
        f"<th style='{th};text-align:left'>종목명</th>"
        f"<th style='{th};text-align:center'>비중(%)</th>"
        f"<th style='{th};text-align:center'>개별 VaR(%)</th>"
        f"<th style='{th};text-align:center'>기여도(%)</th>"
        f"</tr></thead><tbody>{rows_html}</tbody></table></div>"
    )


# ════════════════════════════════════════════════════════════════════
# render (단일 진입점)
# ════════════════════════════════════════════════════════════════════

def render(state) -> None:
    st.subheader("🎯 VaR 리스크 분석", divider="gray")

    # ── 1. 파라미터 설정 UI (항상 표시) ─────────────────────────────
    with st.container(border=True):
        st.markdown("**⚙️ 분석 파라미터**")
        col1, col2, col3 = st.columns(3)

        with col1:
            conf_label = st.radio(
                "신뢰수준", ["95%", "99%"], horizontal=True, key="var_conf"
            )
            if conf_label == "95%":
                st.caption("하루 손실이 이 수치를 초과할 확률 5%")
            else:
                st.caption("하루 손실이 이 수치를 초과할 확률 1% (더 보수적)")

        with col2:
            period_label = st.radio(
                "보유기간", ["1일", "1주", "1개월"], horizontal=True, key="var_period"
            )
            st.caption("기간이 길수록 VaR 수치가 커짐 (√기간 비례)")

        with col3:
            data_period_label = st.radio(
                "과거 데이터", ["1년", "2년", "3년"],
                horizontal=True, index=1, key="var_data_period",
            )
            st.caption("길수록 위기 구간 포함 확률 높아짐. 2년 권장")

    confidence = int(conf_label.replace("%", ""))
    n_days = _PERIOD_DAYS[period_label]
    data_period = _DATA_PERIOD[data_period_label]

    # ── 2. 분석 대상 선택 ────────────────────────────────────────────
    kis_ok = state.kis_status.get("connected", False)
    options = ["① 현재 포트폴리오 (KIS 실잔고)", "② 종목 직접 입력"]

    target = st.radio(
        "분석 대상", options,
        index=0 if kis_ok else 1,
        key="var_target",
        horizontal=True,
    )

    # KIS 미연결인데 ① 선택 → 자동으로 ② 전환
    if target == options[0] and not kis_ok:
        st.warning(
            "KIS가 연결되어 있지 않습니다. **종목 직접 입력** 방식으로 전환합니다.  "
            "(.env에 KIS_APP_KEY / KIS_APP_SECRET / KIS_ACCOUNT_NO를 입력하면 "
            "실잔고를 불러올 수 있습니다.)"
        )
        target = options[1]

    # 분석 대상 파싱
    tickers: list[str] = []
    raw_weights: dict[str, float] = {}
    names: dict[str, str] = {}
    total_value: int = 0

    if target == options[0]:
        # KIS 실잔고 사용
        holdings = state.holdings
        if not holdings:
            st.info(
                "보유 종목이 없습니다. 사이드바에서 **잔고 새로고침**을 누르거나 "
                "종목을 직접 입력하세요."
            )
            return
        total_value = state.total_value
        for h in holdings:
            t = _to_yf_ticker(h.get("code", ""))
            if not t:
                continue
            val = h.get("value") or (h.get("price", 0) * h.get("qty", 1))
            tickers.append(t)
            raw_weights[t] = float(val)
            names[t] = h.get("name", t)
        tw = sum(raw_weights.values())
        if tw > 0:
            raw_weights = {t: v / tw for t, v in raw_weights.items()}

    else:
        # 종목 직접 입력
        text_input = st.text_area(
            "종목코드 및 비중 입력",
            placeholder="종목코드, 비중%\n005930, 40\n000660, 30\n035420, 30",
            height=120,
            key="var_manual_input",
        )
        if text_input.strip():
            for line in text_input.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 2:
                    continue
                try:
                    w = float(parts[1])
                except ValueError:
                    continue
                code = parts[0].strip()
                t = _to_yf_ticker(code)
                if not t or w <= 0:
                    continue
                tickers.append(t)
                raw_weights[t] = w
                names[t] = code  # 원래 입력 코드를 이름으로 보관
            tw = sum(raw_weights.values())
            if tw > 0:
                raw_weights = {t: v / tw for t, v in raw_weights.items()}

    run_btn = st.button("🎯 VaR 계산", type="primary", key="var_run_btn")

    # ── 3. 계산 ──────────────────────────────────────────────────────
    if run_btn:
        if not tickers or not raw_weights:
            st.error("분석할 종목이 없습니다. 종목코드와 비중을 입력한 후 다시 시도하세요.")
        else:
            with st.spinner(f"과거 {data_period_label} 가격 데이터 수집 중…"):
                prices = _fetch_prices(tickers, data_period)

            if prices.empty:
                st.error(
                    "가격 데이터를 가져오지 못했습니다. "
                    "종목코드(국내: 6자리 숫자, 예 005930 → 005930.KS) 또는 "
                    "네트워크를 확인하세요."
                )
            else:
                valid = [t for t in tickers if t in prices.columns]
                missing = [t for t in tickers if t not in prices.columns]
                if missing:
                    st.warning(f"데이터를 가져오지 못한 종목: {', '.join(missing)}")
                if not valid:
                    st.error("유효한 종목 데이터가 없습니다.")
                else:
                    fw = {t: raw_weights[t] for t in valid}
                    tw2 = sum(fw.values())
                    if tw2 > 0:
                        fw = {t: v / tw2 for t, v in fw.items()}

                    port_rets = _portfolio_returns(prices[valid], fw)
                    if len(port_rets) < 20:
                        st.error(
                            f"수익률 계산에 충분한 데이터가 없습니다 ({len(port_rets)}일). "
                            "데이터 기간을 늘리거나 종목코드를 확인하세요."
                        )
                    else:
                        st.session_state[_CACHE_KEY] = {
                            "port_rets": port_rets,
                            "prices": prices[valid],
                            "weights": fw,
                            "names": names,
                            "total_value": total_value,
                            "data_period_label": data_period_label,
                            "n_days_used": len(port_rets),
                        }

    # ── 4. 결과 표시 ─────────────────────────────────────────────────
    if _CACHE_KEY not in st.session_state:
        st.info(
            "파라미터와 분석 대상을 설정한 후 **🎯 VaR 계산** 버튼을 누르세요.  "
            "yfinance로 과거 수익률을 수집해 VaR·CVaR를 계산합니다.",
            icon="ℹ️",
        )
        return

    cached = st.session_state[_CACHE_KEY]
    port_rets: pd.Series = cached["port_rets"]
    prices_c: pd.DataFrame = cached["prices"]
    fw: dict[str, float] = cached["weights"]
    names_c: dict[str, str] = cached["names"]
    tv: int = cached["total_value"]

    # 데이터 기간이 바뀌었을 때 안내
    if cached["data_period_label"] != data_period_label:
        st.warning(
            f"현재 선택한 과거 데이터 기간({data_period_label})이 "
            f"마지막 계산({cached['data_period_label']})과 다릅니다. "
            "🎯 VaR 계산을 다시 실행하면 새 데이터로 업데이트됩니다."
        )

    # 현재 UI 파라미터로 VaR/CVaR 계산 (실시간)
    var_1d, cvar_1d = _calc_var(port_rets, confidence)
    var_nd = var_1d * np.sqrt(n_days)
    cvar_nd = cvar_1d * np.sqrt(n_days)
    var_amount = int(abs(var_nd) * tv) if tv > 0 else 0

    # ── [핵심 지표] ───────────────────────────────────────────────────
    st.markdown("#### 📊 핵심 지표")
    c1, c2, c3 = st.columns(3)
    _red_card(c1, f"VaR ({conf_label} · {period_label})", f"{abs(var_nd) * 100:.2f}%")
    _red_card(c2, f"CVaR ({conf_label} · {period_label})", f"{abs(cvar_nd) * 100:.2f}%")
    if tv > 0:
        _red_card(c3, "금액 환산", f"{var_amount:,}원", f"총 {tv:,}원 기준")
    else:
        _red_card(c3, "금액 환산", "-", "총 평가액 없음 (KIS 미연결)")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 자동 해석 문장 ─────────────────────────────────────────────
    if tv > 0:
        interp = (
            f"**{conf_label} 신뢰수준**에서 {period_label} 최대 손실은 "
            f"**{abs(var_nd)*100:.2f}%** ({var_amount:,}원)이며, "
            f"최악의 상황에서는 평균 **{abs(cvar_nd)*100:.2f}%** 손실이 예상됩니다."
        )
    else:
        interp = (
            f"**{conf_label} 신뢰수준**에서 {period_label} 최대 손실은 "
            f"**{abs(var_nd)*100:.2f}%**이며, "
            f"최악의 상황에서는 평균 **{abs(cvar_nd)*100:.2f}%** 손실이 예상됩니다."
        )
    st.info(interp, icon="💡")

    # ── [파라미터 변화 비교표] ────────────────────────────────────────
    st.markdown("#### 📋 파라미터 변화 비교표")
    st.caption("현재 선택한 조합은 파란 배경으로 표시됩니다.")
    st.markdown(
        _comparison_html(port_rets, confidence, period_label, tv, data_period),
        unsafe_allow_html=True,
    )
    st.markdown("<br>", unsafe_allow_html=True)

    # ── [수익률 분포 히스토그램] ──────────────────────────────────────
    st.markdown("#### 📈 수익률 분포 히스토그램")
    st.caption("주황 점선: 95% VaR  /  빨간 점선: 99% VaR  /  빨간 막대: 극단 손실 구간")
    st.plotly_chart(_histogram(port_rets), use_container_width=True)

    # ── [종목별 VaR 기여도] ───────────────────────────────────────────
    st.markdown(f"#### 🔍 종목별 VaR 기여도 ({conf_label} 기준)")
    st.caption("기여도(%) = 종목 개별 VaR × 비중의 상대 비율 / ⚠️ 가장 높은 기여 종목")
    contrib = _contribution_html(prices_c, fw, confidence, names_c)
    if contrib:
        st.markdown(contrib, unsafe_allow_html=True)
    else:
        st.warning("종목별 기여도를 계산할 수 없습니다.")

    st.divider()
    st.caption(
        f"데이터: {cached['data_period_label']} ({cached['n_days_used']}거래일)  ·  "
        "방법론: 역사적 시뮬레이션 (Historical Simulation)  ·  "
        "N일 VaR = 1일 VaR × √N  ·  소스: Yahoo Finance (yfinance)"
    )
