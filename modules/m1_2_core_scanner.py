from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st
import yfinance as yf

MODULE_ID = "m1_2_core_scanner"
MODULE_META = {
    "title": "코어전략 후보 스캐너",
    "step": 1,
    "icon": "🔍",
    "default_visible": True,
    "description": "전체 상장 종목 자동 탐색 → 배당성장·ROE·부채비율 조건 충족 종목 추천",
}

_CACHE_TTL = 3600  # 1시간

# ── 산업 분류 계층 (대분류 → 중분류 → [소분류]) ──────────────────────────
# yfinance sectorKey / industryKey 기준 (로그인 불필요, 무료)
# 구조: 대분류 → 중분류 → [industryKey, ...]
#   대분류 값 중 "_sector" 키는 sectorKey 빠른 일치용
SECTOR_HIERARCHY: dict[str, dict] = {
    "기술/IT": {
        "_sector": "technology",
        "반도체": ["semiconductors", "semiconductor-equipment-materials"],
        "소프트웨어": [
            "software-application", "software-infrastructure",
            "information-technology-services",
        ],
        "인터넷/게임": [
            "internet-content-information", "electronic-gaming-multimedia",
        ],
        "하드웨어/전자": [
            "consumer-electronics", "electronic-components",
            "computer-hardware", "communication-equipment",
        ],
    },
    "통신": {
        "_sector": "communication-services",
        "통신서비스": ["telecom-services"],
        "미디어/엔터": [
            "entertainment", "broadcasting", "publishing",
            "internet-content-information",
        ],
    },
    "산업재": {
        "_sector": "industrials",
        "방산/항공": ["aerospace-defense"],
        "조선/해운": ["marine-shipping"],
        "기계/장비": ["specialty-industrial-machinery", "tools-accessories"],
        "건설": ["engineering-construction", "infrastructure-operations"],
        "운송": ["railroads", "trucking", "air-freight-logistics", "airlines"],
        "전기장비": ["electrical-equipment-parts"],
    },
    "경기소비재": {
        "_sector": "consumer-cyclical",
        "자동차": ["auto-manufacturers", "auto-parts"],
        "패션/뷰티": ["apparel-manufacturing", "apparel-retail", "personal-products-services"],
        "가전": ["household-appliances"],
        "유통/이커머스": ["internet-retail", "specialty-retail", "department-stores"],
    },
    "필수소비재": {
        "_sector": "consumer-defensive",
        "식음료": ["beverages-non-alcoholic", "beverages-alcoholic", "packaged-foods"],
        "생활용품": ["household-personal-products", "discount-stores", "grocery-stores"],
        "담배": ["tobacco"],
    },
    "헬스케어": {
        "_sector": "healthcare",
        "바이오": ["biotechnology"],
        "제약": ["drug-manufacturers-general", "drug-manufacturers-specialty-generic"],
        "의료기기": ["medical-devices", "medical-instruments-supplies"],
        "병원/서비스": ["health-information-services", "healthcare-plans"],
    },
    "금융": {
        "_sector": "financial-services",
        "은행": ["banks-regional", "banks-diversified"],
        "보험": ["insurance-life", "insurance-property-casualty", "insurance-diversified"],
        "증권/자산운용": ["capital-markets", "financial-conglomerates", "asset-management"],
        "소비자금융": ["credit-services"],
    },
    "부동산": {
        "_sector": "real-estate",
        "부동산": ["real-estate-services", "real-estate-diversified", "reit-diversified"],
    },
    "소재/화학": {
        "_sector": "basic-materials",
        "화학": ["chemicals", "specialty-chemicals"],
        "철강/금속": ["steel", "aluminum", "other-industrial-metals-mining"],
        "포장재": ["packaging-containers"],
    },
    "에너지": {
        "_sector": "energy",
        "석유/가스": ["oil-gas-integrated", "oil-gas-e-p", "oil-gas-refining-marketing"],
        "신재생에너지": ["solar", "utilities-renewable"],
    },
    "유틸리티": {
        "_sector": "utilities",
        "전기/가스": [
            "utilities-regulated-electric", "utilities-regulated-gas",
            "utilities-diversified",
        ],
    },
}


# ── 1단계: 시총·거래대금 필터 (pykrx 우선, FDR 폴백) ──────────────────

