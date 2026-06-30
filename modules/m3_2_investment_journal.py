"""
M-3-2 · 종목 선택 근거 기록 (m3_2_investment_journal)

매수 근거·판단 일지를 날짜별로 기록하고 JSON 파일로 로컬 저장한다.
외부 API 의존성 없음.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path

import streamlit as st

MODULE_ID = "m3_2_investment_journal"
MODULE_META = {
    "title": "종목 선택 근거 기록",
    "step": 3,
    "icon": "📓",
    "default_visible": True,
    "description": "매수 근거·판단 일지를 날짜별로 기록하고 저장",
}

DATA_DIR = Path(__file__).parent.parent / "data"
JOURNAL_FILE = DATA_DIR / "investment_journal.json"


# ════════════════════════════════════════════════════════════════════
# 저장소 헬퍼
# ════════════════════════════════════════════════════════════════════

def _load() -> list[dict]:
    if not JOURNAL_FILE.exists():
        return []
    try:
        return json.loads(JOURNAL_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(records: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JOURNAL_FILE.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _add(record: dict) -> None:
    records = _load()
    records.append(record)
    _save(records)


def _update(record_id: str, updated: dict) -> None:
    records = _load()
    for i, r in enumerate(records):
        if r.get("id") == record_id:
            records[i] = updated
            break
    _save(records)


def _delete(record_id: str) -> None:
    records = [r for r in _load() if r.get("id") != record_id]
    _save(records)


# ════════════════════════════════════════════════════════════════════
# 입력 폼 (신규 작성 / 수정)
# ════════════════════════════════════════════════════════════════════

def _render_form(state) -> None:
    editing_id = st.session_state.get("journal_editing_id")
    editing_data: dict = st.session_state.get("journal_editing_data", {})

    form_title = "✏️ 기록 수정" if editing_id else "📝 새 기록 작성"

    with st.container(border=True):
        st.markdown(f"**{form_title}**")

        r1c1, r1c2, r1c3 = st.columns([3, 3, 2])
        with r1c1:
            default_date = (
                date.fromisoformat(editing_data.get("date", str(date.today())))
                if editing_data.get("date") else date.today()
            )
            entry_date = st.date_input("날짜", value=default_date, key="jf_date")
        with r1c2:
            company = st.text_input("회사명", value=editing_data.get("company", ""), key="jf_company")
        with r1c3:
            ticker = st.text_input("티커 / 종목코드 (선택)", value=editing_data.get("ticker", ""), key="jf_ticker")

        r2c1, r2c2, r2c3 = st.columns(3)
        with r2c1:
            amount = st.number_input(
                "매수금액 (원)", min_value=0, value=int(editing_data.get("amount", 0)),
                step=10000, key="jf_amount"
            )
        with r2c2:
            price = st.number_input(
                "매수가격 (주당, 선택)", min_value=0, value=int(editing_data.get("price", 0)),
                step=100, key="jf_price"
            )
        with r2c3:
            qty = st.number_input(
                "수량 (선택)", min_value=0, value=int(editing_data.get("qty", 0)),
                step=1, key="jf_qty"
            )

        reason = st.text_area(
            "근거 일지",
            value=editing_data.get("reason", ""),
            height=200,
            placeholder="매수 근거, AI 분석 결과 요약, 목표가, 매도 조건 등 자유롭게 작성",
            key="jf_reason",
        )

        bc1, bc2 = st.columns([2, 1])
        with bc1:
            save_clicked = st.button("💾 저장", type="primary", use_container_width=True, key="jf_save")
        with bc2:
            if editing_id and st.button("취소", use_container_width=True, key="jf_cancel"):
                st.session_state.pop("journal_editing_id", None)
                st.session_state.pop("journal_editing_data", None)
                st.rerun()

        if save_clicked:
            if not company.strip():
                st.warning("회사명을 입력하세요.")
                return

            record = {
                "id": editing_id or str(uuid.uuid4()),
                "date": str(entry_date),
                "company": company.strip(),
                "ticker": ticker.strip(),
                "amount": amount,
                "price": price if price > 0 else None,
                "qty": qty if qty > 0 else None,
                "reason": reason.strip(),
                "created_at": editing_data.get("created_at", datetime.now().isoformat(timespec="seconds")),
            }

            if editing_id:
                _update(editing_id, record)
                st.session_state.pop("journal_editing_id", None)
                st.session_state.pop("journal_editing_data", None)
                st.success("기록이 수정되었습니다.")
            else:
                _add(record)
                st.success("기록이 저장되었습니다.")

            st.rerun()


# ════════════════════════════════════════════════════════════════════
# 기록 목록
# ════════════════════════════════════════════════════════════════════

def _render_list() -> None:
    st.divider()
    st.markdown("**📋 저장된 기록**")

    fc1, fc2, fc3 = st.columns([3, 2, 2])
    with fc1:
        search = st.text_input("회사명 검색", placeholder="예: 삼양", key="jf_search", label_visibility="collapsed")
    with fc2:
        date_from = st.date_input("시작일", value=None, key="jf_date_from", label_visibility="collapsed")
    with fc3:
        date_to = st.date_input("종료일", value=None, key="jf_date_to", label_visibility="collapsed")

    records = _load()

    # 필터
    if search.strip():
        records = [r for r in records if search.strip() in r.get("company", "")]
    if date_from:
        records = [r for r in records if r.get("date", "") >= str(date_from)]
    if date_to:
        records = [r for r in records if r.get("date", "") <= str(date_to)]

    # 날짜 내림차순
    records = sorted(records, key=lambda r: r.get("date", ""), reverse=True)

    if not records:
        st.info("저장된 기록이 없습니다.", icon="📭")
        return

    for r in records:
        label = f"{r.get('date', '')} — {r.get('company', '')} ({r.get('amount', 0):,}원)"
        with st.expander(label):
            meta_parts = []
            if r.get("ticker"):
                meta_parts.append(f"티커: **{r['ticker']}**")
            if r.get("price"):
                meta_parts.append(f"매수가: **{r['price']:,}원**")
            if r.get("qty"):
                meta_parts.append(f"수량: **{r['qty']}주**")
            if meta_parts:
                st.markdown(" · ".join(meta_parts))

            if r.get("reason"):
                st.markdown(r["reason"])
            else:
                st.caption("(근거 없음)")

            ac1, ac2 = st.columns(2)
            with ac1:
                if st.button("✏️ 수정", key=f"edit_{r['id']}", use_container_width=True):
                    st.session_state["journal_editing_id"] = r["id"]
                    st.session_state["journal_editing_data"] = r
                    st.rerun()
            with ac2:
                with st.popover("🗑️ 삭제", use_container_width=True):
                    st.markdown("정말 삭제하시겠습니까?")
                    if st.button("삭제 확인", key=f"del_confirm_{r['id']}", type="primary"):
                        _delete(r["id"])
                        st.rerun()


# ════════════════════════════════════════════════════════════════════
# 렌더링 진입점
# ════════════════════════════════════════════════════════════════════

def render(state) -> None:
    st.subheader("📓 종목 선택 근거 기록", divider="gray")
    st.caption("매수 근거·AI 분석 요약·목표가·매도 조건을 날짜별로 기록합니다.")

    _render_form(state)
    _render_list()

    # 하단 안내 + 내보내기
    st.caption(f"📁 저장 위치: data/investment_journal.json")

    records = _load()
    if records:
        json_bytes = json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button(
            "📥 JSON 내보내기",
            data=json_bytes,
            file_name="investment_journal.json",
            mime="application/json",
        )
