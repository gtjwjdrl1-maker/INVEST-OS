from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

MODULE_ID = "m1_4_nps_tracker"
MODULE_META = {
    "title": "국민연금 지분변동 트래커",
    "step": 1,
    "icon": "🏛️",
    "default_visible": True,
    "description": "국민연금 대량보유보고서 추적 — 매집 종목 자동 감지",
}

_DART_ENDPOINT = "https://opendart.fss.or.kr/api/list.json"
_DART_LINK     = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
_CACHE_TTL     = 1800  # 30분

_CORP_CLS_MAP = {"KOSPI": "Y", "KOSDAQ": "K"}
_DATA_DIR        = Path(__file__).parent.parent / "data"
_ANNOTATION_FILE = _DATA_DIR / "nps_annotations.json"

_PURPOSE_OPTIONS: list[tuple[str, str, str]] = [
    ("🆕 신규진입",  "신규진입",         "#16a34a"),
    ("📈 추가매수",  "추가매수",         "#2563eb"),
    ("🔥 일반투자↑", "일반투자 목적변경", "#dc2626"),
    ("📉 단순투자↓", "단순투자 목적변경", "#6b7280"),
    ("📝 기타",     "기타",            "#92400e"),
]

_DEMO_DATA = [
    {"rcept_dt": "20240610", "corp_name": "삼성전자",      "rcept_no": "20240610000001",
     "report_nm": "주식등의대량보유상황보고서(약식)", "flr_nm": "국민연금공단", "corp_cls": "Y"},
    {"rcept_dt": "20240605", "corp_name": "SK하이닉스",     "rcept_no": "20240605000002",
     "report_nm": "주식등의대량보유상황보고서(약식)", "flr_nm": "국민연금공단", "corp_cls": "Y"},
    {"rcept_dt": "20240601", "corp_name": "LG에너지솔루션",  "rcept_no": "20240601000003",
     "report_nm": "주식등의대량보유상황보고서(약식)", "flr_nm": "국민연금공단", "corp_cls": "Y"},
]


# ── 어노테이션 I/O ────────────────────────────────────────────────────────────

