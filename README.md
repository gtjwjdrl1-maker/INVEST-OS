# InvestOS — AI 투자 운용 시스템

> 투자회사의 의사결정 프로세스(사전검토 → 리스크관리 → 심의 → 집행·모니터링)를  
> 개인 투자자 규모로 재현하는 모듈형 Streamlit 대시보드

---

## 주요 기능

| 단계 | 모듈 | 설명 |
|------|------|------|
| 1단계 사전검토 | 핵심 스캐너 (m1_2) | KRX 전체 종목 재무 스크리닝 + Gemini AI 해석 |
| 1단계 사전검토 | NPS 백테스트 (m1_5) | 국민연금 보유 상위 종목 수익률 백테스트 |
| 2단계 리스크관리 | DART 공시 분석 (m2_1) | 공시 기반 컷오프 + Gemini 피어그룹 비교 |
| 2단계 리스크관리 | VaR 리스크 분석 (m2_2) | 포트폴리오 VaR·CVaR 계산 + KOSPI 비교 |
| 3단계 심의 | AI 토론 (m3_1) | Gemini 찬반 토론으로 투자 의사결정 지원 |
| 3단계 심의 | 투자 일지 (m3_2) | 매매 기록 및 감정 메모 저장 |
| 4단계 집행·모니터링 | 비중 모니터 (m4_1) | KIS API 연동 포트폴리오 비중 이탈 감지 |
| 4단계 집행·모니터링 | 모닝 브리핑 (m4_2) | 뉴스요약 + 거시지표 카카오톡 발송 |

---

## 기술 스택

- **Frontend**: Streamlit
- **AI**: Google Gemini 2.5 Flash API (피어그룹 분석, 스크리닝 해석, 뉴스 요약)
- **데이터**: DART 공시 API, yfinance, FinanceDataReader, pykrx, FRED API
- **증권사 연동**: 한국투자증권(KIS) API — 읽기 전용(잔고 조회)
- **알림**: 카카오톡 나에게 보내기

---

## 아키텍처

```
app.py                     # 메인 셸: 사이드바 네비게이션 + 모듈 토글
core/
  module_base.py           # 모듈 공통 인터페이스 (MODULE_ID, MODULE_META, render)
  module_registry.py       # 모듈 등록 단일 파일
  state.py                 # 모듈 간 공유 세션 상태
  kis_client.py            # KIS API 유틸리티 (읽기 전용)
modules/
  m1_2_core_scanner.py
  m1_5_nps_backtest.py
  m2_1_dart_cutoff.py
  m2_2_stress_test.py
  m3_1_ai_debate.py
  m3_2_investment_journal.py
  m4_1_weight_monitor.py
  m4_2_briefing.py
docs/
  module_spec.md           # 모듈별 상세 스펙
  mockup.html              # 디자인 목업
```

각 모듈은 `MODULE_ID`, `MODULE_META`, `render(state)` 규약만 지키면  
`core/module_registry.py`에 한 줄 등록으로 대시보드에 추가됩니다.

---

## 설치 및 실행

```bash
# 1. 저장소 클론
git clone https://github.com/<your-username>/investos.git
cd investos

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
| `FRED_API_KEY` | 선택 | 거시지표 조회 |

---

## 라이선스

개인 포트폴리오 프로젝트입니다. 상업적 이용을 금합니다.
