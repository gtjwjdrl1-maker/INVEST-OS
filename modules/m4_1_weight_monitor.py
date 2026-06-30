"""
M-4-1 · 비중 모니터링 대시보드
현재 배분 vs 목표 배분 비교 · 항목별 ±5%p 이탈 시 경고
2026-06-22 확장: 전략별(코어/위성) 차트 + 개별 보유종목 테이블 추가
데이터 소스: M-3-3(KIS 포트폴리오 조회 유틸리티) → core/state.py
"""
from __future__ import annotations
import os
import time
import streamlit as st

MODULE_ID = "m4_1_weight_monitor"
MODULE_META = {
    "title": "비중 모니터링",
    "step": 4,
    "icon": "⚖️",
    "default_visible": True,
    "description": "목표 배분 이탈 시 리밸런싱 알림 + 보유종목 현황",
}

THRESHOLD = 5  # ±5%p 이탈 임계값

# 전략 분류: 자산군 기준 자동 (주식·채권·현금=코어, 대체자산=위성)
_CORE_ASSETS = {"주식", "채권", "현금"}
_STRATEGY_COLORS = {"코어": "#185FA5", "위성": "#1D9E75"}


def _strategy_of(asset_class: str) -> str:
    """자산군명을 코어/위성 전략으로 분류."""
    return "코어" if asset_class in _CORE_ASSETS else "위성"


def _send_kakao(message: str) -> bool:
    """카카오톡 알림 발송 (API 키 있을 때만)."""
    kakao_key = os.environ.get("KAKAO_API_KEY", "")
    if not kakao_key:
        return False
    try:
        import requests
        resp = requests.post(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            headers={"Authorization": f"Bearer {kakao_key}"},
            data={"template_object": f'{{"object_type":"text","text":"{message}","link":{{}}}}'},
            timeout=5,
        )
        return resp.status_code == 200
    except Exception:
        return False