def _load_annotations() -> dict[str, dict]:
    if not _ANNOTATION_FILE.exists():
        return {}
    try:
        return json.loads(_ANNOTATION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_annotation(
    rcept_no: str, corp_name: str, rcept_dt: str, report_nm: str,
    purpose: str | None = None,
    obligation_date: str | None = None,
) -> None:
    _DATA_DIR.mkdir(exist_ok=True)
    annotations = _load_annotations()
    existing = annotations.get(rcept_no, {})
    annotations[rcept_no] = {
        "corp_name":       corp_name,
        "rcept_dt":        rcept_dt,
        "report_nm":       report_nm,
        "purpose":         purpose         if purpose         is not None else existing.get("purpose", ""),
        "obligation_date": obligation_date if obligation_date is not None else existing.get("obligation_date", ""),
        "saved_at":        datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    _ANNOTATION_FILE.write_text(
        json.dumps(annotations, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _delete_annotation(rcept_no: str) -> None:
    annotations = _load_annotations()
    annotations.pop(rcept_no, None)
    _ANNOTATION_FILE.write_text(
        json.dumps(annotations, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _on_date_change(rcept_no: str, corp_name: str, rcept_dt: str, report_nm: str) -> None:
    new_date = st.session_state.get(f"m1_4_obl_{rcept_no}")
    _save_annotation(
        rcept_no, corp_name, rcept_dt, report_nm,
        obligation_date=str(new_date) if new_date else "",
    )


# ── DART API ──────────────────────────────────────────────────────────────────

def _dart_api_key() -> str | None:
    return os.getenv("DART_API_KEY") or os.getenv("dart_api_key")


_PARALLEL_WORKERS = 5   # 동시 요청 수 (DART 서버 부하 고려)


def _fetch_page(corp_cls: str, page_no: int, begin_de: str, end_de: str,
                api_key: str) -> dict:
    """단일 페이지 조회 — ThreadPoolExecutor 워커에서 호출."""
    params = {
        "crtfc_key":  api_key,
        "corp_cls":   corp_cls,
        "pblntf_ty":  "D",
        "bgn_de":     begin_de,
        "end_de":     end_de,
        "page_no":    page_no,
        "page_count": 100,
    }
    resp = requests.get(_DART_ENDPOINT, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _fetch_dart(
    corp_cls_list: tuple[str, ...],
    begin_de: str,
    end_de: str,
    api_key: str,
    progress_bar,
    status_text,
) -> tuple[list[dict], str | None]:
    """1페이지 선조회로 총 페이지 파악 → 나머지를 병렬 요청."""
    all_items: list[dict] = []
    error_msg: str | None = None
    n_cls = len(corp_cls_list)
    lock = threading.Lock()

    for cls_idx, corp_cls in enumerate(corp_cls_list):
        mkt_label = "KOSPI" if corp_cls == "Y" else "KOSDAQ"

        # ── 1페이지 선조회: total_page 확인 ──────────────────────────────
        try:
            first = _fetch_page(corp_cls, 1, begin_de, end_de, api_key)
        except requests.RequestException as e:
            error_msg = f"DART 서버 연결 실패: {e}"
            break

        status = first.get("status")
        if status == "013":
            continue          # 해당 시장 데이터 없음
        if status != "000":
            error_msg = f"DART API 오류: {first.get('message', '알 수 없는 오류')}"
            break

        total_page = max(int(first.get("total_page", 1)), 1)
        with lock:
            all_items.extend(first.get("list", []))
        completed = 1

        def _update_progress():
            nps = sum(
                1 for i in all_items
                if "약식" in i.get("report_nm", "") and "국민연금" in i.get("flr_nm", "")
            )
            frac = (cls_idx + completed / total_page) / n_cls
            progress_bar.progress(min(frac, 0.99))
            status_text.caption(
                f"📡 {mkt_label} {completed} / {total_page} 페이지 완료"
                f" | 국민연금 약식 {nps}건 발견"
            )

        _update_progress()

        if total_page == 1:
            continue

        # ── 나머지 페이지 병렬 요청 ───────────────────────────────────────
        futures = {}
        with ThreadPoolExecutor(max_workers=_PARALLEL_WORKERS) as executor:
            for page_no in range(2, total_page + 1):
                fut = executor.submit(
                    _fetch_page, corp_cls, page_no, begin_de, end_de, api_key
                )
                futures[fut] = page_no

            for fut in as_completed(futures):
                try:
                    data = fut.result()
                    if data.get("status") == "000":
                        with lock:
                            all_items.extend(data.get("list", []))
                except requests.RequestException as e:
                    error_msg = f"페이지 조회 실패: {e}"

                completed += 1
                _update_progress()

        if error_msg:
            break

    return all_items, error_msg


def _filter_nps(items: list[dict]) -> list[dict]:
    return [
        item for item in items
        if "대량보유" in item.get("report_nm", "")
        and "약식"   in item.get("report_nm", "")
        and "국민연금" in item.get("flr_nm", "")
    ]


# ── UI 헬퍼 ──────────────────────────────────────────────────────────────────

def _fmt_date(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:]}" if len(s) == 8 else s


def _purpose_badge(purpose: str) -> str:
    color = next((c for _, v, c in _PURPOSE_OPTIONS if v == purpose), "#374151")
    return (
        f'<span style="background:{color};color:#fff;padding:1px 8px;'
        f'border-radius:10px;font-size:11px;font-weight:700">{purpose}</span>'
    )


def _build_table(items: list[dict], annotations: dict) -> pd.DataFrame:
    rows = []
    for item in items:
        rno = item.get("rcept_no", "")
        ann = annotations.get(rno, {})
        rows.append({
            "공시일":       _fmt_date(item.get("rcept_dt", "")),
            "종목명":       item.get("corp_name", ""),
            "보고의무일":   ann.get("obligation_date", "—"),
            "보유목적기록": ann.get("purpose", "—"),
            "기록일시":     ann.get("saved_at", "—"),
            "_rcept_no":   rno,
            "_corp_name":  item.get("corp_name", ""),
            "_rcept_dt":   item.get("rcept_dt", ""),
            "_report_nm":  item.get("report_nm", ""),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("공시일", ascending=False).reset_index(drop=True)
    return df


def _range_warning(start: date, end: date) -> None:
    days = (end - start).days
    if days > 730:
        st.warning(
            f"⚠️ {days}일 범위 조회입니다. "
            "전체 지분공시를 페이지별로 받아야 해서 **5~10분** 소요될 수 있습니다. "
            "조회 후 결과는 30분간 캐시됩니다."
        )
    elif days > 365:
        st.info(
            f"ℹ️ {days}일 범위 조회 — **2~4분** 소요 예상. 완료 후 캐시 저장됩니다."
        )
    elif days > 180:
        st.info(f"ℹ️ {days}일 범위 조회 — **1~2분** 소요 예상.")


# ── 메인 렌더 ─────────────────────────────────────────────────────────────────

def render(state) -> None:
    st.markdown(
        '<div class="inv-card"><div class="inv-card-title">🏛️ 국민연금 지분변동 트래커</div>',
        unsafe_allow_html=True,
    )

    api_key = _dart_api_key()
    if not api_key:
        st.warning("⚠️ DART API 키 없음 — 데모 데이터 표시 중. `.env`에 `DART_API_KEY`를 설정하세요.")

    # ── 조건 설정 ──────────────────────────────────────────────────────────
    c_s, c_e, c_mkt, c_btn = st.columns([1.5, 1.5, 2.5, 1])
    with c_s:
        start_date = st.date_input(
            "시작일",
            value=date.today() - timedelta(days=90),
            min_value=date(2000, 1, 1),
            max_value=date.today(),
            key="m1_4_start",
        )
    with c_e:
        end_date = st.date_input(
            "종료일",
            value=date.today(),
            min_value=date(2000, 1, 1),
            max_value=date.today(),
            key="m1_4_end",
        )
    with c_mkt:
        markets = st.multiselect(
            "시장 구분", ["KOSPI", "KOSDAQ"],
            default=["KOSPI"], key="m1_4_markets",
        )
    with c_btn:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        do_query = st.button("🔄 공시 조회", key="m1_4_query", use_container_width=True)

    if start_date > end_date:
        st.error("시작일이 종료일보다 늦습니다.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if not markets:
        st.warning("시장 구분을 하나 이상 선택하세요.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    begin_de = start_date.strftime("%Y%m%d")
    end_de   = end_date.strftime("%Y%m%d")

    # ── 기간 경고 ──────────────────────────────────────────────────────────
    _range_warning(start_date, end_date)

    # ── 캐시 ──────────────────────────────────────────────────────────────
    CACHE_KEY   = "m1_4_items"
    CACHE_TS    = "m1_4_ts"
    CACHE_PARAM = "m1_4_params"
    cache_params = (tuple(sorted(markets)), begin_de, end_de)

    cache_hit = (
        st.session_state.get(CACHE_KEY) is not None
        and not do_query
        and (time.time() - st.session_state.get(CACHE_TS, 0)) < _CACHE_TTL
        and st.session_state.get(CACHE_PARAM) == cache_params
    )

    items: list[dict] = []
    error_msg: str | None = None
    using_demo = False

    if not api_key:
        items = list(_DEMO_DATA)
        using_demo = True

    elif cache_hit:
        items = st.session_state[CACHE_KEY]
        elapsed = int(time.time() - st.session_state[CACHE_TS])
        st.caption(
            f"📦 캐시 ({int((_CACHE_TTL - elapsed) / 60)}분 후 만료) "
            f"— {start_date} ~ {end_date} / {', '.join(markets)}"
        )

    else:
        corp_cls_tuple = tuple(_CORP_CLS_MAP[m] for m in markets if m in _CORP_CLS_MAP)

        progress_bar = st.progress(0, text="조회 준비 중…")
        status_text  = st.empty()

        raw_items, error_msg = _fetch_dart(
            corp_cls_tuple, begin_de, end_de, api_key, progress_bar, status_text
        )

        progress_bar.empty()
        status_text.empty()

        if not error_msg:
            items = _filter_nps(raw_items)
            st.session_state.update({
                CACHE_KEY:   items,
                CACHE_TS:    time.time(),
                CACHE_PARAM: cache_params,
            })

    if error_msg:
        st.error(error_msg)
        st.markdown("[📋 DART 공시 포털에서 직접 확인](https://dart.fss.or.kr)")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if using_demo:
        st.info("📊 데모 데이터 표시 중")

    # ── 탭 ────────────────────────────────────────────────────────────────
    tab_result, tab_history = st.tabs(["📋 조회 결과", "📚 기록 이력"])

    # ════════════════════════════════════════════════════════════════════
    # 탭 1 — 조회 결과 + 보유목적 기록 패널
    # ════════════════════════════════════════════════════════════════════
    with tab_result:
        if not items:
            st.info("조회 기간 내 국민연금공단 약식 대량보유보고서가 없습니다.")
        else:
            annotations = _load_annotations()
            df = _build_table(items, annotations)

            st.markdown(
                f"**총 {len(df)}건** — 주식등의대량보유상황보고서(약식) / 국민연금공단 "
                f"({start_date} ~ {end_date})"
            )
            display_df = df[["공시일", "종목명", "보고의무일", "보유목적기록", "기록일시"]]
            st.dataframe(display_df, use_container_width=True,
                         height=min(420, 58 + 35 * len(display_df)))

            # 원문 링크
            st.markdown("**공시 원문 바로가기**")
            link_cols = st.columns(3)
            for i, row in df.iterrows():
                with link_cols[i % 3]:
                    st.link_button(
                        f"📄 {row['종목명']} {row['공시일']}",
                        _DART_LINK.format(rcept_no=row["_rcept_no"]),
                        use_container_width=True,
                    )

            # ── 보유목적 기록 패널 (컴팩트) ───────────────────────────────
            st.markdown("---")
            st.markdown("##### 📌 보유목적 기록")
            st.caption("원문 확인 후 보고의무일 입력 + 사유 클릭으로 저장. 변경 시 덮어씁니다.")

            # 헤더
            h0, h1, h2, h3, h4 = st.columns([2, 1.5, 4, 1.2, 0.4])
            for col, label in zip(
                [h0, h1, h2, h3],
                ["종목명 (공시일)", "보고의무일", "사유 선택", "현재 기록"],
            ):
                col.markdown(
                    f'<span style="font-size:11px;color:#9ca3af">{label}</span>',
                    unsafe_allow_html=True,
                )
            st.markdown('<hr style="margin:4px 0;border-color:#374151">', unsafe_allow_html=True)

            for _, row in df.iterrows():
                rno       = row["_rcept_no"]
                corp_name = row["_corp_name"]
                rcept_dt  = row["_rcept_dt"]
                report_nm = row["_report_nm"]
                ann       = annotations.get(rno, {})
                cur_p     = ann.get("purpose", "")
                cur_obl   = ann.get("obligation_date", "")

                c0, c1, c2, c3, c4 = st.columns([2, 1.5, 4, 1.2, 0.4])

                c0.markdown(
                    f'<span style="font-weight:600;font-size:13px">{corp_name}</span><br>'
                    f'<span style="font-size:11px;color:#9ca3af">{_fmt_date(rcept_dt)}</span>',
                    unsafe_allow_html=True,
                )

                init_date: date | None = None
                if cur_obl:
                    try:
                        init_date = date.fromisoformat(cur_obl)
                    except ValueError:
                        pass
                c1.date_input(
                    "", value=init_date,
                    key=f"m1_4_obl_{rno}",
                    label_visibility="collapsed",
                    on_change=_on_date_change,
                    args=(rno, corp_name, rcept_dt, report_nm),
                )

                with c2:
                    b_cols = st.columns(5)
                    for bc, (label, value, _) in zip(b_cols, _PURPOSE_OPTIONS):
                        is_sel = cur_p == value
                        if bc.button(
                            f"✓{label}" if is_sel else label,
                            key=f"m1_4_ann_{rno}_{value}",
                            type="primary" if is_sel else "secondary",
                            use_container_width=True,
                        ):
                            _save_annotation(rno, corp_name, rcept_dt, report_nm, purpose=value)
                            st.rerun()

                with c3:
                    if cur_p:
                        st.markdown(_purpose_badge(cur_p), unsafe_allow_html=True)
                    else:
                        st.markdown(
                            '<span style="color:#6b7280;font-size:11px">미기록</span>',
                            unsafe_allow_html=True,
                        )

                with c4:
                    if cur_p or cur_obl:
                        if st.button("🗑️", key=f"m1_4_del_{rno}", help="기록 삭제"):
                            _delete_annotation(rno)
                            st.rerun()

                st.markdown('<hr style="margin:2px 0;border-color:#1f2937">', unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════════════════
    # 탭 2 — 기록 이력
    # ════════════════════════════════════════════════════════════════════
    with tab_history:
        annotations = _load_annotations()
        if not annotations:
            st.info("저장된 기록이 없습니다. 조회 결과 탭에서 사유를 기록하세요.")
        else:
            hist_rows = []
            for rno, ann in annotations.items():
                hist_rows.append({
                    "기록일시":   ann.get("saved_at", "—"),
                    "종목명":    ann.get("corp_name", ""),
                    "공시일":    _fmt_date(ann.get("rcept_dt", "")),
                    "보고의무일": ann.get("obligation_date", "—"),
                    "보유목적":  ann.get("purpose", "—"),
                    "_rcept_no": rno,
                })
            hist_df = (
                pd.DataFrame(hist_rows)
                .sort_values("기록일시", ascending=False)
                .reset_index(drop=True)
            )

            f_col, _ = st.columns([2, 4])
            purposes = ["전체"] + sorted(hist_df["보유목적"].unique().tolist())
            sel = f_col.selectbox("보유목적 필터", purposes, key="m1_4_hist_filter")
            if sel != "전체":
                hist_df = hist_df[hist_df["보유목적"] == sel].reset_index(drop=True)

            st.markdown(f"**{len(hist_df)}건**")
            show_cols = ["기록일시", "종목명", "공시일", "보고의무일", "보유목적"]
            st.dataframe(hist_df[show_cols], use_container_width=True,
                         height=min(500, 58 + 35 * len(hist_df)))

            st.markdown("**원문 링크 / 삭제**")
            for _, row in hist_df.iterrows():
                rno = row["_rcept_no"]
                la, lb, lc = st.columns([3.5, 1.5, 0.5])
                la.markdown(
                    f'**{row["종목명"]}** '
                    f'<span style="color:#9ca3af;font-size:11px">{row["공시일"]}</span> '
                    f'&nbsp;{_purpose_badge(row["보유목적"])}',
                    unsafe_allow_html=True,
                )
                lb.link_button("📄 DART 원문", _DART_LINK.format(rcept_no=rno), use_container_width=True)
                if lc.button("🗑️", key=f"m1_4_hdel_{rno}", help="삭제"):
                    _delete_annotation(rno)
                    st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
