from __future__ import annotations

import io
from datetime import date

import pandas as pd
import streamlit as st

MODULE_ID = "m1_3_ark_scanner"
MODULE_META = {
    "title": "ARK 카피트레이딩 스캐너",
    "step": 1,
    "icon": "🚀",
    "default_visible": True,
    "description": "ARK Invest 일일 편입 변동 추적 — 신규 편입·비중 급증 종목 포착",
}

_ARK_URLS: dict[str, str] = {
    "ARKK": "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv",
    "ARKW": "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS.csv",
    "ARKG": "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv",
    "ARKQ": "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_AUTONOMOUS_TECHNOLOGY_&_ROBOTICS_ETF_ARKQ_HOLDINGS.csv",
    "ARKF": "https://ark-funds.com/wp-content/uploads/funds-etf-csv/ARK_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS.csv",
}

_WEIGHT_THRESHOLD = 1.0  # 비중 변화 기준 (%p)


def _fetch_etf(name: str, url: str) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(url, skiprows=0)
        # ARK CSV 첫 줄이 date 행인 경우 처리
        if df.columns[0].lower().startswith("date") or "date" in df.columns[0].lower():
            pass
        # 컬럼 정규화
        df.columns = [c.strip().lower().replace(" ", "_").replace("($)", "").replace("(%)", "_pct") for c in df.columns]
        # 필요 컬럼 확인 및 rename
        col_map = {}
        for c in df.columns:
            if "company" in c:
                col_map[c] = "company"
            elif "ticker" in c:
                col_map[c] = "ticker"
            elif "weight" in c or "pct" in c:
                col_map[c] = "weight_pct"
            elif "market_value" in c or "market value" in c.replace("_", " "):
                col_map[c] = "market_value"
            elif "shares" in c:
                col_map[c] = "shares"
            elif c == "date":
                col_map[c] = "date"
            elif "fund" in c:
                col_map[c] = "fund"
            elif "cusip" in c:
                col_map[c] = "cusip"
        df = df.rename(columns=col_map)

        # 빈 행 제거
        if "ticker" in df.columns:
            df = df[df["ticker"].notna() & (df["ticker"].astype(str).str.strip() != "")]
        if "weight_pct" in df.columns:
            df["weight_pct"] = pd.to_numeric(df["weight_pct"], errors="coerce")
        if "market_value" in df.columns:
            df["market_value"] = pd.to_numeric(
                df["market_value"].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            )
        df["etf"] = name
        return df.reset_index(drop=True)
    except Exception as e:
        return None


def _load_all(selected: list[str]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    data: dict[str, pd.DataFrame] = {}
    errors: list[str] = []
    for name in selected:
        df = _fetch_etf(name, _ARK_URLS[name])
        if df is not None and not df.empty:
            data[name] = df
        else:
            errors.append(name)
    return data, errors


def _badge(text: str, color: str) -> str:
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:4px;font-size:11px;font-weight:700">{text}</span>'
    )


def _change_card(row: dict) -> str:
    sign = "+" if row["delta"] > 0 else ""
    badge = ""
    if row["kind"] == "new":
        badge = _badge("🆕 신규", "#dc2626")
    elif row["kind"] == "up":
        badge = _badge("📈 급증", "#ea580c")
    elif row["kind"] == "down":
        badge = _badge("📉 급감", "#6b7280")

    prev_str = f"{row['prev']:.2f}%" if row["prev"] is not None else "—"
    delta_color = "#dc2626" if row["delta"] > 0 else "#6b7280"

    return (
        f'<div style="border:1px solid #374151;border-radius:8px;padding:10px 14px;'
        f'margin:6px 0;background:#111827">'
        f'<div style="display:flex;justify-content:space-between;align-items:center">'
        f'<span style="font-weight:700;color:#f9fafb">{row["company"]} '
        f'<span style="color:#9ca3af;font-size:12px">({row["ticker"]})</span></span>'
        f'{badge}</div>'
        f'<div style="margin-top:6px;font-size:13px;color:#d1d5db">'
        f'ETF: <b>{row["etf"]}</b> &nbsp;|&nbsp; '
        f'현재: <b style="color:#60a5fa">{row["curr"]:.2f}%</b> &nbsp;|&nbsp; '
        f'전일: <b>{prev_str}</b> &nbsp;|&nbsp; '
        f'변화: <b style="color:{delta_color}">{sign}{row["delta"]:.2f}%p</b>'
        f'</div></div>'
    )


