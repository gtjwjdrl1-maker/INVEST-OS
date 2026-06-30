"""
KIS(한국투자증권) 포트폴리오 조회 유틸리티  ·  M-3-3

⚠️ 이 파일은 **조회 전용**이다.
   - 인증(토큰 발급) + 잔고조회 + 보유종목조회 함수만 포함한다.
   - 주문(매수/매도/정정/취소) 관련 함수는 절대 추가하지 않는다. (주문은 별도 M-3-2 모듈 담당)

이건 모듈(위젯)이 아니라 공유 유틸리티이므로 core/module_registry.py에는 등록하지 않는다.

.env 설정값
  KIS_APP_KEY     : KIS Developers 앱 키
  KIS_APP_SECRET  : KIS Developers 앱 시크릿
  KIS_ACCOUNT_NO  : 계좌번호 (예: "12345678-01")
  KIS_MODE        : "virtual"(모의투자, 기본값) 또는 "real"(실전투자)

키가 없거나 인증/조회에 실패하면 빈 포트폴리오(수치 0·보유종목 없음)로 폴백하고
응답의 source 필드를 "demo"로 표시한다. (화면에서 "KIS 미연결" 안내에 사용)
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests

# ── 서버 엔드포인트 ───────────────────────────────────────────────────
_BASE_URL = {
    "real":    "https://openapi.koreainvestment.com:9443",
    "virtual": "https://openapivts.koreainvestment.com:29443",
}

# 잔고조회 거래ID (tr_id) — 실전/모의 구분
_TR_ID_BALANCE = {
    "real":    "TTTC8434R",
    "virtual": "VTTC8434R",
}

# 인증 토큰을 짧은 시간 내 반복 발급하면 KIS가 차단하므로 모듈 단위로 캐시한다.
_TOKEN_CACHE: dict[str, Any] = {"token": None, "expires_at": 0.0, "mode": None}

# 자산군 분류 키워드 (M-4-1 비중 집계용)
# KIS 잔고조회는 자산군(주식/대체자산/채권/현금)을 주지 않으므로 종목명·코드 키워드로 추정한다.
_ASSET_KEYWORDS: dict[str, list[str]] = {
    "대체자산": ["리츠", "reit", "금현물", "금 ", "골드", "gold", "은현물", "silver",
                "원자재", "commodity", "인프라", "infra", "btc", "비트코인", "코인",
                "이더", "원유", "oil", "에너지"],
    "채권": ["채권", "국채", "국고채", "통안채", "회사채", "bond", "단기채", "종합채", "tips", "treasury", "ktb"],
    "현금": ["현금", "rp", "mmf", "머니마켓", "money market", "단기자금", "발행어음"],
}

# 자산군별 표시 색상 (core/state.py 기본 allocation과 동일하게 유지)
ASSET_COLORS: dict[str, str] = {
    "주식": "#185FA5",
    "대체자산": "#1D9E75",
    "채권": "#EF9F27",
    "현금": "#888780",
}


def classify_asset(name: str = "", code: str = "") -> str:
    """보유종목을 자산군(주식/대체자산/채권/현금)으로 분류. 기본값은 '주식'."""
    text = f"{name} {code}".lower()
    for asset, keywords in _ASSET_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return asset
    return "주식"


# ── 미연결(폴백) 응답 ─────────────────────────────────────────────────
def _empty_portfolio(reason: str = "KIS API 키 필요") -> dict:
    """키가 없거나 조회에 실패했을 때 반환하는 빈 포트폴리오.
    예시/더미 수치를 만들지 않고 모두 0·빈 리스트로 두어, 화면에서는
    'KIS 미연결' 안내만 보이게 한다(앱은 죽지 않음)."""
    return {
        "source": "demo",
        "message": reason,
        "total_value": 0,
        "daily_pnl": 0,
        "daily_pnl_pct": 0.0,
        "eval_pnl": 0,
        "holdings": [],
    }


# ── 클라이언트 ────────────────────────────────────────────────────────
class KISClient:
    """KIS Developers REST API 조회 전용 클라이언트."""

    def __init__(self) -> None:
        self.app_key = os.environ.get("KIS_APP_KEY", "").strip()
        self.app_secret = os.environ.get("KIS_APP_SECRET", "").strip()
        self.account_no = os.environ.get("KIS_ACCOUNT_NO", "").strip()
        mode = os.environ.get("KIS_MODE", "virtual").strip().lower()
        self.mode = mode if mode in _BASE_URL else "virtual"
        self.base_url = _BASE_URL[self.mode]

    # ── 설정 여부 ──────────────────────────────────────────────────
    @property
    def is_configured(self) -> bool:
        """조회에 필요한 키가 모두 준비됐는지."""
        return bool(self.app_key and self.app_secret and self.account_no)

    def _split_account(self) -> tuple[str, str]:
        """계좌번호를 종합계좌번호(CANO, 앞 8자리)와 상품코드(ACNT_PRDT_CD, 뒤 2자리)로 분리."""
        digits = self.account_no.replace("-", "").strip()
        if "-" in self.account_no:
            head, _, tail = self.account_no.partition("-")
            return head.strip(), tail.strip()
        # 대시가 없으면 앞 8자리 / 뒤 2자리로 가정
        return digits[:8], (digits[8:] or "01")

    # ── 인증 ───────────────────────────────────────────────────────
    def get_access_token(self) -> str | None:
        """OAuth 접근토큰 발급 (캐시 사용). 실패 시 None."""
        now = time.time()
        if (
            _TOKEN_CACHE["token"]
            and _TOKEN_CACHE["mode"] == self.mode
            and now < _TOKEN_CACHE["expires_at"]
        ):
            return _TOKEN_CACHE["token"]

        if not self.is_configured:
            return None

        url = f"{self.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token")
            if not token:
                return None
            # expires_in(초)보다 60초 일찍 만료시켜 안전 마진 확보
            expires_in = int(data.get("expires_in", 86400))
            _TOKEN_CACHE.update(
                token=token,
                expires_at=now + max(expires_in - 60, 60),
                mode=self.mode,
            )
            return token
        except (requests.RequestException, ValueError):
            return None

    # ── 잔고 + 보유종목 조회 ───────────────────────────────────────
    def get_balance(self) -> dict:
        """주식 잔고(요약 + 보유종목)를 조회한다.

        반환 형태(성공 시 source="live"):
          {
            "source": "live",
            "total_value": int,     # 총 평가금액
            "daily_pnl": int,       # 평가손익 합계 (참고: 일손익이 아닌 누적 평가손익)
            "daily_pnl_pct": float, # 평가손익률
            "eval_pnl": int,
            "holdings": [{name, code, type, price, chg, qty}, ...],
          }
        실패/미설정 시 _empty_portfolio()를 반환한다(source="demo").
        """
        if not self.is_configured:
            return _empty_portfolio("KIS API 키 필요 — 설정에서 KIS_APP_KEY/SECRET/계좌번호를 입력하세요")

        token = self.get_access_token()
        if not token:
            return _empty_portfolio("KIS 인증 실패 — 키 또는 모드(KIS_MODE) 설정을 확인하세요")

        cano, prdt_cd = self._split_account()
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": _TR_ID_BALANCE[self.mode],
        }
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": prdt_cd,
            "AFHR_FLPR_YN": "N",        # 시간외단일가 여부
            "OFL_YN": "",               # 오프라인 여부
            "INQR_DVSN": "02",          # 조회구분: 02=종목별
            "UNPR_DVSN": "01",          # 단가구분
            "FUND_STTL_ICLD_YN": "N",   # 펀드결제분 포함 여부
            "FNCG_AMT_AUTO_RDPT_YN": "N",  # 융자금액 자동상환 여부
            "PRCS_DVSN": "01",          # 처리구분: 01=전일매매포함
            "CTX_AREA_FK100": "",       # 연속조회검색조건
            "CTX_AREA_NK100": "",       # 연속조회키
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            return _empty_portfolio("KIS 잔고조회 실패 — 잠시 후 다시 시도하세요")

        # rt_cd "0" == 정상
        if str(data.get("rt_cd")) != "0":
            msg = data.get("msg1", "잔고조회 응답 오류")
            return _empty_portfolio(f"KIS 잔고조회 오류 — {msg}")

        return self._parse_balance(data)

    @staticmethod
    def _to_int(v: Any) -> int:
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_float(v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def _parse_balance(self, data: dict) -> dict:
        """KIS 잔고조회 응답을 state.py가 쓰는 형태로 변환."""
        # output1: 보유종목 리스트 / output2: 계좌 요약(단일 dict in list)
        rows = data.get("output1", []) or []
        summary_list = data.get("output2", []) or []
        summary = summary_list[0] if summary_list else {}

        holdings = []
        for r in rows:
            qty = self._to_int(r.get("hldg_qty"))
            if qty <= 0:
                continue
            name = r.get("prdt_name", "").strip()
            code = r.get("pdno", "").strip()
            price = self._to_int(r.get("prpr"))                 # 현재가
            value = self._to_int(r.get("evlu_amt")) or price * qty  # 평가금액
            holdings.append({
                "name": name,
                "code": code,
                "type": classify_asset(name, code),  # 자산군 추정 (주식/대체자산/채권/현금)
                "price": price,
                "chg": self._to_float(r.get("evlu_pfls_rt")),   # 평가손익률
                "qty": qty,
                "value": value,                                 # 비중 집계용 평가금액
            })

        total_value = self._to_int(summary.get("tot_evlu_amt"))   # 총평가금액
        eval_pnl = self._to_int(summary.get("evlu_pfls_smtl_amt"))  # 평가손익 합계
        # 평가손익률 = 평가손익 / (총평가금액 - 평가손익) * 100
        cost_basis = total_value - eval_pnl
        pnl_pct = round(eval_pnl / cost_basis * 100, 2) if cost_basis else 0.0

        return {
            "source": "live",
            "message": f"KIS 연결됨 ({'실전' if self.mode == 'real' else '모의투자'})",
            "total_value": total_value,
            "daily_pnl": eval_pnl,    # 주: KIS 잔고는 당일손익을 별도로 주지 않아 누적 평가손익을 사용
            "daily_pnl_pct": pnl_pct,
            "eval_pnl": eval_pnl,
            "holdings": holdings,
        }


# ── 외부에서 쓰는 단일 진입점 ─────────────────────────────────────────
def fetch_portfolio() -> dict:
    """KIS에서 포트폴리오(잔고+보유종목)를 가져온다.
    키가 없거나 실패하면 빈 포트폴리오로 폴백한다. 항상 dict를 반환한다."""
    try:
        return KISClient().get_balance()
    except Exception as e:  # 예기치 못한 오류에도 앱이 죽지 않도록
        return _empty_portfolio(f"KIS 조회 중 예외 발생 — {e}")
