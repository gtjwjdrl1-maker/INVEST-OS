# 단계별 개발 프롬프트

> CLAUDE.md가 프로젝트 루트에 있으므로 Claude Code가 자동으로 읽습니다.
> 각 Phase에서 **첨부 파일**과 **프롬프트**만 복사해서 사용하세요.

---

## 개발 순서

| Phase | 모듈 | 이유 |
|---|---|---|
| 0 | 셸 + 빈 모듈 자리 | 전체 골격이 있어야 이후 모듈을 끼워 넣을 수 있음 ✅ 완료 |
| 1 | M-2-1 DART 재무 컷오프 | 규칙 기반, AI API 불필요 — 가장 단순하고 확실하게 검증 가능 |
| 2 | M-2-3 대체자산 시그널 검증기 | FRED 데이터 기반 규칙형, M-2-1과 동일한 난이도 |
| 3 | M-2-2 스트레스 테스트 분석기 | 과거 데이터 시뮬레이션, 계산 로직이 더 복잡함 |
| 4 | M-4-1 비중 모니터링 대시보드 | 시각화 중심, 의존성 낮음, 완성하면 동기부여 됨 |
| 5 | M-3-1 AI 크로스 찬반 토론장 | 첫 AI API 연동 모듈 (Claude API) |
| 6 | M-4-2 자동 브리핑 관리자 | 스케줄러 + 카카오톡/지메일 연동, 외부 발송 모듈 |
| 7 | M-3-2 KIS 주문 집행 UI | 실제 자금 이동 — 가장 신중하게 마지막에 |

---

## Phase 1. M-2-1 DART 재무 컷오프 위젯

**첨부 파일:** `@docs/module_spec.md`

**프롬프트:**
```
docs/module_spec.md의 "M-2-1. DART 재무 컷오프 위젯" 섹션 스펙대로
modules/m2_1_dart_cutoff.py를 만들어줘.

- core/module_base.py 인터페이스를 그대로 따를 것
- 1차 필터(yfinance/PYKRX 배당성장·ROE·부채비율·시총·거래대금)와
  2차 퇴출기준(DART 주석 기반 우발부채/CB잔액/특수관계자대여금)을 분리된 함수로 구현
- DART_API_KEY는 .env에서 읽고, 키가 없으면 데모 데이터로 동작하며 화면에 "DART API 키 필요" 안내 표시
- 통과/퇴출 결과를 표 형태로 보여주고, 퇴출 이유를 함께 표시
- 완료 후 core/module_registry.py에 이 모듈 등록 (다른 모듈 코드는 건드리지 말 것)
```

**확인:** 종목 입력 시 1차 필터 결과 / DART 키 없을 때 안내 문구 / 대시보드에 카드 표시

---

## Phase 2. M-2-3 대체자산 시그널 검증기

**첨부 파일:** `@docs/module_spec.md`

**프롬프트:**
```
docs/module_spec.md의 "M-2-3. 대체자산 시그널 검증기" 섹션 스펙대로
modules/m2_3_alt_signal.py를 만들어줘.

- FRED API로 미국 10년물 실질금리, 장단기 금리차(10Y-2Y)를 가져올 것
  FRED_API_KEY는 .env에서 읽고, 없으면 데모 데이터로 동작
- yfinance로 BTC 가격과 200일 이동평균 가져올 것
- 4개 자산(금/BTC/리츠/인프라)의 트리거 충족 여부를 ✓/✗로 표시하고
  근거 수치(현재값, 기준값)를 함께 보여줄 것
- core/module_registry.py에 등록 (다른 모듈은 건드리지 말 것)
```

**확인:** 4개 자산 트리거 상태 표시 / FRED 키 없을 때 폴백 동작

---

## Phase 3. M-2-2 스트레스 테스트 분석기

**첨부 파일:** `@docs/module_spec.md`

**프롬프트:**
```
docs/module_spec.md의 "M-2-2. 스트레스 테스트 분석기" 섹션 스펙대로
modules/m2_2_stress_test.py를 만들어줘.

- 2008 금융위기, 2020 코로나, 2022 인플레 쇼크 3개 구간의 과거 가격 데이터를
  yfinance로 가져와 매월 말 리밸런싱을 가정한 백테스팅 수행
- MDD와 샤프지수((포트수익-무위험수익률)/표준편차) 계산
- 무위험수익률은 .env의 RISK_FREE_RATE 또는 기본값 3% 사용
- 결과는 시나리오별 테이블 + 누적수익률 차트(plotly)로 표시
- 계산 함수는 core/backtest_utils.py로 분리해서 다른 모듈에서도 재사용 가능하게
- core/module_registry.py에 등록
```

