# AI Task Triage Checklist

이 문서는 **무맥락 AI가 작업을 잘못 분류하는 실수**를 줄이기 위한 빠른 분류표다.
코드를 열기 전에 먼저 읽고, 이번 작업이 어느 범주인지 판단한다.

원칙:
- 이 문서는 "무엇을 먼저 봐야 하는지"를 빠르게 정한다.
- 실제 구현 기준은 각 기능별 SSOT 문서에서 확정한다.
- 자주 반복되는 수정이면 이 문서의 `6. 반복 작업 플레이북`을 같이 본다.

---

## 1. 30초 분류 질문

아래 질문에 먼저 답한다.

1. 사용자가 바꾸려는 것이 화면 배치/스타일인가, 동작 규칙인가?
2. 버튼/모달/AJAX 응답이 바뀌는가?
3. 상태 플래그, 저장 로직, DB 데이터가 바뀌는가?
4. 데모/튜토리얼 흐름인가, 실제 미팅/매칭 기능인가?
5. 기존 문서 중 이미 같은 책임 문서가 있는가?

이 다섯 개에 답하면 대부분의 작업은 아래 범주 중 하나로 떨어진다.

변경 등급도 같이 정한다:
- `A` 문서 전용
- `B` UI/클라이언트
- `C` 서버 로직
- `D` 상태/DB

---

## 2. 작업 범주별 분류

### 2-1. 화면/UI 수정

이 범주로 본다:
- 레이아웃, 간격, 색상, 버튼 위치
- 일반 멤버/관리자 UI 차이
- 세션 카드, footer, 팝오버, 모달 표시

먼저 읽을 문서:
1. `docs/meeting_ui_css_map.md`
2. `docs/meeting_regression_checklist.md`
3. 필요 시 `docs/large_files_overview.md`

먼저 볼 코드:
1. 관련 템플릿
2. 해당 템플릿을 렌더링하는 뷰
3. 관련 JS/CSS 블록

금지 추정:
- CSS만 바꾸면 안전할 것이라고 추정하지 않는다.
- 관리자/일반 멤버 분기를 넓게 건드려도 다른 탭에 영향이 없다고 추정하지 않는다.

### 2-2. 매칭/예약/최종 일정 동작 수정

이 범주로 본다:
- 버튼 활성/비활성 조건
- 예약 진입 조건
- 조율 보드 동작
- 최종 공유/확정 규칙

먼저 읽을 문서:
1. `docs/meeting_handover.md`
2. `docs/meeting_process_state_machine.md`
3. `docs/meeting_regression_checklist.md`

먼저 볼 코드:
1. `pracapp/views/matching_views.py`
2. `pracapp/templates/pracapp/match_result.html`
3. `pracapp/models.py`

빠른 판단:
- 버튼 활성/비활성, 안내 문구, 배너 위치 문제면 `match_result.html`의 액션 버튼 렌더링/인라인 JS를 먼저 본다.
- 버튼을 눌렀을 때 409/검증 실패까지 바뀌어야 하면 `matching_views.py`의 서버 검증도 같이 본다.

금지 추정:
- 현재 조율 보드가 예전 `일반/룸 보기` 전제를 유지한다고 추정하지 않는다.
- 프론트 상태만 바꾸면 서버 검증도 따라갈 것이라고 추정하지 않는다.

### 2-3. 데이터 저장/상태 전이 수정

이 범주로 본다:
- 모델 필드
- 저장 시점
- 트랜잭션 경계
- 상태 플래그 의미/전이
- 무결성 검증

먼저 읽을 문서:
1. `docs/meeting_integrity_rules.md`
2. `docs/meeting_process_state_machine.md`
3. 필요 시 `docs/meeting_handover.md`

먼저 볼 코드:
1. `pracapp/models.py`
2. 관련 뷰
3. 관련 저장 호출부

빠른 판단:
- `Meeting` 플래그 의미/전이를 바꾸는 작업이면 `models.py`와 `matching_views.py`를 먼저 묶어서 본다.
- `ExtraPracticeSchedule`와 `RoomBlock` 같이 저장되는 경로를 바꾸는 작업이면 `extra_practice_views.py`를 먼저 보고 `transaction.atomic()` 경계를 확인한다.

금지 추정:
- UI 문구를 보고 상태 플래그 의미를 추정하지 않는다.
- `get_or_create`가 항상 안전하다고 추정하지 않는다.
- 저장 로직 하나만 바꾸면 관련 드래프트/확인 상태도 자동으로 맞는다고 추정하지 않는다.

