"""
M-4-2 · 자동 브리핑 관리자
오전 9:00 / 오후 4:00 브리핑 생성 → 카카오톡·Gmail 발송
데이터 소스: core/state.py (포트폴리오 현황) + yfinance (시장) + RSS (뉴스) + Gemini (요약)
"""
from __future__ import annotations
import os
import smtplib
import textwrap
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import streamlit as st
from dotenv import load_dotenv as _load_dotenv
from pathlib import Path as _Path

from core.state import WATCHLIST_KEY, save_watchlist, load_watchlist
_ENV_FILE = _Path(__file__).resolve().parent.parent / ".env"
_load_dotenv(dotenv_path=_ENV_FILE, override=True)

MODULE_ID = "m4_2_briefing"
MODULE_META = {
    "title": "자동 브리핑",
    "step": 4,
    "icon": "📋",
    "default_visible": True,
    "description": "오전 9시 / 오후 4시 포트폴리오 브리핑을 카카오톡·Gmail로 발송",
}

_KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
_KAKAO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
_ENV_PATH = str(_ENV_FILE)


# ── .env 파일 업데이트 (refresh_token 교체용) ────────────────────────────
def _update_env_value(key: str, value: str) -> None:
    """·env 파일에서 특정 키의 값만 교체한다. 파일이 없으면 무시."""
    if not os.path.exists(_ENV_PATH):
        return
    with open(_ENV_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    new_lines = []
    found = False
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}\n")
    with open(_ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


# ── 카카오 access token 발급 (refresh_token으로 매번 갱신) ───────────────
def _get_kakao_access_token() -> tuple[str | None, str]:
    """refresh_token으로 access_token을 발급한다.
    반환: (access_token 또는 None, 에러메시지)"""
    rest_api_key = os.environ.get("KAKAO_REST_API_KEY", "")
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "")
    if not rest_api_key or not refresh_token:
        return None, "KAKAO_REST_API_KEY 또는 KAKAO_REFRESH_TOKEN 환경변수가 없습니다."
    try:
        import requests
        payload = {
            "grant_type": "refresh_token",
            "client_id": rest_api_key,
            "refresh_token": refresh_token,
        }
        client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "")
        if client_secret:
            payload["client_secret"] = client_secret
        resp = requests.post(_KAKAO_TOKEN_URL, data=payload, timeout=10)
        data = resp.json()
        if "access_token" not in data:
            return None, f"카카오 토큰 갱신 실패: {data}"
        if "refresh_token" in data and data["refresh_token"] != refresh_token:
            os.environ["KAKAO_REFRESH_TOKEN"] = data["refresh_token"]
            _update_env_value("KAKAO_REFRESH_TOKEN", data["refresh_token"])
        return data["access_token"], ""
    except Exception as e:
        return None, f"카카오 토큰 갱신 예외: {e}"


# ── 카카오 "나에게 보내기" ────────────────────────────────────────────────
def send_kakao(text: str) -> tuple[bool, str]:
    """카카오 나에게 보내기. (성공여부, 메시지) 반환."""
    access_token, err = _get_kakao_access_token()
    if not access_token:
        return False, err
    try:
        import json
        import requests
        template = json.dumps({
            "object_type": "text",
            "text": text[:1900],  # 카카오 텍스트 최대 2000자
            "link": {"web_url": "", "mobile_web_url": ""},
        })
        resp = requests.post(
            _KAKAO_SEND_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            data={"template_object": template},
            timeout=10,
        )
        if resp.status_code == 200:
            return True, "카카오톡 발송 성공"
        return False, f"카카오 API 오류 ({resp.status_code}): {resp.text[:200]}"
    except Exception as e:
        return False, f"카카오 발송 예외: {e}"


