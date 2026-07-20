# InvestOS — AI 투자 운용 시스템

> 투자회사의 의사결정 프로세스(사전검토 → 리스크관리 → 심의 → 집행·모니터링)를  
> 개인 투자자 규모로 재현하는 모듈형 Streamlit 대시보드

---

## 주요 기능

| 단계 | 모듈 | 설명 |
|------|------|------|
| 1단계 사전검토 | 🔍 코어전략 후보 스캐너 (m1_2) | 전체 상장종목 자동 탐색 → 배당성장·ROE·부채비율 조건 충족 종목 추천 (Gemini 해석) |
| 1단계 사전검토 | 🏛️ 국민연금 지분변동 트래커 (m1_4) | 국민연금 대량보유보고서 추적 — 매집 종목 자동 감지 |
| 1단계 사전검토 | 📐 국민연금 공시 수익률 검증 (m1_5) | 공시 종목 수익률 vs KOSPI 비교 — 신호 유효성 백테스트 |
| 2단계 리스크관리 | 📋 주요 공시 모니터 (m2_1) | DART 최근 공시 · 중요도 분류 · 종목 감시 · 원문 바로가기 |
| 2단계 리스크관리 | 🎯 리스크 분석 (m2_2) | 포트폴리오 VaR·CVaR + 종목 MOIC·MDD·회복기간 분석 |
| 3단계 심의 | 💬 AI 심의 프롬프트 생성기 (m3_1) | Claude·Gemini·Perplexity에 붙여넣을 분석 프롬프트 자동 생성 |
| 3단계 심의 | 📓 종목 선택 근거 기록 (m3_2) | 매수 근거·판단 일지를 날짜별로 기록·저장 |
| 4단계 집행·모니터링 | ⚖️ 비중 모니터링 (m4_1) | 목표 배분 이탈 시 리밸런싱 알림 + 보유종목 현황 (KIS 연동) |
| 4단계 집행·모니터링 | 📋 자동 브리핑 (m4_2) | 오전 9시 / 오후 4시 포트폴리오 브리핑을 카카오톡·Gmail로 발송 |

---

## 기술 스택

- **Frontend**: Streamlit
- **AI**: Google Gemini 2.5 Flash API (스크리닝 해석·브리핑 인사이트) + 외부 LLM(Claude·Gemini·Perplexity)용 심의 프롬프트 생성
- **데이터**: DART 공시 API, FinanceDataReader, yfinance, FRED API, 네이버 뉴스 API
- **증권사 연동**: 한국투자증권(KIS) API — 읽기 전용(잔고 조회)
- **알림**: 카카오톡 나에게 보내기 / Gmail SMTP

---

## 아키텍처

```
app.py                     # 메인 셸: 사이드바 네비게이션 + 모듈 토글
core/
  module_base.py           # 모듈 공통 인터페이스 (MODULE_ID, MODULE_META, render)
  module_registry.py       # 모듈 등록 단일 파일
  state.py                 # 모듈 간 공유 세션 상태
  kis_client.py            # KIS API 유틸리티 (읽기 전용)
  backtest_utils.py        # 백테스트 계산 유틸
modules/
  m1_2_core_scanner.py
  m1_4_nps_tracker.py
  m1_5_nps_backtest.py
  m2_1_dart_cutoff.py
  m2_2_stress_test.py
  m3_1_ai_debate.py
  m3_2_investment_journal.py
  m4_1_weight_monitor.py
  m4_2_briefing.py
scripts/
  kakao_token_setup.py     # 카카오 토큰 최초 발급(1회)
```

각 모듈은 `MODULE_ID`, `MODULE_META`, `render(state)` 규약만 지키면  
`core/module_registry.py`에 한 줄 등록으로 대시보드에 추가됩니다.

---

## 설치 및 실행

```bash
# 1. 저장소 클론
git clone https://github.com/gtjwjdrl1-maker/INVEST-OS.git
cd INVEST-OS

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 환경변수 설정
cp .env.example .env
# .env 파일을 열어 API 키 입력

# 4. 실행
streamlit run app.py
```

---

## 환경변수

`.env.example` 파일을 복사해 `.env`로 이름 변경 후 API 키를 입력하세요.  
키가 없어도 앱이 종료되지 않으며, 해당 기능은 데모 데이터로 동작합니다.

| 변수 | 필수 여부 | 설명 |
|------|----------|------|
| `GEMINI_API_KEY` | 필수 | AI 분석 전 기능에 사용 |
| `DART_API_KEY` | 권장 | 공시 조회 (없으면 더미 데이터) |
| `KIS_APP_KEY` / `KIS_APP_SECRET` | 선택 | 실제 잔고 조회 |
| `KAKAO_REST_API_KEY` | 선택 | 모닝 브리핑 카카오톡 발송 |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 선택 | 브리핑 뉴스 검색 |
| `FRED_API_KEY` | 선택 | 거시지표 조회 |

---

## 라이선스

개인 포트폴리오 프로젝트입니다. 상업적 이용을 금합니다.