def _compute_changes(
    today_data: dict[str, pd.DataFrame],
    prev_data: dict[str, pd.DataFrame],
) -> list[dict]:
    changes: list[dict] = []
    for etf, df in today_data.items():
        if "ticker" not in df.columns or "weight_pct" not in df.columns:
            continue
        today_map = {
            str(r["ticker"]).strip(): r
            for _, r in df.iterrows()
            if pd.notna(r["ticker"])
        }
        prev_df = prev_data.get(etf)
        prev_map: dict[str, float] = {}
        if prev_df is not None and "ticker" in prev_df.columns and "weight_pct" in prev_df.columns:
            prev_map = {
                str(r["ticker"]).strip(): float(r["weight_pct"])
                for _, r in prev_df.iterrows()
                if pd.notna(r["ticker"]) and pd.notna(r["weight_pct"])
            }

        for ticker, row in today_map.items():
            curr_w = float(row["weight_pct"]) if pd.notna(row.get("weight_pct")) else None
            if curr_w is None:
                continue
            prev_w = prev_map.get(ticker)
            company = str(row.get("company", ticker))

            if prev_w is None:
                kind = "new"
                delta = curr_w
            else:
                delta = curr_w - prev_w
                if delta >= _WEIGHT_THRESHOLD:
                    kind = "up"
                elif delta <= -_WEIGHT_THRESHOLD:
                    kind = "down"
                else:
                    continue

            changes.append({
                "kind": kind,
                "etf": etf,
                "company": company,
                "ticker": ticker,
                "curr": curr_w,
                "prev": prev_w,
                "delta": delta,
            })

    # 정렬: 신규 → 급증 → 급감, 같은 종류면 delta 절댓값 내림차순
    order = {"new": 0, "up": 1, "down": 2}
    changes.sort(key=lambda x: (order[x["kind"]], -abs(x["delta"])))
    return changes


