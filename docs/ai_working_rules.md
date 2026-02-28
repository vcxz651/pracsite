# AI Working Rules

이 문서는 **무맥락 AI 작업자 공통 가드레일**이다.
기능별 세부 기준 전에 먼저 읽고, 작업 중 계속 참조한다.

원칙:
- 구현 판단은 기능별 SSOT 문서에서 한다.
- 기능 관련 판단은 항상 UX(사용자 이해도, 클릭 수, 대기 체감, 실패처럼 느껴지는지, 실수 유발 가능성)를 함께 고려한다.
- 이 문서는 "어떻게 안전하게 작업할지"를 정의한다.

---

## 1. 시작 규칙

작업 시작 순서:
1. `docs/README.md`
2. `docs/project_overview.md`
3. 이 문서(`docs/ai_working_rules.md`)
4. `docs/ai_task_triage_checklist.md`
5. 필요 시 `docs/ai_task_triage_checklist.md`의 `6. 반복 작업 플레이북`
6. 작업 주제별 SSOT 문서
7. 필요 시 `docs/meeting_reference_pages.md`

금지:
- 문서를 전부 다 읽고 시작하려고 하지 않는다.
- SSOT를 찾지 않고 코드부터 수정하지 않는다.
- 작업 범주를 정하지 않고 파일부터 열지 않는다.
- 같은 책임의 문서를 새로 만들지 않는다.

---

## 2. SSOT 원칙

- 기능별 현재 기준은 `docs/` 루트 문서가 우선이다.
- 과거 이력/백로그/보류 문서는 `docs/archive/`에서만 참고한다.
- 루트 문서와 아카이브 문서가 충돌하면 루트 문서를 따른다.
- 문서가 여러 개면 "가장 직접적으로 그 기능을 설명하는 문서 1개"를 먼저 기준으로 잡는다.

대표 SSOT:
- 미팅/매칭/예약: `docs/meeting_handover.md`
- 상태 전이: `docs/meeting_process_state_machine.md`
- 회귀 체크: `docs/meeting_regression_checklist.md`
- 데이터 무결성: `docs/meeting_integrity_rules.md`
- `meeting_detail` CSS 책임: `docs/meeting_ui_css_map.md`
- 데모: `docs/demo_page_plan.md`
- 추가 합주: `docs/extra_practice_feature.md`

---

## 3. 수정 전 필수 확인

### 3-0. 변경 등급 먼저 결정

코드를 열기 전에 이번 작업의 변경 등급을 먼저 정한다.

- `A` 문서 전용: `docs/`만 수정
- `B` UI/클라이언트: 템플릿, CSS, 인라인 JS, 정적 프론트 수정
- `C` 서버 로직: 뷰, 서버 검증, AJAX 응답, 서버 분기 수정
- `D` 상태/DB: 모델, 상태 전이, 저장 규칙, 트랜잭션 경계 수정

원칙:
- 여러 등급이 섞이면 더 높은 등급 기준을 따른다.
- `C` 이상이면 관련 SSOT와 회귀 체크 문서를 함께 볼 준비를 한다.
- `D`는 사용자 명시 요구 없이 범위를 넓히지 않는다.

### 3-1. 큰 파일 경계 확인

아래 파일은 수정 전에 구조를 먼저 파악한다.

- `pracapp/templates/pracapp/match_result.html`
- `pracapp/templates/pracapp/meeting_detail.html`
- `pracapp/views/matching_views.py`
- `pracapp/views/meeting_views.py`
- `pracapp/models.py`

권장:
- 관련 ID, 클래스명, 함수명을 검색해 수정 범위를 좁힌다.
- 대형 파일 전체를 한 번에 건드리지 말고, 필요한 구간만 읽는다.
- 수정 전 `docs/large_files_overview.md`를 참고한다.

### 3-2. URL/뷰/템플릿 연결 확인

- 템플릿 수정 시 해당 뷰를 같이 본다.
- AJAX/폼 액션 수정 시 `pracsite/urls.py`를 같이 본다.
- 모델 필드/상태 플래그 수정 시 뷰와 템플릿 영향을 같이 확인한다.

---

## 4. 자주 발생하는 위험

### 4-1. 매칭/예약 보드 회귀