### 2-4. 데모/튜토리얼 수정

이 범주로 본다:
- 인트로 CTA/로딩 문구/첫 진입 UX
- 시나리오 A 자동 매칭 보드 진입
- `/demo/tutorial/` 인터랙티브 튜토리얼
- 데모 배너/튜토리얼 안내

먼저 읽을 문서:
1. `docs/demo_page_plan.md`
2. 필요 시 `docs/archive/demo_feedback_acceptance_2026-02-25.md`

먼저 볼 코드:
1. `pracapp/views/demo_views.py`
2. `pracapp/templates/pracapp/demo/`
3. `pracapp/static/pracapp/js/tutorial_demo.js`
4. `/demo/tutorial/`이면 `pracapp/templates/pracapp/demo/demo_feature_tutorial.html`

빠른 판단:
- 인트로 문구/배치/로딩/CTA 수정이면 `demo_home.html`과 `demo_views.py`를 먼저 본다.
- `/demo/tutorial/` 단계/카드/spotlight 수정이면 `demo_feature_tutorial.html`과 `demo_views.py`를 먼저 본다.
- 시나리오 진입 결과나 역할 전환, 세션 데이터가 바뀌면 `demo_views.py`의 세팅 로직도 같이 본다.

금지 추정:
- 과거 `/tutorial/` 독립 흐름이 현재 기준이라고 추정하지 않는다.
- 과거 시나리오 번호 체계가 그대로 유효하다고 추정하지 않는다.
- `tutorial_demo.js` 하나만 보면 데모 튜토리얼 전체가 다 보인다고 추정하지 않는다.

### 2-5. 추가 합주 수정

이 범주로 본다:
- 본 미팅 예약과 별도인 추가 합주 배정
- `ExtraPracticeSchedule`
- 추가 합주용 보드/저장

먼저 읽을 문서:
1. `docs/extra_practice_feature.md`
2. `docs/extra_practice_ui_style.md`
3. 필요 시 `docs/meeting_integrity_rules.md`

먼저 볼 코드:
1. `pracapp/views/extra_practice_views.py`
2. `pracapp/templates/pracapp/extra_practice.html`
3. `pracapp/models.py`

금지 추정:
- 추가 합주가 본 매칭/예약 흐름과 같은 상태 규칙을 공유한다고 추정하지 않는다.
- 저장 경로가 원자적이라고 추정하지 않는다.

---

## 3. 문서와 코드가 충돌할 때

충돌 징후:
- 문서 설명과 실제 버튼/URL/상태 플래그가 다르다.
- 문서에 없는 분기나 모델 필드가 코드에 있다.
- 아카이브 문서와 루트 문서가 서로 다른 말을 한다.

행동 규칙:
1. 가장 직접적인 SSOT 문서를 먼저 확인한다.
2. 관련 URL, 뷰, 템플릿, 모델을 교차 확인한다.
3. 루트 `docs/` 문서와 `docs/archive/` 문서가 충돌하면 루트 문서를 우선한다.
4. 임의로 새 기준을 만들지 않는다.
5. 충돌이 해소되면 기존 SSOT 문서를 갱신하지, 비슷한 새 문서를 만들지 않는다.

---

## 4. 작업 시작 직전 체크

1. 이 작업이 어떤 범주인지 한 줄로 말할 수 있는가?
2. 먼저 읽을 SSOT 문서 1개를 정했는가?
3. 먼저 볼 코드 1~3개를 정했는가?
4. 이 작업에서 금지된 추정이 무엇인지 알고 있는가?
5. 수정 후 어떤 검증을 돌릴지 정했는가?

이 다섯 개에 답하지 못하면, 아직 코드를 열기 전에 문서를 더 봐야 한다.

## 5. 작업 승인 전 자가점검

코드 수정 직전에 아래를 짧게 확인한다.

1. 이번 작업의 변경 등급(`A`~`D`)을 한 줄로 말할 수 있는가?
2. 해당 등급에 맞는 최소 검증(`git diff -- docs`, `manage.py check`, `manage.py test pracapp.tests`)을 정했는가?
3. 사용자 요청 없이 범위를 넓히는 금지 변경(상태 의미, URL, 모델, 대형 리팩터링)에 해당하지 않는가?
4. 대형 파일이면 필요한 구간만 읽고 수정 범위를 좁혔는가?
5. 반복 작업이면 이 문서의 `6. 반복 작업 플레이북`을 확인했는가?

이 다섯 개 중 하나라도 답하지 못하면, 아직 수정 승인을 스스로 내리면 안 된다.

---