def render(state) -> None:
    st.markdown(
        '<div class="inv-card"><div class="inv-card-title">🚀 ARK 카피트레이딩 스캐너</div>',
        unsafe_allow_html=True,
    )

    # ── 컨트롤 영역 ──────────────────────────────────────────────────────
    col_sel, col_btn = st.columns([4, 1])
    with col_sel:
        selected = st.multiselect(
            "ETF 선택",
            options=list(_ARK_URLS.keys()),
            default=["ARKK"],
            key="m1_3_selected",
        )
    with col_btn:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        refresh = st.button("🔄 새로고침", key="m1_3_refresh", use_container_width=True)

    if not selected:
        st.warning("ETF를 하나 이상 선택하세요.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # ── 세션 상태 키 ─────────────────────────────────────────────────────
    TODAY_KEY = "m1_3_today_data"
    PREV_KEY = "m1_3_prev_data"
    DATE_KEY = "m1_3_load_date"

    today_data: dict[str, pd.DataFrame] = st.session_state.get(TODAY_KEY, {})
    load_date: date | None = st.session_state.get(DATE_KEY)

    need_load = refresh or not today_data or set(selected) - set(today_data.keys())

    if need_load:
        with st.spinner("ARK 보유종목 데이터 로딩 중..."):
            # 오늘 데이터를 전일로 이동 (날짜가 바뀐 경우에만)
            if today_data and load_date != date.today():
                st.session_state[PREV_KEY] = today_data

            new_data, errors = _load_all(selected)

            if errors:
                st.warning(
                    f"ARK 서버 접근 불가 — 잠시 후 재시도: {', '.join(errors)}"
                )
            if new_data:
                # 기존 데이터와 병합 (새로 선택된 ETF만 업데이트)
                merged = {**today_data, **new_data}
                st.session_state[TODAY_KEY] = merged
                st.session_state[DATE_KEY] = date.today()
                today_data = merged

    if not today_data:
        st.error("데이터를 불러오지 못했습니다. 잠시 후 새로고침하세요.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # ── 변동 하이라이트 카드 ──────────────────────────────────────────────
    prev_data: dict[str, pd.DataFrame] = st.session_state.get(PREV_KEY, {})
    filtered_today = {k: v for k, v in today_data.items() if k in selected}
    filtered_prev = {k: v for k, v in prev_data.items() if k in selected}

    st.markdown("### 📊 변동 하이라이트")

    if not filtered_prev:
        st.info(
            "비교할 전일 데이터가 없습니다 — 오늘 저장 후 내일부터 비교 가능합니다. "
            "현재는 전체 보유종목만 표시합니다."
        )
    else:
        changes = _compute_changes(filtered_today, filtered_prev)
        if not changes:
            st.success("선택 ETF에서 ±1%p 이상 변동 종목이 없습니다.")
        else:
            c_new = [c for c in changes if c["kind"] == "new"]
            c_up = [c for c in changes if c["kind"] == "up"]
            c_down = [c for c in changes if c["kind"] == "down"]

            tabs_labels = []
            tabs_data = []
            if c_new:
                tabs_labels.append(f"🆕 신규 편입 ({len(c_new)})")
                tabs_data.append(c_new)
            if c_up:
                tabs_labels.append(f"📈 비중 급증 ({len(c_up)})")
                tabs_data.append(c_up)
            if c_down:
                tabs_labels.append(f"📉 비중 급감 ({len(c_down)})")
                tabs_data.append(c_down)

            if tabs_labels:
                change_tabs = st.tabs(tabs_labels)
                for tab, group in zip(change_tabs, tabs_data):
                    with tab:
                        for item in group:
                            st.markdown(_change_card(item), unsafe_allow_html=True)

    # ── 전체 보유종목 테이블 ──────────────────────────────────────────────
    st.markdown("### 📋 전체 보유종목")
    etf_list = [e for e in selected if e in filtered_today]
    if not etf_list:
        st.markdown("</div>", unsafe_allow_html=True)
        return

    etf_tabs = st.tabs(etf_list)
    for tab, etf_name in zip(etf_tabs, etf_list):
        with tab:
            df = filtered_today[etf_name].copy()

            # 전일 대비 변동 컬럼 추가
            prev_df = filtered_prev.get(etf_name)
            if prev_df is not None and "ticker" in prev_df.columns and "weight_pct" in prev_df.columns:
                prev_map = {
                    str(r["ticker"]).strip(): float(r["weight_pct"])
                    for _, r in prev_df.iterrows()
                    if pd.notna(r["ticker"]) and pd.notna(r["weight_pct"])
                }
                df["전일대비(%p)"] = df["ticker"].apply(
                    lambda t: (
                        round(float(df.loc[df["ticker"] == t, "weight_pct"].values[0]) - prev_map[str(t).strip()], 2)
                        if str(t).strip() in prev_map else None
                    )
                )
            else:
                df["전일대비(%p)"] = None

            # 표시 컬럼 선택
            display_cols = []
            col_rename = {}
            if "company" in df.columns:
                display_cols.append("company")
                col_rename["company"] = "종목명"
            if "ticker" in df.columns:
                display_cols.append("ticker")
                col_rename["ticker"] = "티커"
            if "weight_pct" in df.columns:
                display_cols.append("weight_pct")
                col_rename["weight_pct"] = "비중(%)"
            if "market_value" in df.columns:
                display_cols.append("market_value")
                col_rename["market_value"] = "시가총액($)"
            if "전일대비(%p)" in df.columns:
                display_cols.append("전일대비(%p)")

            show_df = df[display_cols].rename(columns=col_rename)
            if "비중(%)" in show_df.columns:
                show_df = show_df.sort_values("비중(%)", ascending=False).reset_index(drop=True)

            st.dataframe(show_df, use_container_width=True, height=min(500, 55 + 35 * len(show_df)))

    st.markdown("</div>", unsafe_allow_html=True)
