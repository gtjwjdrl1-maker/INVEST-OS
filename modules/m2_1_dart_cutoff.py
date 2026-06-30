"""
M-2-1 · DART 재무제표 기준 적용 (m2_1_dart_cutoff)

편입 기준 (스펙 docs/module_spec.md):
  부채비율 ≤ 100%, 배당성향 ≤ 70%, CB 잔액 = 0
"""
from __future__ import annotations

import io
import os
import zipfile
import datetime
import xml.etree.ElementTree as ET

import json
import requests
import yfinance as yf
import pandas as pd
import streamlit as st
try:
    import google.generativeai as genai
    _GENAI_AVAILABLE = True
except ImportError:
    genai = None
    _GENAI_AVAILABLE = False

MODULE_ID = "m2_1_dart_cutoff"
MODULE_META = {
    "title": "DART 재무제표 기준",
    "step": 2,
    "icon": "📋",
    "default_visible": True,
    "description": "부채비율·배당성향·CB 잔액 자동 체크 (DART API)",
}

DEBT_RATIO_MAX   = 100.0
PAYOUT_RATIO_MAX = 70.0
DART_BASE        = "https://opendart.fss.or.kr/api"


# ════════════════════════════════════════════════════════════════════
# DART API 헬퍼
# ════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _get_corp_code(dart_key: str, stock_code: str) -> str | None:
    """종목코드 → DART corp_code 변환 (zip 다운로드, 1시간 캐시)."""
    try:
        resp = requests.get(
            f"{DART_BASE}/corpCode.xml",
            params={"crtfc_key": dart_key},
            timeout=15,
        )
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_data = zf.read("CORPCODE.xml").decode("utf-8")
        root = ET.fromstring(xml_data)
        for item in root.findall("list"):
            if item.findtext("stock_code") == stock_code:
                return item.findtext("corp_code")
    except Exception:
        pass
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_fs_items(dart_key: str, corp_code: str, year: str) -> list[dict]:
    """DART 재무제표 항목 전체 반환 (1시간 캐시)."""
    params = {
        "crtfc_key": dart_key,
        "corp_code":  corp_code,
        "bsns_year":  year,
        "reprt_code": "11011",  # 사업보고서
        "fs_div":     "CFS",    # 연결재무제표
    }
    resp = requests.get(f"{DART_BASE}/fnlttSinglAcntAll.json", params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "000":
        return []
    return data.get("list", [])


def _amount(item: dict) -> int:
    """DART 항목에서 당기 금액(thstrm_amount) 추출. 부호 보존."""
    raw = (item.get("thstrm_amount") or "0").replace(",", "").strip()
    try:
        return int(raw)
    except ValueError:
        return 0


def _find_amount(items: list[dict], *keywords: str) -> int:
    """
    계정명에 keywords를 모두 포함하는 첫 번째 항목의 금액 반환.
    DART는 회사마다 계정명이 다르므로 substring 매칭 사용.
    """
    for item in items:
        nm = item.get("account_nm", "")
        if all(kw in nm for kw in keywords):
            return _amount(item)
    return 0


# ════════════════════════════════════════════════════════════════════
# 1차 필터 — yfinance
# ════════════════════════════════════════════════════════════════════

def filter_primary(stock_code: str) -> dict:
    """ROE, 시총 기준 1차 필터."""
    result = {
        "종목명": stock_code,
        "ROE(%)": None,
        "시가총액(억)": None,
        "1차_통과": True,
        "1차_사유": "",
    }
    try:
        # KOSPI(.KS) 먼저 시도, 실패하면 KOSDAQ(.KQ)
        for suffix in (".KS", ".KQ"):
            tk = yf.Ticker(stock_code + suffix)
            info = tk.info
            name = info.get("longName") or info.get("shortName") or ""
            if name:
                break
        roe    = (info.get("returnOnEquity") or 0.0) * 100
        mktcap = (info.get("marketCap") or 0) / 1e8

        result["종목명"]      = name or stock_code
        result["ROE(%)"]      = round(roe, 1)
        result["시가총액(억)"] = round(mktcap, 0)

        reasons = []
        if roe < 5:
            reasons.append(f"ROE {roe:.1f}% < 5%")
        if mktcap < 1000:
            reasons.append(f"시총 {mktcap:.0f}억 < 1000억")
        result["1차_통과"] = not reasons
        result["1차_사유"] = ", ".join(reasons)
    except Exception as e:
        result["1차_사유"] = f"yfinance 오류: {e}"
    return result


# ════════════════════════════════════════════════════════════════════
# 2차 퇴출 기준 — DART
# ════════════════════════════════════════════════════════════════════

def filter_secondary_dart(dart_key: str, stock_code: str, year: str) -> dict:
    """
    부채비율, 배당성향, CB잔액 기준 2차 퇴출 체크.
    스펙: 부채비율 ≤ 100%, 배당성향 ≤ 70%, CB 잔액 = 0
    """
    result = {
        "부채비율(%)": None,
        "배당성향(%)": None,
        "CB잔액(억)": None,
        "우발부채": "—",
        "2차_통과": False,
        "퇴출사유": "",
        "dart_오류": "",
    }
    try:
        corp_code = _get_corp_code(dart_key, stock_code)
        if not corp_code:
            result["dart_오류"] = f"종목코드 {stock_code}의 DART 기업코드를 찾을 수 없습니다."
            return result

        items = _fetch_fs_items(dart_key, corp_code, year)
        if not items:
            result["dart_오류"] = f"{year}년 사업보고서 데이터가 없습니다."
            return result

        # ── 부채비율 ────────────────────────────────────────────────
        # DART 계정명 예: "부채총계", "부채 총계", "비유동부채" 등 회사마다 다름
        # account_id(IFRS 코드)로도 찾음
        total_liab = 0
        total_equity = 0
        for item in items:
            aid  = item.get("account_id", "")
            nm   = item.get("account_nm", "")
            sj   = item.get("sj_div", "")     # BS=재무상태표
            if sj != "BS":
                continue
            if aid in ("ifrs-full_Liabilities",) or nm in ("부채총계", "부채 총계", "부채합계"):
                total_liab = _amount(item)
            if aid in ("ifrs-full_Equity",) or nm in ("자본총계", "자본 총계", "자본합계"):
                total_equity = _amount(item)

        # account_id 매칭이 안 됐을 경우 키워드 폴백
        if total_liab == 0:
            total_liab = _find_amount(items, "부채총계") or _find_amount(items, "부채합계")
        if total_equity == 0:
            total_equity = _find_amount(items, "자본총계") or _find_amount(items, "자본합계")

        debt_ratio = abs(total_liab / total_equity * 100) if total_equity else 0

        # ── 배당성향 ────────────────────────────────────────────────
        # 현금흐름표의 배당금 지급 / 손익계산서의 당기순이익
        net_income = 0
        dividends  = 0
        for item in items:
            aid = item.get("account_id", "")
            nm  = item.get("account_nm", "")
            sj  = item.get("sj_div", "")
            if sj == "IS" and (aid == "ifrs-full_ProfitLoss" or nm in ("당기순이익", "당기순손익", "당기순이익(손실)")):
                net_income = _amount(item)
            if sj == "CF" and ("배당금" in nm and "지급" in nm):
                dividends = abs(_amount(item))

        payout_ratio = (dividends / abs(net_income) * 100) if net_income else 0

        # ── CB 잔액 ──────────────────────────────────────────────────
        cb_balance = 0
        for item in items:
            nm = item.get("account_nm", "")
            if "전환사채" in nm or "교환사채" in nm:
                cb_balance += abs(_amount(item))
        cb_억 = round(cb_balance / 1e8, 1)

        result.update({
            "부채비율(%)": round(debt_ratio, 1),
            "배당성향(%)": round(payout_ratio, 1),
            "CB잔액(억)":  cb_억,
            "우발부채": "—",
        })

        # ── 판정 ────────────────────────────────────────────────────
        fails = []
        if debt_ratio > DEBT_RATIO_MAX:
            fails.append(f"부채비율 {debt_ratio:.1f}% > {DEBT_RATIO_MAX:.0f}%")
        if payout_ratio > PAYOUT_RATIO_MAX:
            fails.append(f"배당성향 {payout_ratio:.1f}% > {PAYOUT_RATIO_MAX:.0f}%")
        if cb_balance > 0:
            fails.append(f"CB 잔액 {cb_억:.0f}억")

        result["2차_통과"] = not fails
        result["퇴출사유"]  = " / ".join(fails)

    except Exception as e:
        result["dart_오류"] = f"DART API 오류: {e}"

    return result


# ════════════════════════════════════════════════════════════════════
# 렌더링
# ════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=86400, show_spinner=False)
def _search_company(dart_key: str, query: str) -> list[tuple[str, str]]:
    """
    DART corpCode.xml에서 회사명 부분일치 검색.
    반환: [(종목명, 6자리코드), ...] — 상장사만, 정확 일치 우선 정렬.
    """
    try:
        resp = requests.get(
            f"{DART_BASE}/corpCode.xml",
            params={"crtfc_key": dart_key},
            timeout=15,
        )
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_data = zf.read("CORPCODE.xml").decode("utf-8")
        root = ET.fromstring(xml_data)
        q = query.strip().lower()
        results = []
        for item in root.findall("list"):
            name = item.findtext("corp_name") or ""
            code = (item.findtext("stock_code") or "").strip()
            if code and len(code) == 6 and code.isdigit() and q in name.lower():
                results.append((name, code))
        # 정확 일치 → 시작 일치 → 포함 순으로 정렬
        results.sort(key=lambda x: (
            0 if x[0].lower() == q else (1 if x[0].lower().startswith(q) else 2),
            x[0],
        ))
        return results[:20]
    except Exception:
        return []


def _run_dart_analysis(dart_key: str, codes: list[str], year: str) -> None:
    """DART + yfinance 분석 후 결과를 session_state에 저장."""
    results = []
    prog = st.progress(0, text="조회 중…")
    for i, code in enumerate(codes):
        prog.progress(i / len(codes), text=f"{code} 분석 중… ({i+1}/{len(codes)})")
        p1 = filter_primary(code)
        p2 = filter_secondary_dart(dart_key, code, year)

        if p2["dart_오류"]:
            verdict, reason = "오류", p2["dart_오류"]
        elif not p2["2차_통과"]:
            verdict, reason = "퇴출", p2["퇴출사유"]
        elif not p1["1차_통과"]:
            verdict, reason = "재검토", p1["1차_사유"]
        else:
            verdict, reason = "통과", ""

        results.append({
            "종목명":      p1["종목명"],
            "종목코드":    code,
            "부채비율(%)": p2["부채비율(%)"],
            "배당성향(%)": p2["배당성향(%)"],
            "CB잔액(억)":  p2["CB잔액(억)"],
            "우발부채":    p2["우발부채"],
            "ROE(%)":      p1["ROE(%)"],
            "판정":        verdict,
            "퇴출사유":    reason,
        })
    prog.progress(1.0, text="완료")
    st.session_state["dart_results"]     = results
    st.session_state["dart_peer_df"]     = None
    st.session_state["dart_peer_target"] = None


def _build_peer_table(r: dict, peers_df: pd.DataFrame) -> pd.DataFrame:
    """분석 대상 + 피어 + 피어평균 합친 DataFrame."""
    target_row = pd.DataFrame([{
        "종목명":        r["종목명"],
        "종목코드":      r["종목코드"],
        "경쟁 근거":     "▶ 분석 대상",
        "ROE(%)":        r.get("ROE(%)"),
        "부채비율(%)":   r.get("부채비율(%)"),
        "영업이익률(%)": None,
        "배당수익률(%)": None,
        "매출성장률(%)": None,
        "영업CF증감(%)": None,
        "PER(배)":       None,
        "PBR(배)":       None,
    }])
    all_df = pd.concat([target_row, peers_df], ignore_index=True)

    numeric_cols = ["ROE(%)", "부채비율(%)", "영업이익률(%)", "배당수익률(%)",
                    "매출성장률(%)", "영업CF증감(%)", "PER(배)", "PBR(배)"]
    avg_row = {"종목명": "📊 피어 평균", "종목코드": "—", "경쟁 근거": ""}
    for col in numeric_cols:
        vals = peers_df[col].dropna()
        avg_row[col] = round(vals.mean(), 1) if not vals.empty else None
    return pd.concat([all_df, pd.DataFrame([avg_row])], ignore_index=True)


def render(state) -> None:
    dart_key = os.environ.get("DART_API_KEY", "")
    has_key  = bool(dart_key)

    # ── session_state 초기화 ──────────────────────────────────────────
    for k, v in {
        "dart_results":     [],
        "dart_peer_df":     None,
        "dart_peer_target": None,
        "dart_candidates":  [],
        "dart_year_sel":    str(datetime.date.today().year - 1),
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v

    st.subheader("📋 DART 재무제표 기준 적용", divider="gray")
    if not has_key:
        st.warning(
            "**DART API 키 없음** — 설정 탭에서 DART OpenAPI 키를 저장해야 분석할 수 있습니다.",
            icon="⚠️",
        )

    # ── 입력 영역 (form 없이 — 버튼 클릭 시 state 유지) ─────────────
    c1, c2, c3 = st.columns([4, 2, 1])
    with c1:
        user_input = st.text_input(
            "회사명 또는 종목코드",
            placeholder="예: 삼성전자  /  005930",
            key="dart_query",
        )
    with c2:
        cur_year = datetime.date.today().year
        year_input = st.selectbox(
            "기준 연도",
            [str(y) for y in range(cur_year - 1, cur_year - 4, -1)],
            key="dart_year",
        )
    with c3:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        search_btn = st.button("🔍 분석 실행", type="primary", use_container_width=True)

    # ── 검색 버튼 클릭 처리 ──────────────────────────────────────────
    if search_btn:
        raw = user_input.strip()
        if not raw:
            st.warning("회사명 또는 종목코드를 입력하세요.")
        elif not has_key:
            st.error("DART API 키가 없어 분석할 수 없습니다.", icon="🚫")
        else:
            st.session_state.update({
                "dart_results": [], "dart_peer_df": None,
                "dart_peer_target": None, "dart_candidates": [],
                "dart_year_sel": year_input,
            })
            clean = raw.replace(" ", "")
            if clean.isdigit():
                _run_dart_analysis(dart_key, [clean.zfill(6)], year_input)
            else:
                with st.spinner(f"'{raw}' 종목 검색 중…"):
                    candidates = _search_company(dart_key, raw)
                if not candidates:
                    st.warning(
                        f"'{raw}'와 일치하는 KRX 상장 종목이 없습니다. "
                        "종목코드(6자리 숫자)를 직접 입력해 보세요.", icon="⚠️"
                    )
                elif len(candidates) == 1:
                    _run_dart_analysis(dart_key, [candidates[0][1]], year_input)
                else:
                    st.session_state["dart_candidates"] = candidates

    # ── 후보 여러 개 → 선택 UI ──────────────────────────────────────
    candidates = st.session_state.get("dart_candidates", [])
    if candidates:
        options = [f"{n}  ({c})" for n, c in candidates]
        sel = st.selectbox("검색 결과 — 분석할 종목을 선택하세요", options, key="dart_cand_sel")
        if st.button("선택 종목으로 분석 실행", type="primary"):
            idx   = options.index(sel)
            year  = st.session_state.get("dart_year_sel", str(datetime.date.today().year - 1))
            st.session_state["dart_candidates"] = []
            _run_dart_analysis(dart_key, [candidates[idx][1]], year)

    # ── 결과 표시 ────────────────────────────────────────────────────
    results = st.session_state.get("dart_results", [])
    if not results:
        if not candidates:
            st.info(
                "회사명(예: 삼성전자) 또는 종목코드(예: 005930)를 입력하고 "
                "**분석 실행**을 누르면 DART 재무 기준 판정 결과가 표시됩니다.", icon="ℹ️"
            )
        return

    _render_results(results)

    # ── 피어 비교 자동 실행 (단일 종목 + 오류 아닌 경우) ────────────
    if len(results) != 1 or results[0]["판정"] == "오류":
        return

    r          = results[0]
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    target_key = r["종목코드"]
    st.divider()
    st.markdown("#### 🔍 동종업계 피어 비교")

    if not _GENAI_AVAILABLE:
        st.info("`google-generativeai` 패키지를 설치하면 피어 비교가 자동 실행됩니다.", icon="ℹ️")
        return
    if not gemini_key:
        st.info("`.env`에 `GEMINI_API_KEY`를 추가하면 피어 비교가 자동 실행됩니다.", icon="ℹ️")
        return

    # 이 종목 피어가 아직 수집되지 않았으면 자동 탐색
    if st.session_state.get("dart_peer_target") != target_key:
        with st.spinner(f"Gemini가 {r['종목명']}의 동종업계 경쟁사를 탐색 중…"):
            peers_raw, peer_err = _get_peers_via_gemini(r["종목명"], gemini_key)

        if not peers_raw:
            st.warning("Gemini에서 피어 그룹을 가져오지 못했습니다.", icon="⚠️")
            if peer_err:
                with st.expander("🔎 오류 상세 (클릭해서 확인)"):
                    st.code(peer_err, language="")
            st.session_state["dart_peer_df"]     = pd.DataFrame()
            st.session_state["dart_peer_target"] = target_key
        else:
            with st.spinner("피어 종목 재무데이터 수집 중…"):
                peers_df = _validate_and_fetch_peers(peers_raw)
            if peers_df.empty:
                st.warning("유효한 피어 종목을 확인할 수 없습니다.", icon="⚠️")
                st.session_state["dart_peer_df"] = pd.DataFrame()
            else:
                st.session_state["dart_peer_df"]    = _build_peer_table(r, peers_df)
                st.session_state["dart_peer_model"] = peer_err  # "✅ gemini-2.5-flash" 형태
            st.session_state["dart_peer_target"] = target_key

    # 피어 결과 표시
    peer_df = st.session_state.get("dart_peer_df")
    if peer_df is not None and not peer_df.empty:
        used = st.session_state.get("dart_peer_model", "")
        if used:
            st.caption(f"Gemini 모델: `{used}`")
        _render_peer_table_and_charts(peer_df, r["종목명"])
        if st.button("🔄 피어 그룹 재탐색", key=f"peer_refresh_{target_key}"):
            st.session_state["dart_peer_target"] = None
            st.session_state["dart_peer_df"]     = None
            st.rerun()


def _render_results(results: list[dict]) -> None:
    if not results:
        st.info("분석 결과가 없습니다.")
        return

    # ── 요약 카운터 ──────────────────────────────────────────────────
    n_pass = sum(1 for r in results if r["판정"] == "통과")
    n_warn = sum(1 for r in results if r["판정"] == "재검토")
    n_fail = sum(1 for r in results if r["판정"] in ("퇴출", "오류"))

    c1, c2, c3 = st.columns(3)
    c1.metric("✅ 편입 기준 통과", n_pass)
    c2.metric("⚠️ 재검토 필요",   n_warn)
    c3.metric("❌ 퇴출 기준 해당", n_fail)

    st.divider()

    # ── 종목별 상세 카드 ─────────────────────────────────────────────
    VERDICT_COLOR = {
        "통과":   ("🟢", "green"),
        "재검토": ("🟡", "orange"),
        "퇴출":   ("🔴", "red"),
        "오류":   ("⚫", "gray"),
    }

    for r in results:
        icon, color = VERDICT_COLOR.get(r["판정"], ("⚫", "gray"))
        name  = r.get("종목명") or r.get("종목코드", "—")
        code  = r.get("종목코드", "")

        with st.container(border=True):
            # 헤더 행
            hcol1, hcol2 = st.columns([6, 1])
            with hcol1:
                st.markdown(f"**{name}** &nbsp; `{code}`")
            with hcol2:
                st.markdown(
                    f"<span style='color:{color};font-weight:700'>{icon} {r['판정']}</span>",
                    unsafe_allow_html=True,
                )

            # 지표 행
            debt   = r.get("부채비율(%)")
            payout = r.get("배당성향(%)")
            cb     = r.get("CB잔액(억)")
            roe    = r.get("ROE(%)")

            m1, m2, m3, m4 = st.columns(4)

            def _delta_str(val, limit, unit="%", lower_is_bad=False):
                if val is None:
                    return None
                diff = val - limit
                return f"{diff:+.1f}{unit} (기준 {limit:.0f}{unit})"

            m1.metric(
                "부채비율",
                f"{debt}%" if debt is not None else "—",
                delta=_delta_str(debt, DEBT_RATIO_MAX) if debt is not None else None,
                delta_color="inverse",   # 낮을수록 좋음
            )
            m2.metric(
                "배당성향",
                f"{payout}%" if payout is not None else "—",
                delta=_delta_str(payout, PAYOUT_RATIO_MAX) if payout is not None else None,
                delta_color="inverse",
            )
            m3.metric(
                "CB 잔액",
                f"{cb}억" if cb is not None else "—",
                delta="기준 초과" if cb and cb > 0 else ("기준 충족" if cb == 0 else None),
                delta_color="inverse" if cb and cb > 0 else "normal",
            )
            m4.metric(
                "ROE",
                f"{roe}%" if roe is not None else "—",
            )

            # 퇴출 사유 / 우발부채
            reason = r.get("퇴출사유", "")
            conti  = r.get("우발부채", "—")
            if reason:
                st.error(f"**사유:** {reason}", icon="🚫")
            if conti and conti not in ("—", "해당없음", ""):
                st.warning(f"**우발부채:** {conti}", icon="⚠️")

    st.divider()

    # ── 기준 안내 ────────────────────────────────────────────────────
    st.caption(
        f"편입 기준: 부채비율 ≤ {DEBT_RATIO_MAX:.0f}%  ·  "
        f"배당성향 ≤ {PAYOUT_RATIO_MAX:.0f}%  ·  CB 잔액 = 0"
    )

    # ── CSV 다운로드 ─────────────────────────────────────────────────
    df = pd.DataFrame(results)
    st.download_button(
        "📥 결과 CSV 다운로드",
        data=df.to_csv(index=False, encoding="utf-8-sig"),
        file_name="dart_cutoff_result.csv",
        mime="text/csv",
    )


# ════════════════════════════════════════════════════════════════════
# 동종업계 피어 비교 — Gemini 자동 도출
# ════════════════════════════════════════════════════════════════════

PEER_PROMPT_TEMPLATE = """당신은 주식 애널리스트입니다. 아래 기업의 핵심 사업과 직접 경쟁하는 한국 거래소(KRX) 상장 기업 5개를 골라주세요.

## 선정 규칙
1. 핵심 사업 파악: 해당 기업의 매출 비중이 가장 큰 단일 사업 세그먼트를 먼저 파악한다.
   예) 삼성전자 → 반도체(메모리·파운드리), 농심 → 라면, LG화학 → 배터리
2. 동일 세그먼트 경쟁사만 선택: 핵심 사업이 "반도체"면 반도체 회사만, "라면"이면 라면 회사만 고른다.
3. 계열사·지주사·금융 자회사는 절대 포함하지 않는다.
4. KRX 상장 종목이어야 하며, 종목코드는 반드시 KRX 6자리 숫자여야 한다.

## 출력 형식 (반드시 JSON만, 설명 없이)
[{{"name": "회사명", "ticker": "6자리숫자코드", "reason": "핵심경쟁 사업 한 줄"}}]

## 분석 대상
기업명: {company_name}"""


def _call_gemini(prompt: str, gemini_key: str) -> tuple[str, str]:
    """
    google-genai 패키지로 Gemini 호출. 모델 순서대로 폴백.
    반환: (응답 텍스트, 성공한 모델명) — 모두 실패 시 예외 발생.
    """
    from google import genai as _new_genai

    # 2025년 기준 현재 유효한 모델명 (최신 → 경량 순)
    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
    ]
    errors = []
    client = _new_genai.Client(api_key=gemini_key)
    for model_name in models_to_try:
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            return resp.text, model_name
        except Exception as e:
            errors.append(f"{model_name}: {e}")

    raise RuntimeError("\n".join(errors))


def _get_peers_via_gemini(company_name: str, gemini_key: str) -> tuple[list[dict], str]:
    """
    Gemini로 동종업계 한국 상장 경쟁사 5개 도출.
    반환: (피어 목록, 에러 또는 사용된 모델명) — 성공 시 "✅ 모델명" 형태.
    캐시 없음: 에러 결과가 캐싱되는 것을 방지.
    """
    import re
    prompt = PEER_PROMPT_TEMPLATE.format(company_name=company_name)
    used_model = ""
    try:
        text, used_model = _call_gemini(prompt, gemini_key)
        # 코드블록 제거
        text = re.sub(r"^```[a-z]*\s*", "", text.strip(), flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
        peers = json.loads(text)
        filtered = [p for p in peers if str(p.get("ticker", "")).isdigit()][:5]
        if not filtered:
            return [], f"Gemini({used_model}) 응답에서 유효한 종목코드를 찾지 못했습니다.\n응답 원문:\n{text[:300]}"
        return filtered, f"✅ {used_model}"
    except json.JSONDecodeError as e:
        raw = text if "text" in locals() else "(응답 없음)"
        return [], f"JSON 파싱 실패({used_model}): {e}\nGemini 응답 원문:\n{raw[:400]}"
    except Exception as e:
        return [], str(e)


def _validate_and_fetch_peers(peers: list[dict]) -> pd.DataFrame:
    """
    피어 종목코드를 yfinance로 검증하고 재무비율 수집.
    유효하지 않은 종목은 자동 제외.
    """
    rows = []
    for p in peers:
        ticker_raw = str(p.get("ticker", "")).zfill(6)
        name = p.get("name", ticker_raw)
        for suffix in (".KS", ".KQ"):
            try:
                tk = yf.Ticker(ticker_raw + suffix)
                info = tk.info
                if not (info.get("longName") or info.get("shortName")):
                    continue
                roe       = round((info.get("returnOnEquity") or 0) * 100, 1)
                de        = info.get("debtToEquity") or None
                per       = round(info.get("trailingPE") or 0, 1)
                pb        = round(info.get("priceToBook") or 0, 1)
                op_margin = round((info.get("operatingMargins") or 0) * 100, 1)
                div_yield = round((info.get("dividendYield") or 0) * 100, 2)
                rev_growth = round((info.get("revenueGrowth") or 0) * 100, 1)
                try:
                    cf = tk.cashflow
                    ocf_row = cf[cf.index.str.contains("Operating Cash Flow", case=False)]
                    if not ocf_row.empty and ocf_row.shape[1] >= 2:
                        ocf_cur  = ocf_row.iloc[0, 0]
                        ocf_prev = ocf_row.iloc[0, 1]
                        ocf_chg  = round((ocf_cur - ocf_prev) / abs(ocf_prev) * 100, 1) if ocf_prev else None
                    else:
                        ocf_chg = None
                except Exception:
                    ocf_chg = None
                rows.append({
                    "종목명":         info.get("longName") or name,
                    "종목코드":       ticker_raw,
                    "경쟁 근거":      p.get("reason", ""),
                    "ROE(%)":         roe if roe else None,
                    "부채비율(%)":    round(de, 1) if de else None,
                    "영업이익률(%)":  op_margin if op_margin else None,
                    "배당수익률(%)":  div_yield if div_yield else None,
                    "매출성장률(%)":  rev_growth if rev_growth else None,
                    "영업CF증감(%)":  ocf_chg,
                    "PER(배)":        per if per else None,
                    "PBR(배)":        pb if pb else None,
                })
                break
            except Exception:
                continue
    return pd.DataFrame(rows) if rows else pd.DataFrame()



def _render_peer_table_and_charts(all_df: pd.DataFrame, target_name: str) -> None:
    """피어 비교 테이블과 차트를 그린다."""
    peers_df = all_df[~all_df["종목명"].isin([target_name, "📊 피어 평균"])]

    # ── 테이블 표시 ──
    st.dataframe(
        all_df.style.apply(
            lambda row: ["background-color: #1e3a5f; font-weight: bold;" if row["종목명"] == target_name
                         else ("background-color: #2a2a2a;" if row["종목명"] == "📊 피어 평균" else "")
                         for _ in row],
            axis=1,
        ),
        use_container_width=True,
        hide_index=True,
    )

    # ── ROE 막대 차트 ──
    chart_df = all_df[all_df["종목명"] != "📊 피어 평균"][["종목명", "ROE(%)"]].dropna()
    if not chart_df.empty:
        st.markdown("**ROE 비교**")
        st.bar_chart(chart_df.set_index("종목명")["ROE(%)"])

    # ── 영업이익률 막대 차트 ──
    chart_df2 = all_df[all_df["종목명"] != "📊 피어 평균"][["종목명", "영업이익률(%)"]].dropna()
    if not chart_df2.empty:
        st.markdown("**영업이익률 비교**")
        st.bar_chart(chart_df2.set_index("종목명")["영업이익률(%)"])

    st.caption(f"피어 그룹 {len(peers_df)}개 유효 | 분석 대상({target_name})의 ROE·부채비율은 DART 기준, 나머지는 yfinance")
