"""
M-2-1 · 주요 공시 모니터 (m2_1_dart_cutoff)

DART 최근 7일 공시를 중요도별 분류 + 종목 감시 + 원문 바로가기.
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

import requests
import streamlit as st

MODULE_ID = "m2_1_dart_cutoff"
MODULE_META = {
    "title": "주요 공시 모니터",
    "step": 2,
    "icon": "📋",
    "default_visible": True,
    "description": "DART 최근 공시 · 중요도 분류 · 종목 감시 · 원문 바로가기",
}

_DART_LIST  = "https://opendart.fss.or.kr/api/list.json"
_DART_LINK  = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
_CACHE_TTL  = 1800   # 30분
_DATA_DIR   = Path(__file__).parent.parent / "data"
_WL_FILE    = _DATA_DIR / "dart_watchlist.json"

# ── 중요도 분류 키워드 (DART report_nm 기준) ─────────────────────────
_CRITICAL = [
    "횡령", "배임", "조회공시", "불성실공시", "관리종목", "상장폐지",
    "영업정지", "부도", "회생절차",
]
_WARNING = [
    "전환사채", "신주인수권부사채", "유상증자", "무상감자",
    "최대주주변경", "자기주식처분", "임원ㆍ주요주주", "대표이사변경",
]
_INFO = [
    "분기보고서", "반기보고서", "사업보고서",
    "주요사항보고서", "공정공시", "자기주식취득",
]

_CLS_LABEL  = {"Y": "KOSPI", "K": "KOSDAQ", "N": "KONEX", "E": "기타"}
_GRADE_ORDER = {"긴급": 0, "주의": 1, "참고": 2, "기타": 3}

_DEMO_DATA = [
    {"corp_name": "데모전자",   "report_nm": "주요사항보고서(전환사채권발행결정)",
     "rcept_no": "00000001", "rcept_dt": datetime.date.today().strftime("%Y%m%d"), "corp_cls": "Y"},
    {"corp_name": "데모케미칼", "report_nm": "사업보고서 (2025.12)",
     "rcept_no": "00000002", "rcept_dt": datetime.date.today().strftime("%Y%m%d"), "corp_cls": "K"},
    {"corp_name": "데모바이오", "report_nm": "조회공시요구(풍문또는보도)",
     "rcept_no": "00000003", "rcept_dt": datetime.date.today().strftime("%Y%m%d"), "corp_cls": "Y"},
]


# ════════════════════════════════════════════════════════════════════
# 감시 종목 목록 (JSON 파일 영속 저장)
# ════════════════════════════════════════════════════════════════════

def _load_watchlist() -> dict[str, list[str]]:
    try:
        _DATA_DIR.mkdir(exist_ok=True)
        if _WL_FILE.exists():
            return json.loads(_WL_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"holdings": [], "candidates": []}


def _save_watchlist(wl: dict[str, list[str]]) -> None:
    try:
        _DATA_DIR.mkdir(exist_ok=True)
        _WL_FILE.write_text(json.dumps(wl, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════
# 데이터 수집 · 분류
# ════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=_CACHE_TTL, show_spinner=False)
def _fetch_dart(
    api_key: str, corp_cls: str, begin_de: str, end_de: str, max_pages: int = 5
) -> tuple[list[dict], str]:
    """날짜 범위 DART 공시 수집. max_pages×100건 상한. 반환: (목록, 에러)."""
    items: list[dict] = []
    for page in range(1, max_pages + 1):
        try:
            resp = requests.get(
                _DART_LIST,
                params={
                    "crtfc_key":  api_key,
                    "corp_cls":   corp_cls,
                    "bgn_de":     begin_de,
                    "end_de":     end_de,
                    "page_no":    page,
                    "page_count": 100,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "")
            if status != "000":
                if status != "013":
                    return [], f"DART API 오류(status={status}): {data.get('message', '')}"
                break
            batch = data.get("list", [])
            items.extend(batch)
            if len(batch) < 100:   # 마지막 페이지
                break
        except Exception as e:
            return [], f"네트워크 오류: {e}"
    return items, ""


def _classify(report_nm: str) -> tuple[str, str]:
    """공시명 → (등급, 아이콘)."""
    for kw in _CRITICAL:
        if kw in report_nm:
            return "긴급", "🔴"
    for kw in _WARNING:
        if kw in report_nm:
            return "주의", "🟡"
    for kw in _INFO:
        if kw in report_nm:
            return "참고", "🟢"
    return "기타", "🔵"


def _enrich(raw_items: list[dict]) -> list[dict]:
    result = []
    for item in raw_items:
        grade, icon = _classify(item.get("report_nm", ""))
        result.append({
            **item,
            "grade":          grade,
            "icon":           icon,
            "corp_cls_label": _CLS_LABEL.get(item.get("corp_cls", ""), "기타"),
        })
    return result


# ════════════════════════════════════════════════════════════════════
# 렌더링
# ════════════════════════════════════════════════════════════════════

def render(state) -> None:
    api_key = os.environ.get("DART_API_KEY", "")

    # ── session_state 초기화 ──────────────────────────────────────────
    if "dart_items" not in st.session_state:
        st.session_state["dart_items"] = []   # enriched 공시 목록
    if "dart_fetched_label" not in st.session_state:
        st.session_state["dart_fetched_label"] = ""  # 조회 완료 표시용

    st.subheader("📋 주요 공시 모니터", divider="gray")

    # ── 날짜 범위 ─────────────────────────────────────────────────────
    today = datetime.date.today()
    default_from = today - datetime.timedelta(days=7)

    row1a, row1b, row1c, row1d = st.columns([2, 2, 1, 1])
    with row1a:
        date_from = st.date_input("시작일", value=default_from, key="dart_from",
                                  max_value=today)
    with row1b:
        date_to = st.date_input("종료일", value=today, key="dart_to",
                                min_value=date_from, max_value=today)
    with row1c:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        search_btn = st.button("🔍 공시 조회", type="primary", use_container_width=True)
    with row1d:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        if st.button("🔄 초기화", use_container_width=True):
            st.cache_data.clear()
            st.session_state["dart_items"] = []
            st.session_state["dart_fetched_label"] = ""
            st.rerun()

    begin_de = date_from.strftime("%Y%m%d")
    end_de   = date_to.strftime("%Y%m%d")

    # ── 시장 · 중요도 필터 ───────────────────────────────────────────
    row2a, row2b = st.columns(2)
    with row2a:
        market_sel = st.multiselect(
            "시장", ["KOSPI", "KOSDAQ", "KONEX", "기타"],
            default=["KOSPI", "KOSDAQ"], key="dart_market",
        )
    with row2b:
        grade_sel = st.multiselect(
            "중요도", ["🔴 긴급", "🟡 주의", "🟢 참고", "🔵 기타"],
            default=["🔴 긴급", "🟡 주의", "🟢 참고"], key="dart_grade",
        )

    grade_filter = {g.split(" ", 1)[1] for g in grade_sel}
    label_to_cls = {v: k for k, v in _CLS_LABEL.items()}
    cls_filter   = {label_to_cls[m] for m in market_sel if m in label_to_cls}

    # ── 종목 검색 + 감시 목록 ────────────────────────────────────────
    wl = _load_watchlist()

    row3a, row3b, row3c = st.columns([3, 1, 1])
    with row3a:
        corp_search = st.text_input("회사명 검색 (실시간 필터)",
                                    placeholder="예: 삼성전자  (비우면 전체)",
                                    key="dart_corp_search")
    with row3b:
        use_holdings   = st.checkbox(f"보유종목 ({len(wl['holdings'])})",
                                     key="dart_use_holdings")
    with row3c:
        use_candidates = st.checkbox(f"검토중 종목 ({len(wl['candidates'])})",
                                     key="dart_use_candidates")

    # ── 중요도 분류 기준 안내 ─────────────────────────────────────────
    with st.expander("ℹ️ 중요도 분류 기준 보기"):
        st.markdown("""