def _stage1_filter(
    markets: list[str],
    min_cap_eok: float,
    min_turnover_eok: float,
    status_ph,
) -> list[dict]:
    import datetime

    base_date = datetime.date.today().strftime("%Y%m%d")
    candidates: list[dict] = []

    for mkt in markets:
        status_ph.info(f"1단계 | {mkt}: 전체 종목 시총·거래대금 조회 중...")

        # ── 1순위: pykrx (KRX getJsonData 경로, 상대적으로 안정적) ──
        try:
            from pykrx import stock
            cap = stock.get_market_cap_by_ticker(base_date, market=mkt, alternative=True)
            if cap is not None and not cap.empty:
                cap = cap.copy()
                cap["시총_억"]     = pd.to_numeric(cap["시가총액"], errors="coerce") / 1e8
                cap["거래대금_억"] = pd.to_numeric(cap["거래대금"], errors="coerce") / 1e8
                n_all = len(cap)
                cap = cap[(cap["시총_억"] >= min_cap_eok) &
                          (cap["거래대금_억"] >= min_turnover_eok)]
                status_ph.info(f"1단계 | {mkt}: {n_all:,}개 → {len(cap):,}개 통과 (pykrx)")

                for code, row in cap.iterrows():
                    code = str(code).zfill(6)
                    try:
                        name = stock.get_market_ticker_name(code)
                    except Exception:
                        name = code
                    candidates.append({
                        "ticker_krx": code,
                        "종목명": name,
                        "시장": mkt,
                        "시총(억)": round(float(row["시총_억"]), 0),
                        "거래대금(억)": round(float(row["거래대금_억"]), 1),
                    })
                continue  # 이 시장 완료 → FDR 폴백 불필요
        except Exception as e:
            status_ph.info(f"1단계 | {mkt}: pykrx 실패({str(e)[:40]}) → FDR 재시도")

        # ── 2순위: FinanceDataReader 폴백 ──
        try:
            import FinanceDataReader as fdr
            df = fdr.StockListing(mkt)
        except Exception as e:
            st.warning(f"{mkt} 종목 목록 조회 실패: {e}")
            continue
        if df is None or df.empty:
            st.warning(f"{mkt} 종목 목록이 비어 있습니다.")
            continue

        df = df.copy()
        df["시총_억"]     = pd.to_numeric(df["Marcap"], errors="coerce") / 1e8
        df["거래대금_억"] = pd.to_numeric(df["Amount"], errors="coerce") / 1e8
        df = df[(df["시총_억"] >= min_cap_eok) &
                (df["거래대금_억"] >= min_turnover_eok)]

        for _, row in df.iterrows():
            code = str(row.get("Code", "")).zfill(6)
            candidates.append({
                "ticker_krx": code,
                "종목명": str(row.get("Name", code)),
                "시장": mkt,
                "시총(억)": round(float(row["시총_억"]), 0),
                "거래대금(억)": round(float(row["거래대금_억"]), 1),
            })

    return candidates


# ── 2단계: yfinance 재무 필터 ─────────────────────────────────────────

def _yf_symbol(krx_code: str, market: str) -> str:
    return krx_code + (".KS" if market == "KOSPI" else ".KQ")



def _sector_match(info: dict, sector_keys: set[str], industry_keys: set[str]) -> bool:
    """
    yfinance info의 sectorKey/industryKey가 필터와 일치하는지 확인.
    sector_keys가 비어 있으면 True (필터 없음).
    종목에 섹터 정보가 없으면 True (알 수 없으면 통과).
    """
    if not sector_keys and not industry_keys:
        return True
    s_key = info.get("sectorKey", "")
    i_key = info.get("industryKey", "")
    if not s_key and not i_key:
        return True  # 섹터 정보 없는 종목은 통과
    if sector_keys and s_key in sector_keys:
        if not industry_keys:
            return True
    if industry_keys and i_key in industry_keys:
        return True
    return False


