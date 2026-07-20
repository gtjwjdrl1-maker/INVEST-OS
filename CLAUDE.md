# 프로젝트: AI 투자 운용 시스템 (모듈형 Streamlit 대시보드)

## 한 줄 요약
투자회사 프로세스(사전검토→리스크관리→심의→집행)를 개인 규모로 재현하는 Streamlit 앱.
모든 기능은 "모듈(위젯)" 단위로 구성되며, 스마트폰 홈 화면처럼 사용자가 모듈을 켜고 끄고 배치할 수 있어야 한다.

## 절대 규칙
1. **기존 모듈 파일은 수정하지 않는다.** 새 모듈을 추가할 때는 `modules/`에 새 파일을 만들고 `core/module_registry.py`에 등록만 추가한다.
2. **모듈은 서로 직접 의존하지 않는다.** 모듈 간 데이터 공유가 필요하면 `core/state.py`의 공유 세션 상태를 거친다.
3. **API 키가 없어도 앱이 죽지 않는다.** `.env`에 키가 없으면 데모 데이터 또는 "API 키 필요" 안내를 보여주고 계속 동작해야 한다.
4. **각 모듈의 트리거 조건·필터 기준·산출 지표는 임의로 바꾸지 않는다.** 설계와 다르게 구현할 이유가 있으면 먼저 확인한다.
5. **디자인 일관성을 지킨다.** 카드·색상·배지 기반 UI를 Streamlit 네이티브 컴포넌트로 재현하되, 필요 시 커스텀 CSS(`st.markdown(..., unsafe_allow_html=True)`)를 활용한다.

## 폴더 구조
```
app.py                     # 메인 셸: 사이드바 네비게이션 + 모듈 토글 + 레이아웃
core/
  module_base.py           # 모듈 공통 인터페이스 (메타데이터 + render 함수 규약)
  module_registry.py       # 모든 모듈을 등록하는 단일 파일
  state.py                 # 모듈 간 공유 세션 상태 (포트폴리오 데이터 등)
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
.env                       # API 키 (Gemini, DART, FRED, 네이버, KIS, Kakao, Gmail 등)
```

## 모듈 공통 인터페이스 (core/module_base.py 규약)
각 모듈 파일은 아래를 포함해야 한다:
- `MODULE_ID` (예: `"m1_2_core_scanner"`)
- `MODULE_META` dict: `{title, step, icon, default_visible, description}`
- `render(state)` 함수: Streamlit 컴포넌트를 그리는 단일 진입점

새 모듈은 이 규약만 지키면 `core/module_registry.py`에 한 줄 등록으로 대시보드에 나타난다.

## 코딩 컨벤션
- 변수명/주석: 한글 허용. 함수명/모듈ID: 영어 snake_case
- 외부 API 호출은 항상 try/except로 감싸고, 실패 시 사용자에게 명확한 에러 메시지 표시
- 신규 패키지 설치 시 `requirements.txt`에 반영

## 개발 원칙
Phase 0(셸 + 모듈 골격)을 먼저 완성하고, 이후 모듈을 하나씩 독립적으로 추가한다.
한 번에 여러 모듈을 동시에 만들지 않는다.
