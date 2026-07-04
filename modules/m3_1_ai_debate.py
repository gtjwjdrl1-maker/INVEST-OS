"""
M-3-1 · AI 심의 프롬프트 생성기 (m3_1_ai_debate)

Claude·Gemini·Perplexity에 붙여넣을 분석 프롬프트를 자동 생성한다.
외부 AI API를 직접 호출하지 않으며, API 키가 없어도 완전히 동작한다.
"""
from __future__ import annotations

import streamlit as st

from core.state import WATCHLIST_KEY

MODULE_ID = "m3_1_ai_debate"
MODULE_META = {
    "title": "AI 심의 프롬프트 생성기",
    "step": 3,
    "icon": "💬",
    "default_visible": True,
    "description": "Claude·Gemini·Perplexity에 붙여넣을 분석 프롬프트 자동 생성",
}

# ════════════════════════════════════════════════════════════════════
# 프롬프트 템플릿
# ════════════════════════════════════════════════════════════════════

def _perplexity_prompt(name: str, ticker: str) -> str:
    label = f"{name} ({ticker})" if ticker else name
    return f"""다음 종목에 대한 최신 정보를 수집해 주세요.

종목: {label}

수집 항목:
1. 최근 3개월 주요 뉴스 (경영, 실적, 공시)
2. 최근 공시 내역 (DART 기준) — 주요 계약, 유상증자, 지분 변동 등
3. 최근 애널리스트 리포트 요약 (목표주가, 투자의견 변경)
4. 업종 내 주요 이슈 및 경쟁사 동향
5. 글로벌 관련 이슈 (원자재, 환율, 규제 등)

각 항목별로 출처(날짜 포함)를 명시해 주세요.
"""


def _claude_prompt(name: str, ticker: str) -> str:
    label = f"{name} ({ticker})" if ticker else name
    return f"""종목 투자 심의를 위한 찬반 분석을 수행해 주세요.

종목: {label}

[찬성 측 — 가치투자 관점]
- 현재 밸류에이션(PER·PBR·EV/EBITDA)은 역사적·업종 대비 적정한가?
- 핵심 경쟁 우위(해자)와 현금흐름 창출 능력은?
- 배당 정책 및 주주환원 계획은?
- 편입을 지지하는 가장 강력한 근거 3가지

[반대 측 — 리스크 관점]
- 현재 주가에 반영되지 않은 주요 리스크는?
- 업황 둔화·경쟁 심화·규제 리스크가 있는가?
- 편입을 반대하는 가장 강력한 근거 3가지

[종합 의견]
- 찬반 양쪽 논거를 비교했을 때 어느 쪽이 더 설득력 있는가?
- 편입한다면 적정 비중(전체 포트 대비 %)과 그 근거는?
- 모니터링해야 할 핵심 지표 3가지

[뉴스 감시 키워드]
위 '모니터링해야 할 핵심 지표 3가지'를 뉴스 검색에 바로 쓸 수 있는
단어로 변환하여 아래 형식으로만 출력하세요. 설명 없이 형식만:

KEYWORDS: ["키워드1", "키워드2", "키워드3"]

공개된 재무·시장 정보만 사용하고, 추측성 단정은 피해 주세요.
"""


def _gemini_prompt(name: str, ticker: str) -> str:
    label = f"{name} ({ticker})" if ticker else name
    return f"""종목의 업종 포지셔닝과 경쟁 구도를 교차검증해 주세요.

종목: {label}

분석 항목:
1. 업종 내 시장점유율 및 경쟁사 비교 (주요 경쟁사 3~5곳)
2. 글로벌 동종업계 밸류에이션 비교 (해외 피어 그룹)
3. 향후 3년 업종 성장률 전망 및 해당 종목의 수혜/피해 여부
4. 공급망·원가 구조상 차별점은?
5. ESG·지배구조 측면에서 업종 내 위치는?

[최종 판단]
- 업종·경쟁 관점에서 이 종목을 편입할 매력이 있는가? (상·중·하)
- 가장 중요한 투자 포인트 하나를 한 문장으로 요약해 주세요.

공개된 정보만 사용하고, 한국어로 작성해 주세요.
"""


# ════════════════════════════════════════════════════════════════════
# 렌더링
# ════════════════════════════════════════════════════════════════════