- `match_result.html`은 CSS/HTML/JS가 한 파일에 밀집되어 있다.
- 작은 수정도 이벤트 핸들러 중복, 상태 꼬임, 숨김 조건 붕괴를 만들 수 있다.
- 현재 조율 보드는 **룸슬롯 단일 모드** 전제를 유지한다.
- 확인 모달 뒤에 `fetch`가 이어지는 액션(저장/공유/예약 진입)은 **모달을 기다리기 전에** in-flight 잠금을 먼저 걸어야 한다.
- 같은 동작을 호출하는 버튼이 여러 개면, 클릭된 버튼 하나만 막지 말고 **같은 액션 버튼 전체**를 함께 잠가야 한다.

### 4-2. `meeting_detail` 레이아웃 회귀

- 관리자/일반 멤버 레이아웃 분기를 넓게 건드리면 다른 탭까지 깨질 수 있다.
- 일반 멤버 데스크톱 UI는 세션 영역 visibility와 footer collapse를 분리해서 본다.
- 모달/패널 내용을 비동기로 불러올 때는, 이전 요청 응답이 늦게 도착해 최신 화면을 덮어쓰지 않도록 요청 순번 또는 취소 기준을 둔다.

### 4-3. 데이터 무결성 회귀

- 임시 합주실 처리와 `get_or_create` 경로는 실제 `PracticeRoom` 오염 위험이 있다.
- 추가 합주 저장 경로는 `ExtraPracticeSchedule`와 `RoomBlock` 원자성 이슈가 있다.
- 상태 전이, 저장 시그니처, 검증 기준을 클라/서버가 다르게 이해하면 재발성 버그가 생긴다.

이 영역을 수정할 때는 반드시 아래 문서를 먼저 본다.
- `docs/meeting_integrity_rules.md`
- `docs/meeting_process_state_machine.md`

---

## 5. 최소 검증 규칙

### 5-1. 기본 검증

- `A` 문서 전용: `git diff -- docs`
- `B` UI/클라이언트: `./.venv/bin/python manage.py check`
- `C` 서버 로직: `./.venv/bin/python manage.py check` + `./.venv/bin/python manage.py test pracapp.tests`
- `D` 상태/DB: `./.venv/bin/python manage.py check` + `./.venv/bin/python manage.py test pracapp.tests`

### 5-2. 추가 검증이 필요한 경우

- 새 static 파일 추가: `./.venv/bin/python manage.py collectstatic --noinput`
- 상태 전이 변경: 관련 회귀 시나리오를 `docs/meeting_regression_checklist.md` 기준으로 재점검
- 저장 로직 변경: `docs/meeting_integrity_rules.md`와 코드 설명이 일치하는지 재확인
- 중복 클릭 방어를 수정했다면: 같은 액션을 빠르게 연타해도 중복 요청이 나가지 않는지 확인
- 데모 템플릿/더미 생성 로직 변경: `./.venv/bin/python manage.py prepare_demo_cache` 또는 실제 `/demo/start/` 스모크 테스트까지 확인
- 상수값/파일명/기본 개수 변경: 관련 문서의 숫자, 파일명, 경로, enum 라벨까지 코드와 글자를 직접 대조

검증 없이 종료하지 않는다.

---

## 6. 문서 동기화 규칙

아래가 바뀌면 문서를 같이 갱신한다.

- 사용자에게 보이는 동작
- 버튼 위치/활성 조건
- 상태 전이
- 저장 규칙/검증 규칙/트랜잭션 경계
- 기본 상수값(개수, 파일명, seed 대상, 기본 경로)
- 화면 구조/CSS 책임
- 파일 크기와 탐색 난이도(대형 파일 변화)
- 자주 하는 수정 순서 템플릿이 바뀔 정도의 반복 작업 패턴

함께 갱신할 가능성이 높은 문서:
- `docs/meeting_handover.md`
- `docs/meeting_regression_checklist.md`
- `docs/meeting_ui_css_map.md`
- `docs/meeting_integrity_rules.md`
- `docs/large_files_overview.md`

---

## 7. 작업 중 기록 규칙

작업 종료 전까지 기다리지 말고, 아래 항목은 **발견 즉시** 관련 문서에 반영한다.