# ── Gmail SMTP 발송 ───────────────────────────────────────────────────────
def send_gmail(subject: str, body: str) -> tuple[bool, str]:
    """Gmail App Password로 SMTP 발송. (성공여부, 메시지) 반환."""
    gmail_user = os.environ.get("GMAIL_USER", "")
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not app_password:
        return False, "GMAIL_USER 또는 GMAIL_APP_PASSWORD 환경변수가 없습니다."
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = gmail_user
        msg["To"] = gmail_user
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(gmail_user, app_password)
            server.sendmail(gmail_user, gmail_user, msg.as_string())
        return True, "Gmail 발송 성공"
    except Exception as e:
        return False, f"Gmail 발송 예외: {e}"


# ── 해외 시장 데이터 수집 ────────────────────────────────────────────────
def _fetch_market_data() -> dict | None:
    """yfinance로 주요 지수·지표 전일 종가 수집. 실패 시 None 반환."""
    try:
        import yfinance as yf
        tickers = {
            "sp500":  "^GSPC",
            "nasdaq": "^IXIC",
            "dow":    "^DJI",
            "usdkrw": "KRW=X",
            "wti":    "CL=F",
            "gold":   "GC=F",
            "vix":    "^VIX",
            "kospi":  "^KS11",
            "kosdaq": "^KQ11",
        }
        result = {}
        for key, ticker in tickers.items():
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="5d")
                if hist.empty or len(hist) < 2:
                    continue
                prev_close = float(hist["Close"].iloc[-2])
                last_close = float(hist["Close"].iloc[-1])
                chg_pct = (last_close - prev_close) / prev_close * 100 if prev_close else 0
                result[key] = {"price": last_close, "chg_pct": chg_pct}
            except Exception:
                pass
        return result if result else None
    except Exception:
        return None


# ── 거시경제 필터 키워드 ──────────────────────────────────────────────
_MACRO_KEYWORDS = [
    # 통화·금리
    "금리", "기준금리", "한국은행", "연준", "Fed", "FOMC", "국채", "채권",
    # 환율·달러
    "환율", "달러", "원달러", "외환",
    # 경기·물가
    "물가", "CPI", "GDP", "성장률", "경기침체", "경기", "인플레",
    # 무역·수출
    "수출", "무역수지", "무역", "관세", "수입",
    # 주요 산업
    "반도체", "코스피", "코스닥", "증시", "주가", "외국인",
    # 글로벌 리스크
    "중국", "미국", "트럼프", "관세", "전쟁", "제재", "공급망",
    # 기업·산업 거시
    "실적", "영업이익", "매출", "IPO", "상장폐지",
]


# ── 국내 경제 뉴스 RSS 수집 ──────────────────────────────────────────────
def _fetch_news(n: int = 5) -> tuple[list[dict], list[dict]]:
    """
    RSS 3개 소스를 모두 수집 후 거시경제 키워드 매칭 기사를 우선 선별.
    반환: (브리핑용 n건, 전체 기사 목록)
    """
    rss_sources = [
        "https://www.hankyung.com/feed/economy",
        "https://www.yonhapnews.co.kr/rss/economy.xml",
        "https://www.mk.co.kr/rss/30100041/",
    ]
    all_items = []
    try:
        import feedparser
        seen_titles = set()
        for url in rss_sources:
            try:
                feed = feedparser.parse(url)
                for e in feed.entries[:20]:  # 소스당 최대 20건 수집
                    title = e.get("title", "").strip()
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        all_items.append({
                            "title": title,
                            "link": e.get("link", ""),
                        })
            except Exception:
                continue
    except Exception:
        return [], []

    if not all_items:
        return [], []

    # 키워드 매칭 점수 계산 (많이 포함될수록 우선)
    def _score(item: dict) -> int:
        t = item["title"]
        return sum(1 for kw in _MACRO_KEYWORDS if kw in t)

    scored = sorted(all_items, key=_score, reverse=True)

    # 점수 1 이상인 기사 우선, 부족하면 나머지로 채움
    priority = [x for x in scored if _score(x) >= 1]
    fallback  = [x for x in scored if _score(x) == 0]
    return (priority + fallback)[:n], all_items