def render(state) -> None:
    # session_state 초기화 — 페이지 전환 후 돌아와도 입력값 유지
    if "m3_1_name" not in st.session_state:
        st.session_state["m3_1_name"] = ""
    if "m3_1_ticker" not in st.session_state:
        st.session_state["m3_1_ticker"] = ""

    st.subheader("💬 AI 심의 프롬프트 생성기", divider="gray")
    st.caption(
        "종목을 입력하면 **Perplexity · Claude · Gemini**에 바로 붙여넣을 수 있는 "
        "분석 프롬프트를 자동으로 만들어 드립니다."
    )

    # ── 입력 ────────────────────────────────────────────────────────
    c1, c2 = st.columns([3, 2])
    with c1:
        name = st.text_input("회사명", placeholder="예: 삼양식품", key="m3_1_name")
    with c2:
        ticker = st.text_input("티커 / 종목코드", placeholder="예: 003230", key="m3_1_ticker")

    generate = st.button("🚀 프롬프트 생성", type="primary", use_container_width=True)

    if generate:
        if not (name.strip() or ticker.strip()):
            st.warning("회사명 또는 티커를 입력하세요.")
            return
        st.session_state["m3_1_generated"] = True
        st.session_state["m3_1_result_name"] = name.strip()
        st.session_state["m3_1_result_ticker"] = ticker.strip()

    if not st.session_state.get("m3_1_generated"):
        st.info("회사명과 티커를 입력한 뒤 **프롬프트 생성** 버튼을 누르세요.", icon="ℹ️")
        return

    n, t = st.session_state["m3_1_result_name"], st.session_state["m3_1_result_ticker"]

    # ── 결과 탭 ─────────────────────────────────────────────────────
    tab_perp, tab_claude, tab_gemini = st.tabs(["🔍 Perplexity", "🤖 Claude", "✨ Gemini"])

    with tab_perp:
        st.caption("**Perplexity** — 최신 뉴스·공시·리포트를 실시간 검색합니다.")
        prompt_p = _perplexity_prompt(n, t)
        st.text_area("Perplexity 프롬프트", value=prompt_p, height=300, key=f"ta_perp_{n}_{t}")
        st.code(prompt_p, language=None)

    with tab_claude:
        st.caption("**Claude Pro** — 찬성·반대 양측 논거를 심층 분석합니다.")
        prompt_c = _claude_prompt(n, t)
        st.text_area("Claude 프롬프트", value=prompt_c, height=300, key=f"ta_claude_{n}_{t}")
        st.code(prompt_c, language=None)

    with tab_gemini:
        st.caption("**Gemini Pro** — 업종·경쟁사·글로벌 피어를 교차검증합니다.")
        prompt_g = _gemini_prompt(n, t)
        st.text_area("Gemini 프롬프트", value=prompt_g, height=300, key=f"ta_gemini_{n}_{t}")
        st.code(prompt_g, language=None)

    # ── 하단 안내 카드 ───────────────────────────────────────────────
    st.info(
        "💡 **추천 분석 순서**\n\n"
        "1️⃣ **Perplexity** — 최신 뉴스·공시 수집\n"
        "2️⃣ **Claude Pro** — 찬반 심층 분석\n"
        "3️⃣ **Gemini Pro** — 업종·경쟁 교차검증\n\n"
        "분석 결과는 아래 '종목 선택 근거 기록' 모듈에 저장하세요.",
        icon="📋",
    )

    # ── 뉴스 감시 키워드 저장 ────────────────────────────────────────
    st.divider()
    st.markdown("**📌 뉴스 감시 키워드 저장**")

    col1, col2, col3 = st.columns(3)
    kw1 = col1.text_input("키워드 1", key="kw1")
    kw2 = col2.text_input("키워드 2", key="kw2")
    kw3 = col3.text_input("키워드 3", key="kw3")

    if st.button("저장", key="m3_1_watchlist_save"):
        st.session_state.setdefault(WATCHLIST_KEY, {})
        keywords = [k for k in [kw1, kw2, kw3] if k.strip()]
        st.session_state[WATCHLIST_KEY][n] = keywords
        st.success(f"{n} 키워드 {len(keywords)}개 저장됨")
