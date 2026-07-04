"""
모듈 간 공유 세션 상태.

기본값에는 예시/더미 수치를 넣지 않는다(모두 0·빈 값).
KIS 키가 설정돼 있으면 core.kis_client로 실제 잔고·보유종목을 가져와 채우고,
키가 없으면 빈 상태로 두고 kis_status로 "KIS 미연결"을 알린다(앱은 죽지 않음).
allocation_target(목표 배분)만 운용 정책값으로 유지한다.
"""
from __future__ import annotations
import os
import json
import streamlit as st
from dataclasses import dataclass, field
from pathlib import Path

from core import kis_client


# ── 종목 감시 키워드 (M-3-1에서 저장, M-4-2에서 뉴스 매칭에 사용) ──────
WATCHLIST_KEY = "m_watchlist"
# 구조: { "삼성전자": ["HBM 수주", "파운드리 점유율", "메모리 가격"], ... }

_WATCHLIST_FILE = Path(__file__).parent.parent / "data" / "watchlist.json"

def _load_watchlist() -> dict:
    """앱 시작 시 파일에서 watchlist 불러오기."""
    try:
        if _WATCHLIST_FILE.exists():
            return json.loads(_WATCHLIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def load_watchlist() -> dict:
    """세션 밖(CLI·스케줄러)에서 파일로부터 직접 watchlist를 읽는다."""
    return _load_watchlist()


def save_watchlist(watchlist: dict) -> None:
    """watchlist를 파일에 저장 (앱 재시작 후에도 유지)."""
    try:
        _WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        _WATCHLIST_FILE.write_text(
            json.dumps(watchlist, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception:
        pass


@dataclass
class AppState:
    # ── 포트폴리오 기본 수치 (KIS 연결 시 실데이터로 채움) ────────────
    total_value: int = 0                  # 총 평가액 (원)
    daily_pnl: int = 0                    # 평가손익 (원)
    daily_pnl_pct: float = 0.0            # 평가손익률 (%)

    # ── 자산배분 현황 (보유종목으로부터 계산) ────────────────────────
    allocation: dict = field(default_factory=dict)
    # 목표 배분은 운용 정책값이므로 기본값 유지 (예시 수치 아님)
    allocation_target: dict = field(default_factory=lambda: {
        "주식": 60, "대체자산": 30, "채권": 7, "현금": 3
    })

    # ── 주요 보유 종목 (KIS 연결 시 채움) ────────────────────────────
    holdings: list = field(default_factory=list)

    # ── KIS 연결 상태 (kis_client로 갱신) ────────────────────────────
    kis_status: dict = field(default_factory=lambda: {
        "source": "demo",          # "live"=실제 잔고 / "demo"=미연결 폴백
        "connected": False,
        "message": "KIS API 키 필요",
    })

    # ── 데이터 소스(API) 연결 상태 — .env 키 유무로 실시간 판정 ───────
    @property
    def api_status(self) -> dict:
        def _row(env_key: str, always: bool = False) -> dict:
            ok = always or bool(os.environ.get(env_key))
            return {"connected": ok, "label": "연결됨" if ok else "미연결"}
        return {
            "DART":      _row("DART_API_KEY"),
            "FRED":      _row("FRED_API_KEY"),
            "yfinance":  _row("", always=True),   # 키 불필요
            "Gemini":    _row("GEMINI_API_KEY"),
            "카카오":    _row("KAKAO_API_KEY"),
            "KIS":       {"connected": self.kis_status.get("source") == "live",
                          "label": "연결됨" if self.kis_status.get("source") == "live" else "미연결"},
        }

    # ── 리밸런싱 알림 — 현재 배분 vs 목표 배분에서 계산 ───────────────
    @property
    def rebalance_alerts(self) -> list:
        alerts = []
        for asset, target in self.allocation_target.items():
            cur = self.allocation.get(asset, {}).get("pct", 0)
            diff = target - cur
            if abs(diff) >= 5 and self.total_value > 0:  # ±5%p 이탈 + 잔고 있을 때만
                alerts.append({
                    "asset": asset,
                    "current": cur,
                    "target": target,
                    "amount": int(abs(diff) / 100 * self.total_value),
                })
        return alerts


def _build_allocation(holdings: list) -> dict | None:
    """보유종목 평가금액을 자산군별로 집계해 allocation 형태로 변환 (옵션 B).
    KIS는 자산군을 주지 않으므로 kis_client.classify_asset으로 추정한 type을 사용한다."""
    totals: dict[str, float] = {}
    for h in holdings:
        asset = h.get("type") or kis_client.classify_asset(h.get("name", ""), h.get("code", ""))
        if asset not in kis_client.ASSET_COLORS:  # 배당ETF/금ETF 등 더미 라벨 보정
            asset = kis_client.classify_asset(h.get("name", ""), h.get("code", ""))
        val = h.get("value") or (h.get("price", 0) * h.get("qty", 0))
        totals[asset] = totals.get(asset, 0) + val

    grand = sum(totals.values())
    if grand <= 0:
        return None

    alloc: dict = {}
    for asset in ("주식", "대체자산", "채권", "현금"):  # 고정 순서로 표시
        if totals.get(asset):
            alloc[asset] = {
                "pct": round(totals[asset] / grand * 100),
                "color": kis_client.ASSET_COLORS[asset],
            }
    return alloc or None


def _apply_kis_portfolio(state: AppState) -> None:
    """KIS에서 잔고·보유종목을 가져와 state에 반영.
    키가 없거나 실패하면 빈 값(0·빈 리스트)이 그대로 남고 kis_status만 갱신된다.
    (총 평가액·평가손익·보유종목·자산배분을 실제 데이터로 채운다.)"""
    pf = kis_client.fetch_portfolio()
    state.kis_status = {
        "source": pf.get("source", "demo"),
        "connected": pf.get("source") == "live",
        "message": pf.get("message", ""),
    }
    if pf.get("source") != "live":
        return  # 폴백: 빈 상태 유지 (예시 수치 생성 안 함)

    state.total_value = pf["total_value"]
    state.daily_pnl = pf["daily_pnl"]
    state.daily_pnl_pct = pf["daily_pnl_pct"]
    if pf.get("holdings"):
        state.holdings = pf["holdings"]
        # 옵션 B: 보유종목 평가금액으로 자산배분(M-4-1) 재계산
        alloc = _build_allocation(pf["holdings"])
        if alloc:
            state.allocation = alloc


def get_state() -> AppState:
    """session_state에서 AppState를 가져오거나 초기화."""
    # 앱 재시작 후에도 유지되도록 파일에서 로드
    if WATCHLIST_KEY not in st.session_state:
        st.session_state[WATCHLIST_KEY] = _load_watchlist()
    if "app_state" not in st.session_state:
        state = AppState()
        # 최초 1회만 KIS 조회 시도 (rerun마다 재호출 방지)
        _apply_kis_portfolio(state)
        st.session_state["app_state"] = state
    return st.session_state["app_state"]


def refresh_portfolio() -> AppState:
    """KIS에서 포트폴리오를 다시 조회해 state를 갱신한다(수동 새로고침용)."""
    state = get_state()
    _apply_kis_portfolio(state)
    st.session_state["app_state"] = state
    return state


def get_module_visibility() -> dict[str, bool]:
    """모듈 토글 상태를 session_state에서 가져옴."""
    if "module_visibility" not in st.session_state:
        st.session_state["module_visibility"] = {}
    return st.session_state["module_visibility"]


def is_module_visible(module_id: str, default: bool = True) -> bool:
    vis = get_module_visibility()
    return vis.get(module_id, default)


def set_module_visibility(module_id: str, visible: bool) -> None:
    vis = get_module_visibility()
    vis[module_id] = visible
    st.session_state["module_visibility"] = vis


def init_widget_defaults() -> None:
    """모든 모듈 입력 위젯의 session_state 기본값을 앱 시작 시 한 번만 초기화.

    탭(페이지) 전환 후 돌아왔을 때 위젯이 기본값으로 리셋되는 것을 방지한다.
    키가 이미 존재하면 덮어쓰지 않는다.
    """
    if "widget_defaults_initialized" in st.session_state:
        return

    defaults: dict[str, object] = {
        # ── M-1-1 뉴스 스캐너 ──────────────────────────────────────
        "m1_1_query": "",
        # ── M-1-5 NPS 백테스트 ─────────────────────────────────────
        "m1_5_ticker_raw": "",
        # ── M-2-1 DART 재무제표 기준 ───────────────────────────────
        "dart_query": "",
        # ── M-2-2 VaR 리스크 분석 ──────────────────────────────────
        "var_manual_input": "",
        # ── M-3-1 AI 심의 프롬프트 생성기 ──────────────────────────
        "m3_1_name": "",
        "m3_1_ticker": "",
        # ── 설정 탭 스케줄 ──────────────────────────────────────────
        "sched_threshold": "±5%",
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    st.session_state["widget_defaults_initialized"] = True