def _stage2_check(
    candidate: dict,
    min_roe: float | None,
    min_op_margin: float | None,
    max_debt: float | None,
    max_per: float | None,
    min_eps_growth: float | None,
    min_rev_growth: float | None,
    sector_keys: frozenset[str],
    industry_keys: frozenset[str],
) -> dict | None:
    sym = _yf_symbol(candidate["ticker_krx"], candidate["시장"])
    try:
        t = yf.Ticker(sym)
        info = t.info or {}

        # 산업분류 필터 (기존 로직 유지)
        if not _sector_match(info, sector_keys, industry_keys):
            return None

        # ── ROE ──────────────────────────────────────────────
        roe_raw = info.get("returnOnEquity")
        if min_roe is not None:
            if roe_raw is None or roe_raw < min_roe / 100:
                return None
        roe = round((roe_raw or 0) * 100, 1)

        # ── 영업이익률 ────────────────────────────────────────
        op_raw = info.get("operatingMargins")
        if min_op_margin is not None:
            if op_raw is None or op_raw < min_op_margin / 100:
                return None
        op_margin = round((op_raw or 0) * 100, 1)

        # ── 부채비율 ──────────────────────────────────────────
        dte_raw = info.get("debtToEquity")
        if max_debt is not None:
            if dte_raw is None or dte_raw >= max_debt:
                return None
        debt = round(dte_raw or 0, 1)

        # ── PER (trailingPE 없으면 forwardPE 폴백) ────────────
        per_raw = info.get("trailingPE") or info.get("forwardPE")
        if max_per is not None:
            # PER이 None이거나 음수(적자)면 탈락
            if per_raw is None or per_raw <= 0 or per_raw > max_per:
                return None
        per = round(per_raw, 1) if per_raw and per_raw > 0 else None

        # ── EPS 성장률 ────────────────────────────────────────
        eps_g_raw = info.get("earningsGrowth")  # 연간 YoY
        if eps_g_raw is None:
            eps_g_raw = info.get("earningsQuarterlyGrowth")  # 분기 폴백
        if min_eps_growth is not None:
            if eps_g_raw is None or eps_g_raw < min_eps_growth / 100:
                return None
        eps_growth = round((eps_g_raw or 0) * 100, 1)

        # ── 매출 성장률 ───────────────────────────────────────
        rev_g_raw = info.get("revenueGrowth")
        if min_rev_growth is not None:
            if rev_g_raw is None or rev_g_raw < min_rev_growth / 100:
                return None
        rev_growth = round((rev_g_raw or 0) * 100, 1)

        return {
            **candidate,
            "티커":        sym,
            "섹터":        info.get("sector", ""),
            "업종":        info.get("industry", ""),
            "ROE(%)":      roe,
            "영업이익률(%)": op_margin,
            "부채비율(%)":  debt,
            "PER(배)":     per,
            "EPS성장률(%)": eps_growth,
            "매출성장률(%)": rev_growth,
        }
    except Exception:
        return None


# ── 산업분류 선택 → sectorKey/industryKey 집합 변환 ────────────────────

def _resolve_sector_keys(
    major: str, mid: str, selected_subs: list[str]
) -> tuple[set[str], set[str]]:
    """
    UI 선택값을 (sector_keys, industry_keys) 집합으로 변환.
    - major="전체" → 둘 다 빈 set (필터 없음)
    - mid="전체"  → sector_key 하나만 사용 (해당 대분류 전체)
    - subs 있음   → industry_keys 목록 사용
    """
    if major == "전체":
        return set(), set()

    major_data = SECTOR_HIERARCHY.get(major, {})
    sector_key = major_data.get("_sector", "")

    if mid == "전체":
        return ({sector_key} if sector_key else set()), set()

    mid_industries: list[str] = major_data.get(mid, [])

    if selected_subs:
        # 소분류는 industry key 자체 (리스트 원소가 industryKey)
        return set(), set(selected_subs)
    else:
        return set(), set(mid_industries)


# ── AI 해석 ───────────────────────────────────────────────────────────

def _ai_interpret(results: list[dict]) -> str:
    """
    Gemini 2.5 Flash-Lite로 스크리닝 결과를 업종별 비교 분석.
    결과 테이블을 텍스트로 변환 후 구조화된 해석 요청.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return "GEMINI_API_KEY가 없어 AI 해석을 사용할 수 없습니다."

    headers = ["종목명", "업종", "ROE(%)", "영업이익률(%)", "부채비율(%)",
               "PER(배)", "EPS성장률(%)", "매출성장률(%)"]
    rows = []
    for r in results:
        rows.append(
            f"{r.get('종목명','?')} | {r.get('업종','?')} | "
            f"{r.get('ROE(%)','?')} | {r.get('영업이익률(%)','?')} | "
            f"{r.get('부채비율(%)','?')} | {r.get('PER(배)','?')} | "
            f"{r.get('EPS성장률(%)','?')} | {r.get('매출성장률(%)','?')}"
        )
    table_text = " | ".join(headers) + "\n" + "\n".join(rows)

    prompt = f"""당신은 한국 주식 전문 투자 분석가입니다.
아래는 재무 스크리닝을 통과한 한국 상장 종목들의 지표입니다.