**확인:** 3개 시나리오 결과 표시 / 차트 렌더링 / 계산 시간 확인

---

## Phase 4. M-4-1 비중 모니터링 대시보드

**첨부 파일:** `@docs/module_spec.md`

**프롬프트:**
```
docs/module_spec.md의 "M-4-1. 비중 모니터링 대시보드" 섹션 스펙대로
modules/m4_1_weight_monitor.py를 만들어줘.

- core/state.py의 포트폴리오 데이터(자산군별 비중)를 가져와 파이차트로 시각화
- 목표 비중(채권10/주식60/대체30)과 현재 비중을 비교해 ±5% 이탈 시 경고 카드 표시
- app.py의 기존 CSS 스타일(inv-card 클래스 등)을 재사용할 것
- core/module_registry.py에 등록
```

**확인:** 파이차트 표시 / 비중 어긋나게 설정해 경고 뜨는지 테스트

---

## Phase 5. M-3-1 AI 크로스 찬반 토론장

**첨부 파일:** `@docs/module_spec.md`

**프롬프트:**
```
docs/module_spec.md의 "M-3-1. AI 크로스 찬반 토론장" 섹션 스펙대로
modules/m3_1_ai_debate.py를 만들어줘.

- Anthropic API(ANTHROPIC_API_KEY, .env)를 사용해 "가치투자 관점"과 "모멘텀 관점"
  두 개의 시스템 프롬프트로 같은 종목에 대해 각각 의견을 생성
- 종목명/티커, 검토 비중을 입력받는 폼 구성
- 스트리밍 출력(st.write_stream)으로 두 의견을 순차 표시
- 마지막에 Half-Kelly 공식으로 권장 비중 계산 (켈리 비율 산출 로직은 core/kelly_utils.py로 분리)
- API 키 없을 때는 데모 응답으로 동작
- core/module_registry.py에 등록
```

**확인:** Claude API 키로 응답 생성 / 스트리밍 동작 / API 호출 횟수 확인

---

## Phase 6. M-4-2 자동 브리핑 관리자

**첨부 파일:** `@docs/module_spec.md`

**프롬프트:**
```
docs/module_spec.md의 "M-4-2. 자동 브리핑 관리자" 섹션 스펙대로
modules/m4_2_briefing.py를 만들어줘.

- 오전 9시/오후 4시 스케줄 설정 UI
  (실제 백그라운드 스케줄러는 별도 프로세스로 안내, APScheduler 또는 OS 크론탭 연동 방법을 README에 설명)
- 카카오 REST API로 "나에게 보내기" 발송 함수 (KAKAO_API_KEY, .env)
- 지메일 발송 함수 (SMTP, GMAIL_APP_PASSWORD .env)
- 브리핑 내용 미리보기를 화면에 표시하고 "지금 테스트 발송" 버튼 제공
- API 키 없을 때는 발송 없이 미리보기만 표시
- core/module_registry.py에 등록
```

**확인:** 테스트 발송 버튼으로 카카오톡 수신 확인

---

## Phase 7. M-3-2 KIS 주문 집행 UI (가장 마지막, 신중하게)

**첨부 파일:** `@docs/module_spec.md`

**프롬프트:**
```
docs/module_spec.md의 "M-3-2. KIS 주문 집행 UI" 섹션 스펙대로
modules/m3_2_kis_order.py를 만들어줘.

- 한국투자증권 KIS Developers API 연동 (KIS_APP_KEY, KIS_APP_SECRET, .env)
- 처음에는 모의투자(paper trading) 모드만 지원하고,
  실거래 모드는 "실거래 활성화" 체크박스를 켜야만 동작하도록
- 시장가/수량 입력 → "주문 검토" 버튼 → "주문 실행" 버튼(확인 모달) 2단계로 분리해서 오인클릭 방지
- 주문 결과(성공/실패, 체결가)를 화면에 표시하고 로그 파일에 기록
- core/module_registry.py에 등록
```

**확인:** 모의투자 모드로 충분히 테스트 후 실거래 전환. 실거래는 소액으로 먼저 검증.

---

## 매 Phase 공통 체크리스트

- [ ] `streamlit run app.py` 실행해서 에러 없이 뜨는지 확인
- [ ] 새 모듈이 사이드바 토글 목록에 나타나는지 확인
- [ ] API 키를 일부러 지워보고 폴백 동작 확인
- [ ] 이전 Phase 모듈이 여전히 정상 동작하는지 확인 (회귀 테스트)
- [ ] 문제 없으면 `git commit -m "feat: M-X-X 모듈 추가"`