# ── Gemini로 뉴스 요약 ────────────────────────────────────────────────────
def _summarize_news(news_list: list[dict]) -> str:
    """Gemini Flash로 뉴스 헤드라인 요약. API 키 없거나 실패 시 제목 목록 반환."""
    if not news_list:
        return "(뉴스 없음)"
    headlines = "\n".join(f"- {n['title']}" for n in news_list)
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return headlines
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = (
            "당신은 한국 주식 투자자를 위한 거시경제 뉴스 큐레이터입니다.\n"
            "아래 경제 뉴스 헤드라인 중 한국 증시와 거시경제에 실질적 영향을 미치는 "
            "핵심 뉴스 최대 3건을 선별하여, 각 뉴스가 투자자에게 왜 중요한지 "
            "한 줄씩 한국어로 설명해줘.\n"
            "형식: • [뉴스 핵심 요약] → [투자자 관점 의미]\n"
            "관련없는 뉴스(연예, 스포츠, 단순 기업 인사 등)는 제외.\n\n"
            "헤드라인 목록:\n"
            + headlines
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text.strip()
    except Exception:
        return headlines


# ── 보유 종목별 뉴스 수집 ────────────────────────────────────────────────
def _fetch_holdings_news(holdings: list, n_per_stock: int = 2) -> dict:
    """보유 종목별 최신 뉴스를 검색해 반환.
    반환: {"삼양식품": [{"title": ..., "link": ...}, ...], ...}
    """
    if not holdings:
        return {}

    result = {}
    for h in holdings:
        name = h.get("name", "")
        if not name:
            continue
        news_items = []

        # 1순위: 네이버 뉴스 검색 API
        naver_id  = os.environ.get("NAVER_CLIENT_ID", "")
        naver_sec = os.environ.get("NAVER_CLIENT_SECRET", "")
        if naver_id and naver_sec:
            try:
                import requests, urllib.parse
                url = (
                    "https://openapi.naver.com/v1/search/news.json"
                    f"?query={urllib.parse.quote(name)}&display={n_per_stock}&sort=date"
                )
                resp = requests.get(
                    url,
                    headers={"X-Naver-Client-Id": naver_id,
                             "X-Naver-Client-Secret": naver_sec},
                    timeout=5,
                )
                if resp.status_code == 200:
                    items = resp.json().get("items", [])
                    news_items = [
                        {"title": i["title"].replace("<b>","").replace("</b>",""),
                         "link":  i["link"]}
                        for i in items[:n_per_stock]
                    ]
            except Exception:
                pass

        # 2순위: 구글 뉴스 RSS (네이버 키 없을 때 폴백)
        if not news_items:
            try:
                import feedparser, urllib.parse
                rss_url = (
                    "https://news.google.com/rss/search"
                    f"?q={urllib.parse.quote(name)}&hl=ko&gl=KR&ceid=KR:ko"
                )
                feed = feedparser.parse(rss_url)
                news_items = [
                    {"title": e.get("title", ""), "link": e.get("link", "")}
                    for e in feed.entries[:n_per_stock]
                ]
            except Exception:
                pass

        if news_items:
            result[name] = news_items

    return result


# ── 종목 감시 키워드별 뉴스 검색 ───────────────────────────────────────────
def _fetch_watchlist_news(watchlist: dict, n_per_keyword: int = 3) -> list[dict]:
    """
    watchlist = {"SK하이닉스": ["D램", "파운드리"], ...}
    등록된 종목별 키워드마다 네이버 뉴스 검색 API(폴백: 구글 뉴스 RSS)로 직접 검색한다.
    (메인 브리핑의 거시경제 RSS와는 완전히 별도 — 좁은 RSS 풀에 갇히지 않음)
    반환: [{"종목": ..., "키워드": ..., "title": ..., "link": ...}], 링크 기준 중복 제거.
    키워드 단위로 실패를 흡수하므로 일부 검색이 실패해도 앱은 죽지 않는다.
    """
    if not watchlist:
        return []

    naver_id  = os.environ.get("NAVER_CLIENT_ID", "")
    naver_sec = os.environ.get("NAVER_CLIENT_SECRET", "")

    hits: list[dict] = []
    seen_links = set()
    for 종목, keywords in watchlist.items():
        for kw in keywords:
            if not kw or not kw.strip():
                continue
            news_items = []

            # 1순위: 네이버 뉴스 검색 API
            if naver_id and naver_sec:
                try:
                    import requests, urllib.parse
                    url = (
                        "https://openapi.naver.com/v1/search/news.json"
                        f"?query={urllib.parse.quote(kw)}&display={n_per_keyword}&sort=date"
                    )
                    resp = requests.get(
                        url,
                        headers={"X-Naver-Client-Id": naver_id,
                                 "X-Naver-Client-Secret": naver_sec},
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        items = resp.json().get("items", [])
                        news_items = [
                            {"title": i["title"].replace("<b>", "").replace("</b>", ""),
                             "link":  i["link"]}
                            for i in items[:n_per_keyword]
                        ]
                except Exception:
                    pass

            # 2순위: 구글 뉴스 RSS (네이버 키 없거나 실패 시 폴백)
            if not news_items:
                try:
                    import feedparser, urllib.parse
                    rss_url = (
                        "https://news.google.com/rss/search"
                        f"?q={urllib.parse.quote(kw)}&hl=ko&gl=KR&ceid=KR:ko"
                    )
                    feed = feedparser.parse(rss_url)
                    news_items = [
                        {"title": e.get("title", ""), "link": e.get("link", "")}
                        for e in feed.entries[:n_per_keyword]
                    ]
                except Exception:
                    pass

            for item in news_items:
                link = item.get("link", "")
                if link and link not in seen_links:
                    seen_links.add(link)
                    hits.append({"종목": 종목, "키워드": kw,
                                 "title": item.get("title", ""), "link": link})

    return hits


def _format_holdings_news(holdings_news: dict) -> str:
    """종목별 뉴스를 브리핑 텍스트로 변환."""
    if not holdings_news:
        return "(종목 뉴스 없음)"
    lines = []
    for company, items in holdings_news.items():
        lines.append(f"▶ {company}")
        for item in items:
            title = item["title"][:35] + "…" if len(item["title"]) > 35 else item["title"]
            lines.append(f"  · {title}")
    return "\n".join(lines)


# ── 브리핑 텍스트 조립 ────────────────────────────────────────────────────
def _build_briefing(
    state,
    market: dict | None = None,
    news_summary: str = "",
    holdings_news: dict | None = None,
) -> str:
    now_dt = datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M")

    def _fmt(val: float, decimals: int = 2) -> str:
        sign = "▲" if val >= 0 else "▼"
        return f"{sign}{abs(val):.{decimals}f}%"

    def _price(val: float, decimals: int = 2) -> str:
        return f"{val:,.{decimals}f}"

    mkt = market or {}

    def _mkt_row(key, label):
        d = mkt.get(key)
        if not d:
            return f"{label:<8} —"
        return f"{label:<8} {_price(d['price'], 0 if d['price'] > 100 else 2)}  {_fmt(d['chg_pct'])}"

    # ── 포트폴리오 현황 ──────────────────────────────────────────────
    total = getattr(state, "total_value", 0)
    daily_pnl = getattr(state, "daily_pnl", 0)
    daily_pnl_pct = getattr(state, "daily_pnl_pct", 0.0)
    kis_src = getattr(state, "kis_status", {}).get("source", "demo")
    kis_live = kis_src == "live"
    pnl_sign = "+" if daily_pnl >= 0 else ""

    if kis_live:
        portfolio_section = (
            f"총평가액: {total:,}원\n"
            f"당일손익: {pnl_sign}{daily_pnl:,}원 ({pnl_sign}{daily_pnl_pct:.2f}%)"
        )
    else:
        portfolio_section = "KIS 미연결 — 설정에서 연결하세요"

    vix_val = mkt.get("vix", {}).get("price")
    if vix_val is not None:
        vix_level = "높음" if vix_val > 25 else ("보통" if vix_val > 15 else "낮음")
        vix_line = f"VIX      {vix_val:.2f} ({vix_level})"
    else:
        vix_line = "VIX      —"

    # FRED 거시지표 (실질금리, 장단기금리차) — 키 없으면 생략
    fred_key = os.environ.get("FRED_API_KEY", "")
    macro_line = ""
    if fred_key:
        try:
            import requests as _req
            def _fred_val(sid):
                r = _req.get(
                    "https://api.stlouisfed.org/fred/series/observations",
                    params={"series_id": sid, "api_key": fred_key,
                            "file_type": "json", "sort_order": "desc", "limit": 5},
                    timeout=8,
                )
                for o in r.json().get("observations", []):
                    if o.get("value", ".") != ".":
                        return float(o["value"])
            real_rate = _fred_val("DFII10")
            spread    = _fred_val("T10Y2Y")
            if real_rate is not None and spread is not None:
                macro_line = (
                    f"📊 거시지표: 미국 실질금리 {real_rate:+.2f}%  |  "
                    f"장단기금리차(10Y-2Y) {spread:+.2f}%p"
                )
        except Exception:
            pass

    news_section = news_summary or "(뉴스 없음)"

    lines = [
        "[InvestOS] 📊 일일 브리핑",
        now_str,
        "─────────────────",
        "🌐 해외 시장",
        _mkt_row("sp500",  "S&P500"),
        _mkt_row("nasdaq", "NASDAQ"),
        _mkt_row("dow",    "DOW"),
        "─────────────────",
        "💱 주요 지표",
    ]
    usd = mkt.get("usdkrw")
    lines.append(f"달러/원  {_price(usd['price'], 0)}원  {_fmt(usd['chg_pct'])}" if usd else "달러/원  —")
    wti = mkt.get("wti")
    lines.append(f"WTI유가  ${_price(wti['price'], 1)}  {_fmt(wti['chg_pct'])}" if wti else "WTI유가  —")
    gld = mkt.get("gold")
    lines.append(f"금       ${_price(gld['price'], 0)}  {_fmt(gld['chg_pct'])}" if gld else "금       —")
    lines.append(vix_line)
    if macro_line:
        lines.append(macro_line)

    lines += [
        "─────────────────",
        "📊 국내 시장",
        _mkt_row("kospi",  "KOSPI"),
        _mkt_row("kosdaq", "KOSDAQ"),
        "─────────────────",
        "💼 내 포트폴리오",
        portfolio_section,
        "─────────────────",
        "📰 주요 뉴스",
        news_section,
        "─────────────────",
        "📌 내 종목 뉴스",
        _format_holdings_news(holdings_news or {}),
    ]

    return "\n".join(lines)


# ── 감시 브리핑 텍스트 조립 ────────────────────────────────────────────────
def _build_watch_briefing(hits: list[dict]) -> str:
    """종목 감시 키워드 검색 결과(_fetch_watchlist_news)로 별도 브리핑을 만든다.
    메인 브리핑과 완전히 분리되어 있어 시장·뉴스 수집 부담을 주지 않는다."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "[InvestOS] 🔍 종목 감시 브리핑",
        now_str,
        "─────────────────",
        "🔍 감시 키워드 매칭 뉴스",
    ]
    if hits:
        for h in hits:
            lines.append(f"· [{h['종목']}] {h['키워드']} — {h['title']}")
    else:
        lines.append("(매칭 뉴스 없음)")
    return "\n".join(lines)


# ── Streamlit UI ─────────────────────────────────────────────────────────
def render(state) -> None:
    _load_dotenv(dotenv_path=_ENV_FILE, override=True)

    # ── 종목 감시 키워드 ─────────────────────────────────────────────
    st.session_state.setdefault(WATCHLIST_KEY, {})

    with st.expander("📋 종목 감시 키워드", expanded=False):
        watchlist = st.session_state[WATCHLIST_KEY]

        if not watchlist:
            st.caption("3-1 AI 토론 결과의 KEYWORDS를 여기에 등록하세요.")
        else:
            for 종목, keywords in list(watchlist.items()):
                c1, c2 = st.columns([5, 1])
                c1.markdown(f"**{종목}** — {' · '.join(keywords)}")
                if c2.button("삭제", key=f"wl_del_{종목}"):
                    del st.session_state[WATCHLIST_KEY][종목]
                    save_watchlist(st.session_state[WATCHLIST_KEY])
                    st.rerun()

        st.markdown("---")
        st.markdown("**키워드 추가**")
        st.caption("Claude 분석 결과의 KEYWORDS 값을 아래에 입력하세요.")
        c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 1])
        wl_name = c1.text_input("종목명", key="wl_name")
        wl_k1 = c2.text_input("키워드 1", key="wl_k1")
        wl_k2 = c3.text_input("키워드 2", key="wl_k2")
        wl_k3 = c4.text_input("키워드 3", key="wl_k3")
        if c5.button("저장", key="wl_add"):
            if wl_name and wl_k1:
                kws = [k for k in [wl_k1, wl_k2, wl_k3] if k.strip()]
                st.session_state[WATCHLIST_KEY][wl_name] = kws
                save_watchlist(st.session_state[WATCHLIST_KEY])
                st.rerun()

    # ── API 연결 상태 ────────────────────────────────────────────────
    kakao_ok = bool(os.environ.get("KAKAO_REST_API_KEY") and os.environ.get("KAKAO_REFRESH_TOKEN"))
    gmail_ok = bool(os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD"))
    gemini_ok = bool(os.environ.get("GEMINI_API_KEY"))
    naver_ok = bool(os.environ.get("NAVER_CLIENT_ID") and os.environ.get("NAVER_CLIENT_SECRET"))

    def _badge(ok: bool, label: str) -> str:
        color = "#1D9E75" if ok else "#9ca3af"
        icon = "✅" if ok else "⬜"
        return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;margin-right:4px">{icon} {label}</span>'

    st.markdown(
        '<div class="inv-card"><div class="inv-card-title">🔌 발송 채널 연결 상태</div>'
        + _badge(kakao_ok, "카카오톡")
        + _badge(gmail_ok, "Gmail")
        + _badge(gemini_ok, "Gemini AI")
        + _badge(naver_ok, "네이버뉴스")
        + "</div>",
        unsafe_allow_html=True,
    )

    if not kakao_ok:
        st.caption("카카오톡: .env에 KAKAO_REST_API_KEY · KAKAO_REFRESH_TOKEN 필요 — `python scripts/kakao_token_setup.py` 실행")
    if not gmail_ok:
        st.caption("Gmail: .env에 GMAIL_USER · GMAIL_APP_PASSWORD 필요 (구글 계정 → 앱 비밀번호 발급)")
    if not gemini_ok:
        st.caption("Gemini AI: .env에 GEMINI_API_KEY 없으면 뉴스 헤드라인만 표시됩니다.")
    if not naver_ok:
        st.caption("종목 뉴스: NAVER_CLIENT_ID · NAVER_CLIENT_SECRET 없으면 구글뉴스 RSS로 자동 대체됩니다.")

    # ── 브리핑 미리보기 ─────────────────────────────────────────────
    st.markdown("---")

    # ── 데이터 소스 상태 표시 ────────────────────────────────────
    news_status = st.empty()
    market_status = st.empty()

    if st.button("브리핑 생성", key="m4_2_preview_btn"):
        with st.spinner("시장 데이터 수집 중…"):
            market = _fetch_market_data()
        market_status.markdown(
            f"해외시장 {'✅' if market else '❌'}  |  "
            f"뉴스 RSS {'⏳'}  |  "
            f"Gemini요약 {'✅' if gemini_ok else '❌'}"
        )
        with st.spinner("뉴스 수집 중…"):
            news, _ = _fetch_news(n=5)
        news_ok = bool(news)
        market_status.markdown(
            f"해외시장 {'✅' if market else '❌'}  |  "
            f"뉴스 RSS {'✅' if news_ok else '❌'}  |  "
            f"Gemini요약 {'✅' if gemini_ok else '❌'}"
        )
        with st.spinner("뉴스 요약 중…"):
            summary = _summarize_news(news)
        with st.spinner("종목 뉴스 수집 중…"):
            h_news = _fetch_holdings_news(
                getattr(state, "holdings", []) or []
            )
        with st.spinner("브리핑 조립 중…"):
            st.session_state["m4_2_preview"] = _build_briefing(
                state, market, summary, h_news
            )

    preview_text = st.session_state.get("m4_2_preview", "")
    if preview_text:
        st.markdown(
            '<div class="inv-card"><div class="inv-card-title">📄 브리핑 미리보기</div></div>',
            unsafe_allow_html=True,
        )
        st.text_area("", value=preview_text, height=400, key="m4_2_preview_area", label_visibility="collapsed")

        # ── 발송 ──────────────────────────────────────────────────────
        st.markdown("**지금 발송**")
        col_k, col_g = st.columns(2)
        with col_k:
            if st.button("📲 카카오톡 발송", key="m4_2_send_kakao", disabled=not kakao_ok):
                with st.spinner("카카오톡 발송 중…"):
                    ok, msg = send_kakao(preview_text)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
        with col_g:
            if st.button("📧 Gmail 발송", key="m4_2_send_gmail", disabled=not gmail_ok):
                subject = f"[InvestOS] {datetime.now().strftime('%Y-%m-%d')} 일일 브리핑"
                with st.spinner("Gmail 발송 중…"):
                    ok, msg = send_gmail(subject, preview_text)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)

        if not kakao_ok and not gmail_ok:
            st.info("API 키가 없어 발송 버튼이 비활성화되어 있습니다. 미리보기는 정상 표시됩니다.")

    # ── 감시 브리핑 (메인 브리핑과 완전히 분리) ─────────────────────
    st.markdown("---")
    st.markdown("**🔍 감시 브리핑**")
    st.caption("등록된 종목 감시 키워드로 뉴스를 검색해 별도 브리핑을 만듭니다.")

    watchlist_all = st.session_state.get(WATCHLIST_KEY, {})
    watchlist_names = list(watchlist_all.keys())

    if not watchlist_names:
        st.caption("등록된 감시 종목이 없습니다. 위 '종목 감시 키워드'에서 먼저 추가하세요.")
    else:
        selected_names = st.multiselect(
            "감시 브리핑에 포함할 종목 선택 (선택한 종목만 검색해 조회 시간·API 호출을 줄입니다)",
            options=watchlist_names,
            default=watchlist_names,
            key="m4_2_watch_select",
        )

        if st.button("감시 브리핑 생성", key="m4_2_watch_preview_btn", disabled=not selected_names):
            watchlist = {name: watchlist_all[name] for name in selected_names}
            with st.spinner("감시 키워드 뉴스 검색 중…"):
                hits = _fetch_watchlist_news(watchlist)
            st.session_state["m4_2_watch_preview"] = _build_watch_briefing(hits)

    watch_preview_text = st.session_state.get("m4_2_watch_preview", "")
    if watch_preview_text:
        st.markdown(
            '<div class="inv-card"><div class="inv-card-title">📄 감시 브리핑 미리보기</div></div>',
            unsafe_allow_html=True,
        )
        st.text_area("", value=watch_preview_text, height=250,
                      key="m4_2_watch_preview_area", label_visibility="collapsed")

        st.markdown("**지금 발송**")
        wcol_k, wcol_g = st.columns(2)
        with wcol_k:
            if st.button("📲 카카오톡 발송", key="m4_2_watch_send_kakao", disabled=not kakao_ok):
                with st.spinner("카카오톡 발송 중…"):
                    ok, msg = send_kakao(watch_preview_text)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
        with wcol_g:
            if st.button("📧 Gmail 발송", key="m4_2_watch_send_gmail", disabled=not gmail_ok):
                subject = f"[InvestOS] {datetime.now().strftime('%Y-%m-%d')} 감시 브리핑"
                with st.spinner("Gmail 발송 중…"):
                    ok, msg = send_gmail(subject, watch_preview_text)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)

        if not kakao_ok and not gmail_ok:
            st.info("API 키가 없어 발송 버튼이 비활성화되어 있습니다. 미리보기는 정상 표시됩니다.")


# ── 외부(스케줄러·CLI)에서 호출 가능한 단독 발송 함수 ──────────────────
def send_briefing_now() -> dict:
    """스케줄러 / CLI에서 직접 호출하는 발송 함수.
    Streamlit 세션 없이도 동작한다."""
    from dotenv import load_dotenv
    load_dotenv()

    # state 없이 최소 포트폴리오 요약을 직접 빌드
    class _MinimalState:
        total_value = 0
        daily_pnl = 0
        daily_pnl_pct = 0.0
        allocation = {}
        holdings = []
        kis_status = {"source": "demo"}
        rebalance_alerts = []

    try:
        from core import state as _state_mod
        # Streamlit 세션 밖에서는 get_state()를 쓸 수 없으므로 kis_client를 직접 호출
        from core import kis_client
        pf = kis_client.fetch_portfolio()
        s = _MinimalState()
        if pf.get("source") == "live":
            s.total_value = pf.get("total_value", 0)
            s.daily_pnl = pf.get("daily_pnl", 0)
            s.daily_pnl_pct = pf.get("daily_pnl_pct", 0.0)
            s.holdings = pf.get("holdings", [])
            s.kis_status = {"source": "live"}
        state = s
    except Exception:
        state = _MinimalState()

    market = _fetch_market_data()
    news, _ = _fetch_news(n=5)
    summary = _summarize_news(news)
    h_news = _fetch_holdings_news(state.holdings or [])
    text = _build_briefing(state, market, summary, h_news)

    results = {}

    kakao_ok, kakao_msg = send_kakao(text)
    results["kakao"] = {"ok": kakao_ok, "msg": kakao_msg}

    subject = f"[InvestOS] {datetime.now().strftime('%Y-%m-%d')} 일일 브리핑"
    gmail_ok, gmail_msg = send_gmail(subject, text)
    results["gmail"] = {"ok": gmail_ok, "msg": gmail_msg}

    return results


def send_watch_briefing_now() -> dict:
    """감시 브리핑을 단독으로 발송한다 (메인 브리핑과 무관).
    스케줄러 / CLI에서 직접 호출 가능. Streamlit 세션 없이도 동작한다."""
    from dotenv import load_dotenv
    load_dotenv()

    try:
        watchlist = load_watchlist()
    except Exception:
        watchlist = {}

    hits = _fetch_watchlist_news(watchlist)
    text = _build_watch_briefing(hits)

    results = {}

    kakao_ok, kakao_msg = send_kakao(text)
    results["kakao"] = {"ok": kakao_ok, "msg": kakao_msg}

    subject = f"[InvestOS] {datetime.now().strftime('%Y-%m-%d')} 감시 브리핑"
    gmail_ok, gmail_msg = send_gmail(subject, text)
    results["gmail"] = {"ok": gmail_ok, "msg": gmail_msg}

    return results
