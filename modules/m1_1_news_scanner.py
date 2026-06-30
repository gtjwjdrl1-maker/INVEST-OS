from __future__ import annotations

import time
import os
import urllib.parse
import requests
import feedparser
import streamlit as st

MODULE_ID = "m1_1_news_scanner"
MODULE_META = {
    "title": "뉴스 스캐너",
    "step": 1,
    "icon": "📰",
    "default_visible": True,
    "description": "종목명·키워드로 최신 뉴스를 검색합니다",
}

_CACHE_TTL = 300  # 5분


def _fetch_naver(query: str) -> list[dict]:
    client_id = os.environ.get("NAVER_CLIENT_ID", "")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return []
    url = f"https://openapi.naver.com/v1/search/news.json?query={urllib.parse.quote(query)}&display=10"
    try:
        resp = requests.get(
            url,
            headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
            timeout=5,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [
            {
                "title": i.get("title", "").replace("<b>", "").replace("</b>", ""),
                "link": i.get("link", ""),
                "source": i.get("originallink", "네이버뉴스"),
                "date": i.get("pubDate", ""),
            }
            for i in items
        ]
    except Exception:
        return []


def _fetch_google_rss(query: str) -> list[dict]:
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries[:10]:
            results.append(
                {
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "source": entry.get("source", {}).get("title", "Google뉴스") if isinstance(entry.get("source"), dict) else "Google뉴스",
                    "date": entry.get("published", ""),
                }
            )
        return results
    except Exception:
        return []


def _dedupe(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for item in items:
        key = item["title"][:40]
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out[:15]


def render(state) -> None:
    st.markdown(
        '<div class="inv-card"><div class="inv-card-title">📰 뉴스 스캐너</div>',
        unsafe_allow_html=True,
    )

    col_input, col_btn = st.columns([5, 1])
    with col_input:
        query = st.text_input(
            "",
            placeholder="종목명 또는 키워드 입력 (예: 삼성전자, AAPL)",
            label_visibility="collapsed",
            key="m1_1_query",
        )
    with col_btn:
        search_clicked = st.button("뉴스 조회", use_container_width=True, key="m1_1_search")

    if search_clicked and query:
        cache_key = f"m1_1_cache_{query}"
        ts_key = f"m1_1_ts_{query}"
        now = time.time()
        if cache_key in st.session_state and now - st.session_state.get(ts_key, 0) < _CACHE_TTL:
            articles = st.session_state[cache_key]
        else:
            with st.spinner("뉴스를 불러오는 중..."):
                naver = _fetch_naver(query)
                google = _fetch_google_rss(query)
                articles = _dedupe(naver + google)
            st.session_state[cache_key] = articles
            st.session_state[ts_key] = now

        if articles:
            rows_html = "".join(
                f"""<div class="stock-row" style="flex-direction:column;align-items:flex-start;gap:2px;padding:8px 0;border-bottom:1px solid #1f2937">
                  <a href="{a['link']}" target="_blank" style="color:#e2e8f0;font-size:13px;font-weight:500;text-decoration:none">{a['title']}</a>
                  <div style="font-size:11px;color:#6b7280">{a['source']} &nbsp;·&nbsp; {a['date'][:16] if a['date'] else ''}</div>
                </div>"""
                for a in articles
            )
            st.markdown(rows_html, unsafe_allow_html=True)
        else:
            st.warning("뉴스를 불러올 수 없습니다. 네이버 API 키를 확인하거나 잠시 후 다시 시도하세요.")
    elif search_clicked and not query:
        st.warning("키워드를 입력해 주세요.")

    st.markdown("</div>", unsafe_allow_html=True)