def render(state) -> None:
    alloc: dict = state.allocation          # {"자산명": {"pct": int, "color": str}}
    target: dict = state.allocation_target  # {"자산명": int}

    # ── 이탈 계산 ────────────────────────────────────────────────────
    deviations = []
    for name, info in alloc.items():
        tgt = target.get(name, 0)
        diff = info["pct"] - tgt
        deviations.append({
            "name": name,
            "current": info["pct"],
            "target": tgt,
            "diff": diff,
            "color": info["color"],
            "alert": abs(diff) >= THRESHOLD,
        })

    alerts = [d for d in deviations if d["alert"]]

    # ── 상단 경고 배너 ────────────────────────────────────────────────
    if alerts:
        for a in alerts:
            direction = "초과" if a["diff"] > 0 else "부족"
            kakao_icon = ""
            kakao_key = os.environ.get("KAKAO_API_KEY", "")
            if kakao_key:
                kakao_icon = " · 카카오톡 알림 발송됨"
            st.markdown(f"""
            <div class="notify-bar-amber">
              ⚠️ <b>{a['name']}</b> 목표 {a['target']}% 대비
              <b>{abs(a['diff'])}%p {direction}</b> (현재 {a['current']}%){kakao_icon}
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="notify-bar">✅ 모든 자산군이 목표 비중 ±5%p 이내에 있습니다.</div>',
            unsafe_allow_html=True,
        )

    # ── 전략별(코어/위성) 비중 집계 ──────────────────────────────────
    strategy_pct: dict[str, int] = {"코어": 0, "위성": 0}
    for d in deviations:
        strategy_pct[_strategy_of(d["name"])] += d["current"]

    col_chart, col_strategy = st.columns([1, 1])

    # ── 파이차트 (자산군별) ───────────────────────────────────────────
    with col_chart:
        try:
            import plotly.graph_objects as go

            labels = [d["name"] for d in deviations]
            values = [d["current"] for d in deviations]
            colors = [d["color"] for d in deviations]

            fig = go.Figure(data=[go.Pie(
                labels=labels,
                values=values,
                marker_colors=colors,
                hole=0.45,
                textinfo="label+percent",
                textfont_size=12,
                hovertemplate="<b>%{label}</b><br>현재: %{value}%<extra></extra>",
            )])
            fig.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                showlegend=False,
                height=240,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                annotations=[dict(
                    text="현재<br>배분",
                    x=0.5, y=0.5,
                    font_size=12,
                    showarrow=False,
                    font_color="#6b7280",
                )],
            )
            st.markdown('<div class="inv-card"><div class="inv-card-title">🥧 현재 자산배분</div>', unsafe_allow_html=True)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            st.markdown("</div>", unsafe_allow_html=True)
        except ImportError:
            st.markdown(
                '<div class="inv-card"><div class="inv-card-title">🥧 현재 자산배분</div>'
                '<div style="font-size:12px;color:#9ca3af">plotly 패키지가 필요합니다: <code>pip install plotly</code></div>'
                "</div>",
                unsafe_allow_html=True,
            )

    # ── 전략별(코어/위성) 바차트 ─────────────────────────────────────
    with col_strategy:
        try:
            import plotly.graph_objects as go

            s_names = ["코어", "위성"]
            s_vals = [strategy_pct[s] for s in s_names]
            fig_s = go.Figure(data=[go.Bar(
                x=s_vals,
                y=s_names,
                orientation="h",
                marker_color=[_STRATEGY_COLORS[s] for s in s_names],
                text=[f"{v}%" for v in s_vals],
                textposition="auto",
                textfont_size=13,
                hovertemplate="<b>%{y}</b><br>%{x}%<extra></extra>",
            )])
            fig_s.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                height=240,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(range=[0, 100], ticksuffix="%", showgrid=True, gridcolor="#f3f4f6"),
                yaxis=dict(autorange="reversed"),
                showlegend=False,
            )
            st.markdown('<div class="inv-card"><div class="inv-card-title">🛰️ 전략별 비중 (코어/위성)</div>', unsafe_allow_html=True)
            st.plotly_chart(fig_s, use_container_width=True, config={"displayModeBar": False})
            st.markdown(
                f'<div style="font-size:10px;color:#9ca3af;margin-top:-6px">코어=주식·채권·현금 / 위성=대체자산 · 합계 {sum(s_vals)}%</div>'
                "</div>",
                unsafe_allow_html=True,
            )
        except ImportError:
            st.markdown(
                '<div class="inv-card"><div class="inv-card-title">🛰️ 전략별 비중 (코어/위성)</div>'
                f'<div style="font-size:12px">코어 {strategy_pct["코어"]}% · 위성 {strategy_pct["위성"]}%</div>'
                "</div>",
                unsafe_allow_html=True,
            )

    # ── 목표 vs 현재 상세 테이블 (자산군 항목별 ±5% 판정) ─────────────
    with st.container():
        rows_html = ""
        for d in deviations:
            diff_color = "#E24B4A" if d["diff"] < -THRESHOLD else ("#1D9E75" if d["diff"] > THRESHOLD else "#6b7280")
            sign = "+" if d["diff"] >= 0 else ""
            alert_badge = f'<span class="tag tag-red">⚠ 이탈</span>' if d["alert"] else '<span class="tag tag-green">정상</span>'

            # 필요 거래 금액 추산 (총 평가액 기준)
            total_val = getattr(state, "total_value", 0)
            needed = int(abs(d["diff"]) / 100 * total_val)
            trade_str = f'{"매수" if d["diff"] < 0 else "매도"} ~{needed:,}원' if d["alert"] and total_val else ""

            rows_html += f"""
            <div class="stock-row">
              <div>
                <div class="stock-name" style="color:{d['color']}">{d['name']}</div>
                <div class="stock-meta">{trade_str}</div>
              </div>
              <div style="text-align:right">
                <div style="font-size:13px;font-weight:600">{d['current']}%
                  <span style="font-size:11px;color:{diff_color}">({sign}{d['diff']}%p)</span>
                </div>
                <div style="font-size:11px;color:#9ca3af">목표 {d['target']}%&nbsp;{alert_badge}</div>
              </div>
            </div>"""

        st.markdown(f"""
        <div class="inv-card">
          <div class="inv-card-title">📋 목표 vs 현재 비교 <span style="margin-left:auto;font-size:10px;color:#9ca3af">임계값 ±{THRESHOLD}%p</span></div>
          {rows_html}
        </div>""", unsafe_allow_html=True)

    # ── 개별 보유종목 테이블 (M-3-3 KIS 보유종목 데이터) ─────────────
    holdings = getattr(state, "holdings", []) or []
    src = getattr(state, "kis_status", {}).get("source", "demo")
    src_badge = '<span class="tag tag-green">KIS 실잔고</span>' if src == "live" else '<span class="tag tag-gray">KIS 미연결</span>'

    if holdings:
        hd_rows = ""
        for h in holdings:
            qty = h.get("qty", 0)
            value = h.get("value") or int(h.get("price", 0) * qty)
            pnl = h.get("chg", 0.0)  # 매입가 대비 손익률(%)
            pnl_color = "#1D9E75" if pnl >= 0 else "#E24B4A"
            pnl_sign = "+" if pnl >= 0 else ""
            asset = h.get("type", "")
            strat = _strategy_of(asset) if asset in (_CORE_ASSETS | {"대체자산"}) else ""
            strat_tag = f'<span class="tag {"tag-blue" if strat == "코어" else "tag-green"}">{strat}</span>' if strat else ""
            hd_rows += f"""
            <div class="stock-row">
              <div>
                <div class="stock-name">{h.get('name','')}</div>
                <div class="stock-meta">{h.get('code','')} · {asset} {strat_tag}</div>
              </div>
              <div style="text-align:right">
                <div style="font-size:13px;font-weight:600">{value:,}원
                  <span style="font-size:11px;color:{pnl_color}">({pnl_sign}{pnl:.2f}%)</span>
                </div>
                <div style="font-size:11px;color:#9ca3af">{qty:,}주</div>
              </div>
            </div>"""
        st.markdown(f"""
        <div class="inv-card">
          <div class="inv-card-title">📦 개별 보유종목 <span style="margin-left:auto">{src_badge}</span></div>
          {hd_rows}
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="inv-card"><div class="inv-card-title">📦 개별 보유종목</div>'
            '<div style="font-size:12px;color:#9ca3af">보유종목이 없습니다. 설정 탭에서 KIS를 연결하세요.</div>'
            "</div>",
            unsafe_allow_html=True,
        )

    # ── 자동 새로고침 컨트롤 ─────────────────────────────────────────
    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        auto_refresh = st.toggle("30초 자동 새로고침", key="m4_1_auto_refresh", value=False)
    with col_info:
        if auto_refresh:
            last_ts = st.session_state.get("m4_1_last_refresh", 0)
            elapsed = int(time.time() - last_ts)
            remaining = max(0, 30 - elapsed)
            st.markdown(
                f'<div style="font-size:11px;color:#6b7280;padding-top:6px">⏱ {remaining}초 후 갱신</div>',
                unsafe_allow_html=True,
            )
            if elapsed >= 30:
                st.session_state["m4_1_last_refresh"] = time.time()
                time.sleep(0.1)
                st.rerun()
        else:
            if st.button("🔄 수동 새로고침", key="m4_1_manual_refresh"):
                st.rerun()

    # 카카오 알림 (경고 있을 때 자동 발송 시도 — 세션 중 1회)
    if alerts and not st.session_state.get("m4_1_kakao_sent"):
        msg = " / ".join(
            f"{a['name']} {a['current']}%(목표{a['target']}%)"
            for a in alerts
        )
        sent = _send_kakao(f"[InvestOS] 리밸런싱 필요: {msg}")
        st.session_state["m4_1_kakao_sent"] = True
        if sent:
            st.toast("카카오톡 알림을 발송했습니다.", icon="📲")
