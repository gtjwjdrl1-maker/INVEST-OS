"""
InvestOS — AI 투자 운용 시스템
메인 셸: 사이드바 네비게이션 + 모듈 토글 + 레이아웃
"""
import os
import streamlit as st
from dotenv import load_dotenv, set_key, dotenv_values
from pathlib import Path
from core.state import get_state, get_module_visibility, set_module_visibility, refresh_portfolio, init_widget_defaults
from core import module_registry

load_dotenv(override=True)

# Streamlit Community Cloud 배포 대응:
# 로컬 .env가 없는 클라우드 환경에서는 대시보드에 등록한 st.secrets 값을
# os.environ에 주입해 기존 os.getenv(...) 기반 코드가 그대로 동작하게 한다.
try:
    for _k, _v in st.secrets.items():
        os.environ.setdefault(_k, str(_v))
except Exception:
    pass  # secrets.toml이 없는 로컬 환경에서는 조용히 무시

ENV_PATH = Path(__file__).parent / ".env"
if not ENV_PATH.exists():
    try:
        ENV_PATH.touch()
    except Exception:
        pass  # 클라우드의 읽기 전용 파일시스템 등에서는 무시

# API 키 목록: (표시명, .env 키이름, session_state 키)
API_KEYS = [
    ("Anthropic (Claude)",  "ANTHROPIC_API_KEY", "api_anthropic"),
    ("Google (Gemini)",     "GEMINI_API_KEY",     "api_gemini"),
    ("DART OpenAPI",        "DART_API_KEY",        "api_dart"),
    ("FRED API",            "FRED_API_KEY",        "api_fred"),
    ("카카오 REST API",     "KAKAO_API_KEY",       "api_kakao"),
    ("KIS (한국투자증권)",  "KIS_APP_KEY",         "api_kis"),
]

# session_state에 .env 값 초기화 (최초 1회)
if "api_keys_loaded" not in st.session_state:
    env_vals = dotenv_values(ENV_PATH)
    for _, env_key, ss_key in API_KEYS:
        st.session_state[ss_key] = env_vals.get(env_key, "")
    st.session_state["api_keys_loaded"] = True