## 6. 반복 작업 플레이북

### 6-1. 버튼 상태 수정

대상:
- 버튼 활성/비활성 조건
- 버튼 문구
- 버튼 클릭 중 잠금 처리

순서:
1. `docs/meeting_handover.md` 또는 관련 UI SSOT를 읽는다.
2. 해당 버튼을 렌더링하는 템플릿과 인라인 JS를 찾는다.
3. 같은 동작을 호출하는 버튼이 여러 개인지 확인한다.
4. 비동기 확인 모달이 있으면, 모달 전에 in-flight 잠금이 걸리는지 확인한다.
5. 버튼 상태를 바꾼 뒤 `manage.py check`를 실행한다.
6. 동작 기준이 바뀌면 SSOT와 회귀 체크 문서를 함께 갱신한다.

주의:
- 클릭된 버튼 하나만 막고 같은 액션의 다른 버튼을 열어두지 않는다.
- UI 잠금만 바꾸고 서버 검증이 필요 없는지 넘겨짚지 않는다.

### 6-2. 모달/패널 수정

대상:
- 모달 문구/버튼/열림 순서
- 비동기 로딩 모달
- 패널 데이터 로드

순서:
1. 관련 기능 SSOT를 읽는다.
2. 모달 템플릿과 호출 함수, 서버 응답 경로를 함께 확인한다.
3. 응답 역전 가능성이 있으면 요청 순번 또는 취소 기준이 있는지 본다.
4. 버튼 중복 클릭 방어가 필요한지 확인한다.
5. `manage.py check`를 실행한다.
6. 화면 구조 책임이 바뀌면 UI 문서를 갱신한다.

주의:
- 느린 이전 응답이 최신 화면을 덮어쓰지 않게 한다.
- 모달 순서를 바꿀 때 기존 서버 검증 흐름이 그대로인지 확인한다.

### 6-3. AJAX 응답/클라이언트-서버 연결 수정

대상:
- `fetch` 응답 형식
- 상태 코드 처리
- 프론트 후속 분기

순서:
1. 관련 SSOT와 `docs/meeting_reference_pages.md`를 읽는다.
2. 템플릿/JS 호출부와 대상 뷰를 함께 본다.
3. URL, 요청 메서드, 응답 JSON 키를 교차 확인한다.
4. UI만 바뀌는지, 서버 검증도 바뀌는지 범위를 결정한다.
5. 서버 코드가 바뀌면 `manage.py test pracapp.tests`까지 실행한다.
6. 응답 계약이 바뀌면 관련 SSOT를 갱신한다.

주의:
- 프론트 JSON 키만 바꾸고 서버 응답은 그대로 둘 것이라고 추정하지 않는다.
- 에러 응답(409, 400, 500 대체 처리)을 같이 확인한다.

### 6-4. 서버 검증/분기 수정

대상:
- 권한 분기
- 중복 요청 방어
- 검증 실패 응답

순서:
1. 관련 SSOT와 회귀 체크 문서를 먼저 읽는다.
2. URL -> 뷰 -> 모델 의존 순서로 확인한다.
3. 중복 제출, 동시 요청, 상태 전이 경계를 확인한다.
4. 필요한 경우 `select_for_update()`, `IntegrityError` 처리, idempotent 응답 여부를 검토한다.
5. `manage.py check`와 `manage.py test pracapp.tests`를 실행한다.
6. 검증 규칙이 바뀌면 SSOT와 회귀 체크 문서를 같이 갱신한다.

주의:
- 사용자 요청 없이 검증 기준 자체를 완화하지 않는다.
- 서버 응답만 바꾸고 프론트 후속 처리를 방치하지 않는다.

### 6-5. 상태/DB 저장 수정

대상:
- 모델 필드
- 상태 전이
- 트랜잭션 경계
- 저장 순서

순서:
1. `docs/meeting_integrity_rules.md`와 `docs/meeting_process_state_machine.md`를 먼저 읽는다.
2. 관련 모델, 저장 뷰, 후속 UI 영향을 함께 확인한다.
3. 변경 등급을 `D`로 두고 범위를 다시 검토한다.
4. 드래프트/확정/후속 동기화 경로까지 같이 확인한다.
5. `manage.py check`와 `manage.py test pracapp.tests`를 실행한다.
6. 상태 코드, 저장 규칙, 트랜잭션 경계를 문서에 즉시 반영한다.

주의:
- UI 문구로 상태 의미를 추정하지 않는다.
- 사용자 명시 요구 없이 모델 스키마나 상태 의미를 넓게 바꾸지 않는다.