- 기존 문서 설명과 코드가 충돌하는 사실을 확인했을 때
- 새 회귀 위험이나 사용자성 버그 패턴을 확인했을 때
- 대형 파일에서 반복적으로 터지는 수정 금지 패턴을 확인했을 때
- 저장/무결성/트랜잭션 관련 새 위험을 확인했을 때

기록 원칙:
- 기능 기준이 바뀌면 관련 SSOT에 바로 반영한다.
- 아직 해결하지 않은 위험이면 `주의`, `알려진 위험`, `수정 시 금지` 같은 형태로라도 먼저 남긴다.
- 대형 파일 구조/위험 정보면 `docs/large_files_overview.md`에 바로 반영한다.
- 이번 세션 한정 메모가 아니라 다음 작업자도 알아야 하는 정보면 handoff만 남기지 말고 기준 문서에도 함께 남긴다.
- 같은 사용자 체감 이슈에 대해 패치를 1회 이상 시도했는데 재현되면, 추가 시도 전에 관련 SSOT에 `알려진 이슈`로 먼저 기록한다.
- 숫자/파일명/고정 문구가 바뀌었다면 “의미만 맞다”고 넘기지 말고, 문서의 literal 값도 코드와 같은 문자열인지 직접 맞춘다.

---

## 8. 문서 추가/정리 규칙

- 같은 주제의 기준 문서가 이미 있으면 새 파일을 만들지 말고 기존 문서에 흡수한다.
- 현재 기준이 아닌 문서는 루트에 두지 말고 `docs/archive/`로 보낸다.
- 새 문서를 만들면 `docs/README.md`의 역할표와 스타팅 맵 반영 여부를 확인한다.
- 아카이브 문서는 현재 구현의 단독 기준으로 사용하지 않는다.

### 8-1. 사용자 명시 요청 없이는 하지 말아야 할 변경

아래 변경은 사용자가 명시적으로 요구하지 않았으면, 안전 패치 명목으로 범위를 넓혀서 수행하지 않는다.

- 상태 플래그 의미 변경
- URL 경로 또는 라우트 이름 변경
- 모델 필드 추가/삭제/의미 변경
- 대형 템플릿의 구조적 리팩터링
- 기존 UX 흐름 재구성(버튼 순서, 모달 단계, 진입 플로우 재설계)
- 테스트 실패를 숨기기 위한 기준 완화

원칙:
- 이런 변경이 필요해 보여도 먼저 사용자 요구 범위인지 확인한다.
- 범위를 넓혀야 한다면 `C` 또는 `D` 등급으로 다시 분류하고 SSOT를 재확인한다.

---

## 9. 작업 종료 체크

1. 수정한 기능의 SSOT 문서가 여전히 코드와 일치하는지 확인한다.
2. 회귀 체크 기준이 바뀌었으면 `docs/meeting_regression_checklist.md`를 갱신한다.
3. 저장/무결성 정책이 바뀌었으면 `docs/meeting_integrity_rules.md`를 갱신한다.
4. 화면 구조 책임이 바뀌었으면 관련 UI 문서를 갱신한다.
5. `500`줄 이상 파일이 추가되거나 대형 파일 규모가 크게 달라졌으면 `docs/large_files_overview.md`를 갱신한다.
6. 문서 간 링크와 참조 경로가 깨지지 않았는지 확인한다.
7. `C` 또는 `D` 등급 작업, 대형 파일 수정, 릴리즈 직전이면 문서-코드 정합성 점검을 한 번 더 수행한다.
8. 다음 작업자에게 넘겨야 하면 `docs/session_handoff_template.md` 형식으로 세션 handoff를 남긴다.

정합성 점검 최소 항목:
- SSOT의 함수명, URL, 상태 코드, 모델 속성명이 현재 코드와 일치하는지 확인한다.
- `docs/meeting_reference_pages.md`와 `pracsite/urls.py`가 일치하는지 확인한다.
- 테스트 실행 경로와 최소 검증 규칙이 현재 저장소 구조와 맞는지 확인한다.

이 문서의 목적은 AI가 "빨리" 움직이는 것이 아니라, "맥락 없이 들어와도 같은 실수를 반복하지 않게" 만드는 것이다.