| 등급 | 아이콘 | 해당 공시 유형 | 예시 |
|------|--------|--------------|------|
| **긴급** | 🔴 | 즉시 확인이 필요한 중대 사안 | 횡령·배임, 조회공시, 불성실공시법인 지정, 관리종목 편입, 상장폐지, 영업정지, 부도, 회생절차 |
| **주의** | 🟡 | 주가·지배구조에 영향을 줄 수 있는 사안 | 전환사채·신주인수권부사채 발행, 유상증자, 무상감자, 최대주주 변경, 자기주식 처분, 임원·주요주주 주식 거래, 대표이사 변경 |
| **참고** | 🟢 | 정기·수시 공시로 내용 확인이 권장되는 사안 | 분기·반기·사업보고서, 주요사항보고서, 공정공시(실적·계획), 자기주식 취득 |
| **기타** | 🔵 | 위 3가지에 해당하지 않는 일반 공시 | 주식 대량보유 보고, 증권발행 실적, 투자설명서 등 |
""")
        st.caption("분류 기준은 공시명(report_nm) 키워드 매칭 방식입니다. 동일 공시도 정정 여부에 따라 등급이 달라질 수 있습니다.")

    # ── 감시 종목 목록 관리 ──────────────────────────────────────────
    with st.expander("⚙️ 감시 종목 목록 관리"):
        tab_h, tab_c = st.tabs(["📂 보유종목", "🔍 검토중 종목"])
        with tab_h:
            _render_wl_editor(wl, "holdings", "보유종목")
        with tab_c:
            _render_wl_editor(wl, "candidates", "검토중 종목")

    # ── 공시 조회 버튼 클릭 시 데이터 수집 ─────────────────────────
    searching_corp_at_fetch = corp_search.strip()

    if search_btn:
        if not api_key:
            st.warning("**DART_API_KEY 없음** — `.env`에 추가하세요.", icon="⚠️")
            st.session_state["dart_items"] = _enrich(_DEMO_DATA)
            st.session_state["dart_fetched_label"] = f"데모 데이터 ({begin_de}~{end_de})"
        elif not cls_filter:
            st.warning("시장을 하나 이상 선택하세요.", icon="⚠️")
        else:
            # 회사명 검색이면 더 많은 페이지 수집 (DART는 최신순 정렬 — 대형주는 뒤에 있을 수 있음)
            pages = 20 if searching_corp_at_fetch else 5
            label_mode = f"회사명 '{searching_corp_at_fetch}' 전체 조회" if searching_corp_at_fetch else "최신 공시"

            all_raw: list[dict] = []
            errors: list[str] = []
            with st.spinner(f"DART {label_mode} 수집 중… ({begin_de} ~ {end_de})"):
                for cls in cls_filter:
                    batch, err = _fetch_dart(api_key, cls, begin_de, end_de, max_pages=pages)
                    if err:
                        errors.append(f"{_CLS_LABEL.get(cls, cls)}: {err}")
                    all_raw.extend(batch)

            if errors:
                with st.expander("⚠️ 수집 오류 상세"):
                    for e in errors:
                        st.code(e, language="")

            st.session_state["dart_items"] = _enrich(all_raw)
            label_suffix = f" · '{searching_corp_at_fetch}' 검색" if searching_corp_at_fetch else ""
            st.session_state["dart_fetched_label"] = (
                f"{begin_de}~{end_de} 조회 완료 {len(all_raw)}건{label_suffix}"
            )

    # ── 결과 표시 (session_state 기반 — 버튼 클릭 후에만 존재) ────────
    cached = st.session_state["dart_items"]
    if not cached:
        st.info("🔍 날짜·시장을 설정하고 **공시 조회** 버튼을 눌러주세요.", icon="ℹ️")
        return

    if st.session_state.get("dart_fetched_label"):
        st.caption(f"📅 {st.session_state['dart_fetched_label']}")

    _render_list(cached, grade_filter, corp_search, wl, use_holdings, use_candidates)


def _render_wl_editor(wl: dict, key: str, label: str) -> None:
    """보유종목 / 검토중 종목 추가·삭제 UI."""
    current: list[str] = wl.get(key, [])

    # 추가
    add_col, btn_col = st.columns([4, 1])
    with add_col:
        new_name = st.text_input(f"{label} 추가", placeholder="회사명 입력",
                                 key=f"wl_add_{key}", label_visibility="collapsed")
    with btn_col:
        if st.button("추가", key=f"wl_btn_{key}") and new_name.strip():
            name = new_name.strip()
            if name not in current:
                current.append(name)
                wl[key] = current
                _save_watchlist(wl)
                st.rerun()

    # 목록 표시 + 삭제
    if not current:
        st.caption("등록된 종목이 없습니다.")
        return

    for i, name in enumerate(current):
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"• {name}")
        if c2.button("삭제", key=f"wl_del_{key}_{i}"):
            current.pop(i)
            wl[key] = current
            _save_watchlist(wl)
            st.rerun()


def _render_list(
    items: list[dict],
    grade_filter: set[str],
    corp_search: str,
    wl: dict,
    use_holdings: bool,
    use_candidates: bool,
) -> None:
    """필터 적용 후 공시 목록 표시."""

    # 회사명 필터 결정
    name_filter: set[str] = set()
    if use_holdings:
        name_filter.update(wl.get("holdings", []))
    if use_candidates:
        name_filter.update(wl.get("candidates", []))

    searching_corp = corp_search.strip()

    def _match(item: dict) -> bool:
        corp = item.get("corp_name", "")
        # 회사명 검색 중이면 해당 회사의 모든 등급을 보여준다
        if not searching_corp and item["grade"] not in grade_filter:
            return False
        if searching_corp and searching_corp not in corp:
            return False
        if name_filter and not searching_corp and corp not in name_filter:
            return False
        return True

    filtered = [it for it in items if _match(it)]

    # 요약 카운터
    grade_counts: dict[str, int] = {"긴급": 0, "주의": 0, "참고": 0, "기타": 0}
    for it in items:
        grade_counts[it["grade"]] += 1

    st.caption(
        f"수집 {len(items)}건  ·  "
        f"🔴 {grade_counts['긴급']}  🟡 {grade_counts['주의']}  "
        f"🟢 {grade_counts['참고']}  🔵 {grade_counts['기타']}"
        f"  →  필터 후 **{len(filtered)}건**"
    )

    if not filtered:
        st.info("해당 조건의 공시가 없습니다.", icon="ℹ️")
        return

    # 중요도 → 날짜 순 정렬
    sorted_items = sorted(
        filtered,
        key=lambda x: (_GRADE_ORDER.get(x["grade"], 9), x.get("rcept_dt", "")),
    )

    for item in sorted_items:
        dt_fmt = item.get("rcept_dt", "")
        if len(dt_fmt) == 8:
            dt_fmt = f"{dt_fmt[:4]}-{dt_fmt[4:6]}-{dt_fmt[6:]}"
        with st.container():
            c1, c2 = st.columns([8, 2])
            c1.markdown(f"{item['icon']} **{item['corp_name']}** — {item['report_nm']}")
            c1.caption(f"{item['corp_cls_label']}  |  {dt_fmt}")
            c2.link_button(
                "📄 원문 보기",
                _DART_LINK.format(rcept_no=item["rcept_no"]),
                use_container_width=True,
            )
        st.divider()