st.set_page_config(
    page_title="InvestOS",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 공통 CSS (mockup.html 색상·카드 스타일 재현) ─────────────────────
st.markdown("""
<style>
/* 색상 변수 */
:root {
  --blue:   #185FA5;
  --green:  #1D9E75;
  --red:    #E24B4A;
  --amber:  #EF9F27;
  --bg-blue:   #E6F1FB;
  --bg-green:  #EAF3DE;
  --bg-red:    #FCEBEB;
  --bg-amber:  #FAEEDA;
  --border: #e0e0e0;
  --text-sub: #6b7280;
}

/* 카드 */
.inv-card {
  background: white;
  border: 0.5px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 10px;
}
.inv-card-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-sub);
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 헤더 배지 */
.badge-live {
  display: inline-block;
  font-size: 11px;
  padding: 2px 9px;
  border-radius: 99px;
  background: var(--bg-green);
  color: #3B6D11;
  border: 0.5px solid #C0DD97;
  font-weight: 500;
}
.badge-step {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 99px;
  background: var(--bg-blue);
  color: var(--blue);
  margin-right: 8px;
}

/* 알림 바 */
.notify-bar {
  background: var(--bg-blue);
  border: 0.5px solid #B5D4F4;
  border-radius: 8px;
  padding: 8px 14px;
  font-size: 12px;
  color: var(--blue);
  margin-bottom: 10px;
}
.notify-bar-amber {
  background: var(--bg-amber);
  border: 0.5px solid #FAC775;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 12px;
  color: #633806;
  margin-bottom: 10px;
}

/* 태그 배지 */
.tag { display:inline-block; font-size:10px; padding:2px 8px; border-radius:99px; margin-right:4px; font-weight:500; }
.tag-blue  { background:var(--bg-blue);  color:var(--blue); }
.tag-green { background:var(--bg-green); color:#3B6D11; }
.tag-red   { background:var(--bg-red);   color:#A32D2D; }
.tag-amber { background:var(--bg-amber); color:#854F0B; }
.tag-gray  { background:#f3f4f6; color:#6b7280; border:0.5px solid #d1d5db; }

/* 할당 바 */
.alloc-row { display:flex; align-items:center; gap:8px; margin-bottom:7px; }
.alloc-label { width:64px; font-size:12px; color:#374151; }
.alloc-bar-bg { flex:1; height:6px; background:#f3f4f6; border-radius:99px; overflow:hidden; }
.alloc-bar { height:100%; border-radius:99px; }
.alloc-pct { width:32px; text-align:right; font-size:12px; color:var(--text-sub); }

/* 주식 행 */
.stock-row { display:flex; align-items:center; justify-content:space-between; padding:6px 0; border-bottom:0.5px solid #f3f4f6; }
.stock-row:last-child { border-bottom:none; }
.stock-name { font-size:12px; font-weight:600; color:#111827; }
.stock-meta { font-size:11px; color:var(--text-sub); }
.stock-price { text-align:right; font-size:13px; font-weight:500; }

/* 뉴스 */
.news-item { display:flex; gap:10px; padding:7px 0; border-bottom:0.5px solid #f3f4f6; }
.news-item:last-child { border-bottom:none; }
.news-dot { width:6px; height:6px; border-radius:50%; margin-top:5px; flex-shrink:0; }
.news-headline { font-size:12px; color:#111827; margin-bottom:2px; }
.news-meta { font-size:10px; color:#9ca3af; }

/* placeholder 카드 */
.placeholder-card {
  background: white;
  border: 0.5px dashed #d1d5db;
  border-radius: 10px;
  padding: 20px 16px;
  margin-bottom: 10px;
  text-align: center;
}
.placeholder-title { font-size:13px; font-weight:600; color:#374151; margin-bottom:4px; }
.placeholder-desc  { font-size:11px; color:#9ca3af; margin-bottom:10px; }

/* 진행 단계 */
.ps-row { display:flex; align-items:center; gap:8px; margin-bottom:7px; font-size:12px; }
.ps-done    { display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; border-radius:50%; background:var(--bg-green); color:#3B6D11; font-size:10px; font-weight:700; flex-shrink:0; }
.ps-active  { display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; border-radius:50%; background:var(--blue); color:white; font-size:10px; font-weight:700; flex-shrink:0; }
.ps-pending { display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; border-radius:50%; background:#f3f4f6; color:#9ca3af; font-size:10px; border:0.5px solid #d1d5db; flex-shrink:0; }

/* 리스크 미터 */
.risk-meter { display:flex; gap:4px; margin:8px 0; }
.risk-block { flex:1; height:8px; border-radius:2px; }

/* 상단 헤더 고정 느낌 */
.topbar {
  display:flex; align-items:center; justify-content:space-between;
  padding:10px 0 14px 0;
  border-bottom: 0.5px solid #e5e7eb;
  margin-bottom: 16px;
}
.topbar-left { display:flex; align-items:center; gap:14px; }
.logo { font-size:16px; font-weight:700; color:#111827; }
.logo span { color:var(--blue); }
.pf-val { font-size:12px; color:var(--text-sub); }
.pf-val b { color:var(--green); font-weight:600; }

/* Streamlit 기본 여백 조정 */
[data-testid="stVerticalBlock"] { gap: 0.5rem; }
</style>
""", unsafe_allow_html=True)

# ── 세션 상태 초기화 ─────────────────────────────────────────────────
state = get_state()
init_widget_defaults()  # 모든 모듈 위젯 기본값 1회 초기화 (탭 전환 시 리셋 방지)

if "current_page" not in st.session_state:
    st.session_state["current_page"] = "dashboard"

# ── 사이드바 ─────────────────────────────────────────────────────────
PAGES = [
    ("dashboard", "📊", "대시보드"),
    ("step1",     "🔍", "Step 1  사전검토"),
    ("step2",     "🛡️", "Step 2  리스크"),
    ("step3",     "💬", "Step 3  심의위원회"),
    ("step4",     "📈", "Step 4  집행·모니터링"),
    ("settings",  "⚙️", "설정"),
]

# 개발 완료(레지스트리 등록) 모듈 — 사이드바 토글·각 Step 화면에 실제로 렌더링됨
BUILT_MODULES = module_registry.get_all_modules()

# 개발 예정 모듈 — 아직 구현되지 않음. 설정 탭의 '모듈 목록' 상태 표시에만 사용한다.
# (워크플로 화면에는 가짜 '개발 예정' 카드를 더 이상 띄우지 않는다.)
PLANNED_MODULES = [
    {"id": "m4_2_briefing", "step": 4, "title": "자동 브리핑", "icon": "📨", "description": "오전 9시·오후 4시 카카오톡·메일 발송"},
]

with st.sidebar:
    st.markdown('<div style="font-size:15px;font-weight:700;color:#111827;padding:4px 0 12px 0"><span style="color:#185FA5">◆</span> InvestOS</div>', unsafe_allow_html=True)

    # 네비게이션
    for page_id, icon, label in PAGES:
        is_active = st.session_state["current_page"] == page_id
        if st.button(
            f"{icon}  {label}",
            key=f"nav_{page_id}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            st.session_state["current_page"] = page_id
            st.rerun()

    st.divider()

    # 모듈 토글 (개발 완료된 모듈만 표시)
    st.markdown('<div style="font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">모듈 표시 설정</div>', unsafe_allow_html=True)
    vis = get_module_visibility()
    for mod in BUILT_MODULES:
        meta = mod.MODULE_META
        mid = mod.MODULE_ID
        current = vis.get(mid, meta.get("default_visible", True))
        new_val = st.checkbox(
            f"{meta.get('icon','')} {meta.get('title', mid)}",
            value=current,
            key=f"toggle_{mid}",
        )
        if new_val != current:
            set_module_visibility(mid, new_val)


# ── 헬퍼: 등록된 실제 모듈 렌더러 ────────────────────────────────────
def render_registered_modules(step: int):
    """레지스트리에 등록된(개발 완료) 모듈을 토글 상태에 따라 렌더링한다."""
    modules = module_registry.get_modules_for_step(step)
    if not modules:
        st.info("이 단계에 등록된 모듈이 없습니다.", icon="ℹ️")
        return
    vis = get_module_visibility()
    for mod in modules:
        mid = mod.MODULE_ID
        if vis.get(mid, mod.MODULE_META.get("default_visible", True)):
            try:
                mod.render(state)
            except Exception as e:
                st.error(f"[{mid}] 렌더링 오류: {e}")


# ── M-1: 포트폴리오 메인 헤더 (모든 탭 고정) ─────────────────────────
# KIS 연결 상태 배지 (live=실시간 잔고 / demo=미연결)
_kis = getattr(state, "kis_status", {"source": "demo", "message": "KIS API 키 필요"})
_connected = _kis.get("source") == "live"

if _connected:
    kis_badge = '<span class="badge-live">● 실시간</span>'
else:
    kis_badge = (
        '<span style="font-size:11px;padding:2px 9px;border-radius:99px;'
        'background:var(--bg-amber);color:#854F0B;border:0.5px solid #FAC775;font-weight:500">'
        '◌ KIS 미연결</span>'
    )

# 잔고가 있을 때만 실제 수치 표시, 없으면 "—"
if _connected and state.total_value > 0:
    daily_sign = "+" if state.daily_pnl >= 0 else ""
    pf_html = (
        f'총 평가액 <b>{state.total_value:,}원</b>'
        f'<span style="color:{"#1D9E75" if state.daily_pnl >= 0 else "#E24B4A"}">'
        f' {daily_sign}{state.daily_pnl_pct:.2f}%</span>'
    )
else:
    pf_html = '총 평가액 <b style="color:#9ca3af">— (KIS 미연결)</b>'

st.markdown(f"""
<div class="topbar">
  <div class="topbar-left">
    <div class="logo"><span>◆</span> InvestOS</div>
    <div class="pf-val">{pf_html}</div>
  </div>
  <div style="display:flex;gap:6px;align-items:center">
    {kis_badge}
  </div>
</div>
""", unsafe_allow_html=True)

page = st.session_state["current_page"]

# ════════════════════════════════════════════════════════════════════
# 대시보드
# ════════════════════════════════════════════════════════════════════
if page == "dashboard":
    # KIS 잔고 연결 상태 + 새로고침
    _ks = state.kis_status
    connected = _ks.get("source") == "live"
    sc1, sc2 = st.columns([6, 1])
    with sc1:
        if connected:
            st.markdown(f'<div class="notify-bar">📈 KIS 잔고 연결됨 — {_ks.get("message","")} · 실시간 데이터</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="notify-bar-amber">📈 {_ks.get("message","KIS API 키 필요")} — 설정 탭에서 KIS를 연결하면 실제 잔고가 표시됩니다</div>', unsafe_allow_html=True)
    with sc2:
        if st.button("🔄 잔고 새로고침", use_container_width=True):
            refresh_portfolio()
            st.rerun()

    # ── 미연결: 예시 수치 대신 빈 상태 안내 후 종료 ──────────────────
    if not connected or state.total_value <= 0:
        st.markdown(
            '<div class="placeholder-card" style="border-style:solid">'
            '<div class="placeholder-title">포트폴리오 데이터 없음</div>'
            '<div class="placeholder-desc">설정 탭에서 KIS(한국투자증권)를 연결하면 '
            '총 평가액·보유종목·자산배분이 실시간으로 채워집니다.</div>'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        # ── 통계 (KIS 잔고에서 산출) ──────────────────────────────────
        c1, c2, c3 = st.columns(3)
        c1.metric("총 평가액", f"{state.total_value:,}원")
        daily_sign = "+" if state.daily_pnl >= 0 else ""
        c2.metric("평가손익", f"{daily_sign}{state.daily_pnl:,}원",
                  f"{daily_sign}{state.daily_pnl_pct:.2f}%")
        c3.metric("보유종목 수", f"{len(state.holdings)}개")

        col_left, col_right = st.columns(2)

        # 자산배분 카드 (보유종목에서 계산된 값)
        with col_left:
            bars_html = ""
            for name, info in state.allocation.items():
                target = state.allocation_target.get(name, 0)
                diff = info["pct"] - target
                diff_str = f'<span style="color:{"#1D9E75" if diff >= 0 else "#E24B4A"};font-size:10px"> ({diff:+d}%p)</span>' if diff != 0 else ""
                bars_html += f"""
                <div class="alloc-row">
                  <div class="alloc-label">{name}</div>
                  <div class="alloc-bar-bg">
                    <div class="alloc-bar" style="width:{info['pct']}%;background:{info['color']}"></div>
                  </div>
                  <div class="alloc-pct" style="color:{info['color']}">{info['pct']}%{diff_str}</div>
                </div>"""

            alerts = "".join(
                f'<div style="margin-top:8px;padding-top:8px;border-top:0.5px solid #f3f4f6;font-size:11px;color:#9ca3af">⚠ {a["asset"]} 목표({a["target"]}%)보다 {a["target"]-a["current"]}%p 부족</div>'
                for a in state.rebalance_alerts
            )
            st.markdown(f"""
            <div class="inv-card">
              <div class="inv-card-title">📊 자산배분 현황</div>
              {bars_html or '<div style="font-size:11px;color:#9ca3af">자산배분 데이터 없음</div>'}{alerts}
            </div>""", unsafe_allow_html=True)

        # 보유 종목 카드
        with col_right:
            rows_html = ""
            for h in state.holdings:
                chg = h.get("chg", 0.0)
                color = "#1D9E75" if chg >= 0 else "#E24B4A"
                sign  = "+" if chg >= 0 else ""
                rows_html += f"""
                <div class="stock-row">
                  <div>
                    <div class="stock-name">{h.get('name','')}</div>
                    <div class="stock-meta">{h.get('code','')} · {h.get('type','')}</div>
                  </div>
                  <div class="stock-price">
                    <div>{h.get('price',0):,}원</div>
                    <div style="font-size:11px;color:{color}">{sign}{chg:.2f}%</div>
                  </div>
                </div>"""
            st.markdown(f"""
            <div class="inv-card">
              <div class="inv-card-title">📈 보유 종목</div>
              {rows_html or '<div style="font-size:11px;color:#9ca3af">보유 종목 없음</div>'}
            </div>""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════
# Step 1 — 투자대상 사전검토
# ════════════════════════════════════════════════════════════════════
elif page == "step1":
    st.markdown('<span class="badge-step">Step 1</span><span style="font-size:15px;font-weight:600">투자대상 사전검토</span>', unsafe_allow_html=True)
    st.markdown("")
    render_registered_modules(1)

# ════════════════════════════════════════════════════════════════════
# Step 2 — 리스크 관리
# ════════════════════════════════════════════════════════════════════
elif page == "step2":
    st.markdown('<span class="badge-step">Step 2</span><span style="font-size:15px;font-weight:600">리스크 관리</span>', unsafe_allow_html=True)
    st.markdown("")
    dart_ok = bool(os.environ.get("DART_API_KEY"))
    fred_ok = bool(os.environ.get("FRED_API_KEY"))
    api_status_parts = []
    if dart_ok:
        api_status_parts.append("DART ✓")
    if fred_ok:
        api_status_parts.append("FRED ✓")
    if api_status_parts:
        st.markdown(f'<div class="notify-bar">ℹ️ {" · ".join(api_status_parts)} 연결됨 — API 키 추가는 설정 탭에서</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="notify-bar-amber">⚠️ DART·FRED API 키 미입력 — 설정 탭에서 키를 추가하면 실시간 데이터가 활성화됩니다</div>', unsafe_allow_html=True)

    # 등록된 실제 모듈 렌더링 (M-2-1, M-2-2, M-2-3)
    render_registered_modules(2)

# ════════════════════════════════════════════════════════════════════
# Step 3 — AI 투자심의위원회
# ════════════════════════════════════════════════════════════════════
elif page == "step3":
    st.markdown('<span class="badge-step">Step 3</span><span style="font-size:15px;font-weight:600">AI 투자심의위원회</span>', unsafe_allow_html=True)
    st.markdown("")
    st.markdown('<div class="notify-bar">💬 AI 심의 프롬프트를 생성하고, 분석 결과를 종목 근거 일지에 저장하세요</div>', unsafe_allow_html=True)

    render_registered_modules(3)

# ════════════════════════════════════════════════════════════════════
# Step 4 — 집행·모니터링
# ════════════════════════════════════════════════════════════════════
elif page == "step4":
    st.markdown('<span class="badge-step">Step 4</span><span style="font-size:15px;font-weight:600">집행 및 모니터링</span>', unsafe_allow_html=True)
    st.markdown("")

    # 리밸런싱 알림 배너 (현재 배분 vs 목표 배분에서 계산 · KIS 연결 시에만 표시)
    for alert in state.rebalance_alerts:
        st.markdown(f"""
        <div class="notify-bar-amber">
          ⚠️ <b>{alert['asset']}</b> 현재 {alert['current']}% → 목표 {alert['target']}%<br>
          <span style="font-size:11px">약 {alert['amount']:,}원 조정 필요</span>
        </div>""", unsafe_allow_html=True)

    # 등록된 실제 모듈 렌더링 (M-4-1 비중 모니터링)
    render_registered_modules(4)

# ════════════════════════════════════════════════════════════════════
# 설정
# ════════════════════════════════════════════════════════════════════
elif page == "settings":
    st.markdown('<span style="font-size:15px;font-weight:600">⚙️ 시스템 설정</span>', unsafe_allow_html=True)
    st.markdown("")

    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown("**🔑 API 키 관리**")
            for label, env_key, ss_key in API_KEYS:
                saved_indicator = " ✓" if os.environ.get(env_key) else ""
                st.text_input(
                    f"{label}{saved_indicator}",
                    type="password",
                    placeholder="저장됨 (변경 시 입력)" if os.environ.get(env_key) else "입력하세요",
                    key=ss_key,
                )
            if st.button("저장", type="primary"):
                saved_keys = []
                for label, env_key, ss_key in API_KEYS:
                    val = st.session_state.get(ss_key, "").strip()
                    if val:
                        set_key(str(ENV_PATH), env_key, val)
                        os.environ[env_key] = val
                        saved_keys.append(label)
                if saved_keys:
                    st.success(f"저장 완료: {', '.join(saved_keys)}")
                    st.rerun()
                else:
                    st.warning("저장할 키가 없습니다. 입력란에 값을 입력하세요.")

        # ── KIS(한국투자증권) 포트폴리오 조회 연결 (M-3-3 유틸리티) ──
        with st.container(border=True):
            st.markdown("**📈 KIS 잔고 연결** (조회 전용 · 주문 없음)")
            _ks = state.kis_status
            if _ks.get("source") == "live":
                st.success(f"연결됨 — {_ks.get('message','')}")
            else:
                st.warning(f"미연결 — {_ks.get('message','KIS API 키 필요')}")

            st.caption("APP KEY는 위 'API 키 관리'에서 입력합니다. 아래 3개를 추가로 채워야 연결됩니다.")
            st.text_input("KIS APP SECRET" + (" ✓" if os.environ.get("KIS_APP_SECRET") else ""),
                          type="password",
                          placeholder="저장됨 (변경 시 입력)" if os.environ.get("KIS_APP_SECRET") else "입력하세요",
                          key="api_kis_secret")
            st.text_input("계좌번호 (예: 12345678-01)",
                          value=os.environ.get("KIS_ACCOUNT_NO", ""),
                          key="api_kis_account")
            _mode_opts = ["virtual", "real"]
            _cur_mode = os.environ.get("KIS_MODE", "virtual")
            st.selectbox("투자 모드", _mode_opts,
                         index=_mode_opts.index(_cur_mode) if _cur_mode in _mode_opts else 0,
                         format_func=lambda m: "모의투자 (virtual)" if m == "virtual" else "실전투자 (real)",
                         key="api_kis_mode")

            kc1, kc2 = st.columns(2)
            with kc1:
                if st.button("저장 후 연결", type="primary", use_container_width=True):
                    if st.session_state.get("api_kis_secret", "").strip():
                        set_key(str(ENV_PATH), "KIS_APP_SECRET", st.session_state["api_kis_secret"].strip())
                        os.environ["KIS_APP_SECRET"] = st.session_state["api_kis_secret"].strip()
                    acct = st.session_state.get("api_kis_account", "").strip()
                    set_key(str(ENV_PATH), "KIS_ACCOUNT_NO", acct)
                    os.environ["KIS_ACCOUNT_NO"] = acct
                    set_key(str(ENV_PATH), "KIS_MODE", st.session_state["api_kis_mode"])
                    os.environ["KIS_MODE"] = st.session_state["api_kis_mode"]
                    refresh_portfolio()
                    st.rerun()
            with kc2:
                if st.button("잔고 새로고침", use_container_width=True):
                    refresh_portfolio()
                    st.rerun()

    with c2:
        with st.container(border=True):
            st.markdown("**🕐 자동화 스케줄**")
            st.time_input("아침 브리핑",     value=None, key="sched_morning")
            st.time_input("장마감 브리핑",   value=None, key="sched_close")
            st.selectbox("리밸런싱 체크 주기", ["매일", "매주", "매월"], key="sched_rebal")
            st.text_input("리밸런싱 임계값", value="±5%", key="sched_threshold")

        with st.container(border=True):
            n_built = len(BUILT_MODULES)
            n_total = n_built + len(PLANNED_MODULES)
            st.markdown(f"**📋 모듈 목록 · 개발현황** &nbsp;<span style='color:#6b7280;font-size:12px'>완료 {n_built} / 전체 {n_total}</span>", unsafe_allow_html=True)

            # 개발 완료 (레지스트리 등록) 모듈
            for mod in BUILT_MODULES:
                meta = mod.MODULE_META
                step_label = f"Step {meta.get('step', '-')}"
                st.markdown(
                    f"`{mod.MODULE_ID}` — {meta.get('icon','')} {meta.get('title','')} "
                    f"({step_label}) <span class='tag tag-green'>✅ 사용 중</span>",
                    unsafe_allow_html=True,
                )

            # 개발 예정 모듈
            for m in PLANNED_MODULES:
                st.markdown(
                    f"`{m['id']}` — {m['icon']} {m['title']} "
                    f"(Step {m['step']}) <span class='tag tag-gray'>🚧 개발 예정</span>",
                    unsafe_allow_html=True,
                )