{table_text}

다음 순서로 분석해주세요:

① 업종별 그룹화 & 동종업계 내 비교
  - 같은 업종끼리 묶어 ROE·영업이익률·PER을 상대 비교
  - 업종 특성 감안 (예: 금융업은 부채비율 높은 게 정상)

② 종목별 판정 (표 형식)
  | 종목명 | 판정 | 핵심 근거 (1줄) |
  판정 기준: 우량⭐ / 보통 / 주의⚠️

③ 주의 신호 탐지
  - ROE 높은데 부채비율도 높은 종목 (레버리지 의존 가능성)
  - EPS 성장하는데 매출이 역성장인 종목 (비용 절감 위주 개선)
  - PER 낮지만 EPS도 역성장인 종목 (싼 데는 이유가 있을 수 있음)

④ Top 3 추천
  선정 이유를 지표 간 상호관계 기준으로 2문장 이내로 설명

한국어로 답변. 불필요한 서론 없이 바로 분석 시작."""

    # 우선순위 순으로 시도 (앞 모델이 503이면 다음으로 폴백)
    _MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        last_err = None
        for model in _MODELS:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                )
                return response.text.strip()
            except Exception as e:
                last_err = e
                if "503" not in str(e) and "UNAVAILABLE" not in str(e):
                    break  # 503 외 오류(인증 실패 등)는 재시도 의미 없음
        return f"Gemini API 오류: {last_err}"
    except ImportError:
        return "google-genai 패키지가 없습니다. `pip install google-genai` 후 재시작하세요."


# ── 결과 표시 ─────────────────────────────────────────────────────────

def _show_results(results: list[dict], state) -> None:
    if not results:
        st.info("조건을 충족하는 종목이 없습니다. 스크리닝 조건을 완화해 보세요.")
        return

    st.markdown(
        f'<div style="background:#064e3b;border-radius:8px;padding:10px 14px;'
        f'margin:8px 0;color:#6ee7b7;font-size:13px">'
        f'<b>✅ 조건 충족 종목 {len(results)}개 발견</b></div>',
        unsafe_allow_html=True,
    )

    col_order = [
        "종목명", "티커", "시장", "섹터", "업종", "시총(억)",
        "ROE(%)", "영업이익률(%)", "부채비율(%)", "PER(배)",
        "EPS성장률(%)", "매출성장률(%)", "거래대금(억)",
    ]
    df = pd.DataFrame(results)
    df = df[[c for c in col_order if c in df.columns]]
    df = df.sort_values("시총(억)", ascending=False).reset_index(drop=True)

    st.dataframe(df, use_container_width=True, height=min(420, 55 + 35 * len(df)))
    st.markdown("---")

    if st.button(
        "Step 2 DART 분석으로 ↗",
        key="m1_2_dart_btn",
        use_container_width=True,
        type="primary",
    ):
        ticker_list = [r["ticker_krx"] for r in results]
        st.session_state["dart_candidate_tickers"] = ticker_list
        st.success(f"{len(ticker_list)}개 종목이 Step 2 분석 목록에 저장되었습니다.")

    # ── AI 종합 해석 ─────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 🤖 AI 종합 해석")
    st.caption("Gemini 2.5 Flash-Lite가 업종별 비교 분석 · 판정 · Top 3 추천을 제공합니다.")

    col_ai1, col_ai2 = st.columns([2, 3])
    with col_ai1:
        ai_clicked = st.button(
            "🤖 AI 종합 해석 요청",
            key="m1_2_ai_btn",
            use_container_width=True,
            type="primary",
        )
    with col_ai2:
        st.caption(f"분석 대상 {len(results)}개 종목 · 예상 소요 5~15초")

    if ai_clicked:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if not gemini_key:
            st.warning(
                "Gemini API 키가 없습니다. `.env`에 `GEMINI_API_KEY`를 추가하세요.",
                icon="⚠️",
            )
        else:
            with st.spinner("Gemini가 업종별 비교 분석 중…"):
                interpretation = _ai_interpret(results)
            st.session_state["m1_2_ai_result"] = interpretation
            with st.expander("📊 AI 분석 결과 보기", expanded=True):
                st.markdown(interpretation)
                st.caption("본 분석은 AI 생성 내용으로 투자 권유가 아닙니다. 최종 판단은 본인이 하세요.")

    elif st.session_state.get("m1_2_ai_result"):
        with st.expander("📊 AI 분석 결과 (이전 결과)", expanded=False):
            st.markdown(st.session_state["m1_2_ai_result"])


# ── 메인 render ───────────────────────────────────────────────────────

def render(state) -> None:
    st.markdown(
        '<div class="inv-card"><div class="inv-card-title">🔍 코어전략 후보 스캐너</div>',
        unsafe_allow_html=True,
    )

    # ══════════════════════════════════════════════════════
    # 1. 산업분류 필터
    # ══════════════════════════════════════════════════════
    with st.expander("🏭 산업분류 필터 (선택)", expanded=True):
        st.caption("yfinance 섹터/업종 기준 · '전체'를 선택하면 모든 산업 대상")

        major = "전체"
        mid   = "전체"
        selected_subs: list[str] = []

        major_options = ["전체"] + [k for k in SECTOR_HIERARCHY if not k.startswith("_")]
        major = st.selectbox("대분류", major_options, key="m1_2_major")

        if major != "전체":
            mid_options = ["전체"] + [
                k for k in SECTOR_HIERARCHY[major] if not k.startswith("_")
            ]
            mid = st.selectbox("중분류", mid_options, key="m1_2_mid")

            if mid != "전체":
                sub_options = SECTOR_HIERARCHY[major].get(mid, [])
                selected_subs = st.multiselect(
                    "소분류 industryKey (복수 선택, 비우면 중분류 전체)",
                    sub_options,
                    default=[],
                    key="m1_2_sub",
                )

        # 선택 요약 표시
        s_keys, i_keys = _resolve_sector_keys(major, mid, selected_subs)
        if s_keys or i_keys:
            preview = list(i_keys or s_keys)
            st.info(f"필터 적용: {', '.join(preview[:5])}{'…' if len(preview) > 5 else ''}")

    # ══════════════════════════════════════════════════════
    # 2. 스크리닝 조건 (조건별 ON/OFF 체크박스)
    # ══════════════════════════════════════════════════════
    with st.expander("⚙️ 스크리닝 조건 설정", expanded=True):

        col_l, col_r = st.columns(2)
        with col_l:
            min_cap = st.number_input(
                "시가총액 최소 (억원)", value=5000, step=500, min_value=0, key="m1_2_cap"
            )
        with col_r:
            min_turnover = st.number_input(
                "당일 거래대금 최소 (억원)", value=30, step=10, min_value=0, key="m1_2_turn"
            )
        markets = st.multiselect(
            "대상 시장", ["KOSPI", "KOSDAQ"], default=["KOSPI"], key="m1_2_markets"
        )

        st.markdown("---")
        st.markdown("**재무 조건 (체크 해제 시 해당 조건 무시)**")

        # ROE
        col1, col2 = st.columns([1, 4])
        with col1:
            use_roe = st.checkbox("ROE", value=True, key="m1_2_use_roe")
        with col2:
            min_roe = st.slider(
                "ROE 최소 (%)", 0, 40, 10, key="m1_2_roe",
                disabled=not use_roe,
                help="자기자본이익률. 동종업 대비 높을수록 수익성 우수."
            )

        # 영업이익률
        col1, col2 = st.columns([1, 4])
        with col1:
            use_op = st.checkbox("영업이익률", value=False, key="m1_2_use_op")
        with col2:
            min_op = st.slider(
                "영업이익률 최소 (%)", 0, 40, 5, key="m1_2_op",
                disabled=not use_op,
                help="본업 수익성 지표. 금융·세금 왜곡 없이 순수 사업력 비교."
            )

        # 부채비율
        col1, col2 = st.columns([1, 4])
        with col1:
            use_debt = st.checkbox("부채비율", value=False, key="m1_2_use_debt")
        with col2:
            max_debt = st.slider(
                "부채비율 최대 (%)", 50, 500, 150, key="m1_2_debt",
                disabled=not use_debt,
                help="총부채/자기자본. 금융업은 업종 특성상 높은 게 정상."
            )

        # PER
        col1, col2 = st.columns([1, 4])
        with col1:
            use_per = st.checkbox("PER", value=False, key="m1_2_use_per")
        with col2:
            max_per = st.slider(
                "PER 최대 (배)", 1, 50, 20, key="m1_2_per",
                disabled=not use_per,
                help="주가/EPS. 업종 평균 대비 낮으면 저평가 신호. 적자기업은 자동 제외."
            )

        # EPS 성장률
        col1, col2 = st.columns([1, 4])
        with col1:
            use_eps = st.checkbox("EPS 성장률", value=False, key="m1_2_use_eps")
        with col2:
            min_eps = st.slider(
                "EPS 성장률 최소 (%)", -50, 100, 0, key="m1_2_eps",
                disabled=not use_eps,
                help="전년 대비 주당순이익 증가율. 0% 이상이면 이익이 늘고 있는 것."
            )

        # 매출 성장률
        col1, col2 = st.columns([1, 4])
        with col1:
            use_rev = st.checkbox("매출 성장률", value=False, key="m1_2_use_rev")
        with col2:
            min_rev = st.slider(
                "매출 성장률 최소 (%)", -30, 100, 0, key="m1_2_rev",
                disabled=not use_rev,
                help="전년 대비 매출 증가율. EPS 성장과 함께 보면 성장의 질 판별 가능."
            )

    # ══════════════════════════════════════════════════════
    # 3. 탐색 버튼
    # ══════════════════════════════════════════════════════
    col_start, col_refresh = st.columns([3, 1])
    with col_start:
        scan_clicked = st.button(
            "🔍 탐색 시작", type="primary", use_container_width=True, key="m1_2_scan"
        )
    with col_refresh:
        force_refresh = st.button(
            "🔄 강제 재탐색", use_container_width=True, key="m1_2_refresh"
        )

    # ══════════════════════════════════════════════════════
    # 4. 캐시 확인 및 실행
    # ══════════════════════════════════════════════════════
    cache_key  = "m1_2_results"
    ts_key     = "m1_2_ts"
    params_key = "m1_2_params"

    s_keys, i_keys = _resolve_sector_keys(major, mid, selected_subs)

    current_params = (
        tuple(sorted(markets)),
        min_cap, min_turnover,
        use_roe, min_roe,
        use_op, min_op,
        use_debt, max_debt,
        use_per, max_per,
        use_eps, min_eps,
        use_rev, min_rev,
        major, mid, tuple(sorted(selected_subs)),
    )

    cached_results = st.session_state.get(cache_key)
    cache_valid = (
        cached_results is not None
        and time.time() - st.session_state.get(ts_key, 0) < _CACHE_TTL
        and st.session_state.get(params_key) == current_params
        and not force_refresh
    )

    if cache_valid and not scan_clicked:
        elapsed = int(time.time() - st.session_state[ts_key])
        st.caption(
            f"지난 탐색 결과 재사용 중 · {elapsed // 60}분 {elapsed % 60}초 전 · "
            "강제 재탐색 버튼으로 갱신 가능"
        )
        _show_results(cached_results, state)
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if scan_clicked or force_refresh:
        if not markets:
            st.warning("대상 시장을 하나 이상 선택해 주세요.")
            st.markdown("</div>", unsafe_allow_html=True)
            return

        status_ph = st.empty()
        results: list[dict] = []

        # 1단계: 시총·거래대금 필터
        stage1 = _stage1_filter(markets, float(min_cap), float(min_turnover), status_ph)

        if not stage1:
            status_ph.warning("1단계 통과 종목이 없습니다. 조건을 완화해 보세요.")
            st.markdown("</div>", unsafe_allow_html=True)
            return

        # 2단계: yfinance 재무 + 산업분류 필터 (info 한 번 호출로 동시 처리)
        total = len(stage1)
        status_ph.info(f"2단계: {total:,}개 종목 재무 필터링 중 (yfinance 병렬)...")
        progress_bar = st.progress(0)
        done = 0

        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = {
                ex.submit(
                    _stage2_check,
                    c,
                    float(min_roe)  if use_roe  else None,
                    float(min_op)   if use_op   else None,
                    float(max_debt) if use_debt else None,
                    float(max_per)  if use_per  else None,
                    float(min_eps)  if use_eps  else None,
                    float(min_rev)  if use_rev  else None,
                    frozenset(s_keys),
                    frozenset(i_keys),
                ): c
                for c in stage1
            }
            for fut in as_completed(futures):
                done += 1
                progress_bar.progress(done / total)
                res = fut.result()
                if res:
                    results.append(res)
                if done % 10 == 0 or done == total:
                    status_ph.info(f"2단계: {done}/{total}개 처리 · 현재 {len(results)}개 통과")

        progress_bar.empty()
        status_ph.empty()

        st.session_state[cache_key] = results
        st.session_state[ts_key]    = time.time()
        st.session_state[params_key] = current_params

        _show_results(results, state)

    st.markdown("</div>", unsafe_allow_html=True)
