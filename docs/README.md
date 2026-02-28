# Docs Protocol

이 문서는 **아무 사전 지식 없는 다음 AI 작업자**가 바로 작업에 착수할 수 있도록,
`docs/`를 어떤 순서로 읽고, 어떤 문서를 기준으로 판단하고, 작업 종료 시 어떻게 정리할지를 정의한다.

---

## 1. 빠른 착수 절차

처음 들어온 작업자는 아래 순서로 시작한다.

1. 이 문서(`docs/README.md`)를 먼저 읽는다.
2. `docs/project_overview.md`로 프로젝트 전체 구조를 파악한다.
3. `docs/ai_working_rules.md`로 공통 가드레일을 확인한다.
4. `docs/ai_task_triage_checklist.md`로 작업 유형을 먼저 분류한다.
5. 필요 시 `docs/ai_task_triage_checklist.md`의 `6. 반복 작업 플레이북`까지 확인한다.
6. 분류에 맞는 **단일 기준 문서(SSOT)** 를 먼저 읽는다.
7. 관련 코드 진입점은 `docs/meeting_reference_pages.md`로 확인한다.
8. 여기까지 읽은 뒤, **현재 문서 체계가 무맥락 AI 작업자에게 바로 착수 가능한 구조인지 30초 안에 빠르게 점검한다.**
9. 작업 후에는 이 문서의 `5. 작업 종료 프로토콜`에 따라 문서를 정리한다.

원칙:
- 문서를 다 읽고 시작하는 게 아니라, **작업 주제에 맞는 문서만 먼저 읽고 시작**한다.
- 같은 책임의 문서가 이미 있으면 새 문서를 만들지 않는다.
- 기능별 상세 판단 전에 `project_overview.md`, `ai_working_rules.md`, `ai_task_triage_checklist.md`로 공통 맥락과 작업 범주를 먼저 맞춘다.
- 변경 전에는 작업 위험도를 먼저 등급으로 정하고, 등급에 맞는 검증 범위를 잡는다.
- 기능 관련 판단은 동작 가능 여부만 보지 말고, UX(사용자 이해도, 클릭 수, 대기 체감, 실패처럼 느껴지는지)까지 함께 본다.

빠른 점검 기준:
- 지금 읽은 문서만으로 **이번 작업의 SSOT 1개가 바로 식별되는지** 확인한다.
- 스타팅 맵의 문서/코드 진입 순서가 실제 작업 경로와 크게 어긋나지 않는지 확인한다.
- 같은 책임의 문서가 2개 이상처럼 느껴지면, 작업 중 해당 문서 체계 충돌 여부를 같이 확인한다.

---

## 2. 작업 주제별 스타팅 맵

공통 선행 문서:
1. `docs/project_overview.md`
2. `docs/ai_working_rules.md`
3. `docs/ai_task_triage_checklist.md`
4. 필요 시 `docs/ai_task_triage_checklist.md`의 `6. 반복 작업 플레이북`

아래 스타팅 맵은 위 공통 문서를 먼저 읽었다는 전제로 본다.

### 2-1. 스케줄보드 / 매칭 / 예약 / 최종 일정

먼저 읽을 문서:
1. `docs/meeting_handover.md`
2. `docs/meeting_process_state_machine.md`
3. `docs/meeting_regression_checklist.md`
4. 필요 시 `docs/large_files_overview.md`

먼저 볼 코드:
1. `pracapp/templates/pracapp/match_result.html`
2. `pracapp/views/matching_views.py`
3. `pracapp/models.py`

주의:
- `match_result.html`은 초대형 파일이다. 작은 수정도 핸들러 중복/상태 꼬임을 만들 수 있다.
- 현재 조율 보드는 **룸슬롯 단일 모드**다. 예전 `일반/룸 보기` 전제를 다시 넣지 않는다.
- 예약 단계에서는 `booking_completed_keys`까지 dirty-state에 포함될 수 있다.

### 2-2. meeting_detail / 일반 멤버 UI / 세션 카드 레이아웃

먼저 읽을 문서:
1. `docs/meeting_ui_css_map.md`
2. `docs/meeting_regression_checklist.md`
3. 필요 시 `docs/meeting_handover.md`

먼저 볼 코드:
1. `pracapp/templates/pracapp/meeting_detail.html`
2. `pracapp/views/meeting_views.py`
3. 관련 AJAX가 있으면 `pracapp/views/song_session_views.py`

주의:
- 관리자/일반 멤버 레이아웃 분기는 `.manager-page` 기준으로 좁혀야 한다.
- 일반 멤버 데스크톱에서는 세션 칸 visibility와 footer collapse를 분리해서 봐야 한다.

### 2-3. 데모 페이지

먼저 읽을 문서:
1. `docs/demo_page_plan.md`
2. 필요 시 `docs/archive/demo_feedback_acceptance_2026-02-25.md`

먼저 볼 코드:
1. `pracapp/views/demo_views.py`
2. `pracapp/templates/pracapp/demo/` 하위 템플릿
3. `pracapp/static/pracapp/js/tutorial_demo.js`
4. `templates/base.html`

주의:
- 현재 기준은 **시나리오 선택 모달 + A/B/C + 자유 탐색 + 투어 안내 전용**이다.
- 과거 `시나리오 1/2/3 + /tutorial/ 연계` 방향으로 되돌리지 않는다.
- 데모 데이터는 세션 단위 격리가 기본이다.

### 2-4. 추가합주

먼저 읽을 문서:
1. `docs/extra_practice_feature.md`
2. `docs/extra_practice_ui_style.md`
3. 필요 시 `docs/meeting_regression_checklist.md`

먼저 볼 코드:
1. `pracapp/views/extra_practice_views.py`
2. `pracapp/templates/pracapp/extra_practice.html`
3. `pracapp/models.py` (`ExtraPracticeSchedule`)

주의:
- 추가합주는 본 매칭/예약 흐름과 별도 기능으로 본다.
- 상태/권한 규칙이 바뀌면 기능 문서도 같이 갱신해야 한다.
- `extra_practice_save`에서 `ExtraPracticeSchedule` + `RoomBlock` 생성이 **`transaction.atomic()` 없이** 수행된다. DB 저장 경로 수정 시 `docs/meeting_integrity_rules.md` §8 참조.

### 2-8. 홈 화면 / 개인 일정

먼저 읽을 문서:
1. `docs/meeting_handover.md` §27~29 (홈 보드 UX 변경 이력)
2. 필요 시 `docs/large_files_overview.md` (home_views.py, schedule_views.py 항목)

먼저 볼 코드:
1. `pracapp/templates/pracapp/home.html` (~900줄, 홈 주간보드)
2. `pracapp/views/home_views.py` (~620줄)
3. `pracapp/views/schedule_views.py` (~510줄, 개인 일정 블록 CRUD)
4. `pracapp/templates/pracapp/schedule_step2.html` (~1,020줄)
5. `pracapp/templates/pracapp/schedule_step3.html` (~830줄)

주의:
- 홈 보드 시간축은 "해당 주 내 최초 합주/개인일정 시작 ~ 최후 종료"로 압축된다. 고정 범위로 되돌리지 않는다.
- 개인일정 오버레이는 `RecurringBlock`, `OneOffBlock(is_generated=False)`, `RecurringException`을 직접 반영한다.
- 홈 팝오버는 `.floating-popover` 커스텀 팝오버를 사용한다. Bootstrap 기본 tooltip으로 되돌리지 않는다.

### 2-9. 배포 / 운영 / 장애 확인

먼저 읽을 문서:
1. `docs/deployment_runbook.md`
2. 작업 주제가 데모면 `docs/demo_page_plan.md`
3. 필요 시 `docs/ai_working_rules.md`

먼저 볼 코드:
1. `Procfile`
2. `scripts/release_web.sh`
3. `scripts/prewarm_demo.sh`
4. `scripts/post_deploy_check.sh`
5. 필요 시 `pracsite/settings.py`

주의:
- Railway 대시보드 설정을 감으로 믿지 말고, 저장소의 배포 기준 파일과 먼저 대조한다.
- `railway logs`는 스트리밍 명령이라, 같은 터미널에서 다른 명령을 이어 치지 않는다.
- 데모 장애는 앱 로그(Railway) 우선으로 보고, Supabase 로그는 DB 보조 신호로만 본다.

### 2-5. 데이터 무결성 / 상태 정책

먼저 읽을 문서:
1. `docs/meeting_integrity_rules.md`
2. `docs/meeting_process_state_machine.md`
3. `docs/meeting_handover.md`

먼저 볼 코드:
1. `pracapp/models.py`
2. `pracapp/views/matching_views.py`
3. `pracapp/views/meeting_views.py`
4. `pracapp/views/song_session_views.py`
5. `pracapp/views/extra_practice_views.py` — RoomBlock 원자성 이슈(§8) 관련

주의:
- 상태 전이, 시그니처, 저장 기준을 클라/서버가 다르게 이해하면 재발성 버그가 생긴다.
- 무결성 규칙을 위반하는 알려진 위험(`get_or_create` 오염, RoomBlock atomicity)은 `meeting_integrity_rules.md`에 기록되어 있다.

### 2-6. 바로 실행할 기본 커맨드

작업 시작 시 자주 쓰는 커맨드:

```bash
# 프로젝트 기본 점검
./.venv/bin/python manage.py check

# URL/뷰/템플릿 빠른 탐색
grep -RIn "schedule_booking_start" pracsite pracapp
grep -RIn "goBookingConfirmBtn" pracapp/templates/pracapp

# 대형 템플릿 구간 읽기
sed -n '1800,1950p' pracapp/templates/pracapp/match_result.html
sed -n '3500,3650p' pracapp/templates/pracapp/meeting_detail.html

# docs 참조 역추적
grep -RIn "meeting_handover.md\\|meeting_regression_checklist.md" docs
```

작업 종료 전 최소 커맨드:

```bash
# 서버사이드 회귀 검증 (31개 테스트, 약 5분)
./.venv/bin/python manage.py test pracapp.tests

# import/모델 정합성 점검
./.venv/bin/python manage.py check

# 문서 변경 범위 확인
git diff -- docs
```

원칙:
- 뷰/모델/비즈니스 로직을 수정했으면 `manage.py test`를 반드시 돌린다.
- 템플릿/CSS/JS만 수정했으면 `manage.py check`로 충분하다.
- 문서를 손댔으면 `git diff -- docs`로 문서 변경 범위를 확인한다.
- 새 static 파일(이미지/영상 등)을 추가했으면 `manage.py collectstatic --noinput` 후 `manage.py test` 순서로 실행한다.

### 2-7. 작업 유형별 즉시 적용 예시

#### 예시 A: 예약 버튼/임시 저장 활성 조건 수정

1. `docs/meeting_handover.md` 먼저 읽기
2. `docs/meeting_regression_checklist.md`에서 예약 단계 항목 확인
3. `pracapp/templates/pracapp/match_result.html`에서 관련 버튼 ID 검색
4. 수정 후 `./.venv/bin/python manage.py check`
5. 동작 기준이 바뀌었으면 `meeting_handover.md`와 `meeting_regression_checklist.md` 같이 갱신

#### 예시 B: 일반 멤버 `meeting_detail` 레이아웃 수정

1. `docs/meeting_ui_css_map.md` 먼저 읽기
2. `docs/meeting_regression_checklist.md`의 `meeting_detail UI` 항목 확인
3. `pracapp/templates/pracapp/meeting_detail.html` 수정
4. 스타일 책임이 바뀌었으면 `meeting_ui_css_map.md` 갱신

#### 예시 C: 데모 시나리오/모달 흐름 수정

1. `docs/demo_page_plan.md` 먼저 읽기
2. 필요 시 `docs/archive/demo_feedback_acceptance_2026-02-25.md` 참고
3. `pracapp/views/demo_views.py`, `pracapp/templates/pracapp/demo/`, `tutorial_demo.js` 순서로 확인
4. 시나리오 기준이 바뀌면 `demo_page_plan.md`를 먼저 갱신

---

## 3. 현재 문서 역할표 (SSOT 기준)

### 3-1. 루트 `docs/`에 남겨야 하는 문서

| 문서 | 단일 기준 역할 |
|---|---|
| `docs/project_overview.md` | 프로젝트 전체 구조/도메인/진입점 개요 |
| `docs/ai_working_rules.md` | 무맥락 AI 작업자 공통 가드레일 |
| `docs/ai_task_triage_checklist.md` | 작업 유형 빠른 분류 체크리스트 |
| `docs/session_handoff_template.md` | 세션 종료 handoff 템플릿 |
| `docs/meeting_handover.md` | 미팅/매칭/예약/최종 일정의 실무 단일 기준 |
| `docs/meeting_process_state_machine.md` | `Meeting` 상태 전이 기준 |
| `docs/meeting_regression_checklist.md` | 회귀 점검 기준 |
| `docs/meeting_reference_pages.md` | 빠른 코드 진입점 |
| `docs/meeting_ui_css_map.md` | `meeting_detail` CSS 책임 범위 |
| `docs/meeting_integrity_rules.md` | 데이터 무결성 원칙 |
| `docs/demo_page_plan.md` | 현재 데모 단일 기준 |
| `docs/deployment_runbook.md` | 배포/운영/장애 확인 공통 런북 |
| `docs/extra_practice_feature.md` | 추가합주 기능 기준 |
| `docs/extra_practice_ui_style.md` | 추가합주 스타일 기준 |
| `docs/dummy_name_pool.md` | 더미 이름 기준 |
| `docs/large_files_overview.md` | 탐색 보조 문서(근사치 참고용) |

### 3-2. `docs/archive/`에 있어야 하는 문서

| 문서 | 이유 |
|---|---|
| `docs/archive/demo_feedback_acceptance_2026-02-25.md` | 과거 데모 피드백 수용 이력 |
| `docs/archive/match_result_refactor_backlog.md` | 리팩토링 백로그 |
| `docs/archive/tutorial_plan.md` | 보류된 과거 튜토리얼 기획 |

원칙:
- 현재 구현 판단의 기준 문서는 루트에 둔다.
- 과거 기획/이력/백로그는 `archive/`로 보낸다.

---

## 4. 변경 등급과 작업 중 기록 프로토콜

### 4-1. 변경 등급

작업 시작 전에 이번 변경의 위험도를 먼저 등급으로 정한다.

- `A` 문서 전용: `docs/`만 수정, 코드 동작은 바꾸지 않음
- `B` UI/클라이언트: 템플릿, CSS, 인라인 JS, 정적 프론트 동작만 수정
- `C` 서버 로직: 뷰, 검증, AJAX 응답, 서버 분기 수정
- `D` 상태/DB: 모델 필드, 상태 전이, 저장 규칙, 트랜잭션 경계 수정

등급별 최소 검증:
- `A`: `git diff -- docs`
- `B`: `./.venv/bin/python manage.py check`
- `C`: `./.venv/bin/python manage.py check` + `./.venv/bin/python manage.py test pracapp.tests`
- `D`: `./.venv/bin/python manage.py check` + `./.venv/bin/python manage.py test pracapp.tests`

원칙:
- 한 작업에 여러 등급이 섞이면 더 높은 등급 기준을 따른다.
- `C` 이상이면 관련 SSOT와 회귀 체크 문서 갱신 여부를 먼저 판단한다.
- `D`는 사용자 명시 요구 없이 범위를 넓히지 않는다.

### 4-2. 작업 중 기록 프로토콜

작업 중 아래 상황이 발생하면, 종료 시점까지 미루지 말고 관련 문서에 바로 기록한다.

1. 문서와 코드의 불일치를 확인했을 때
2. 새 회귀 위험이나 반복 버그 패턴을 발견했을 때
3. 대형 파일 수정 금지 패턴이나 구조 메모가 추가로 필요해졌을 때
4. 저장/무결성/트랜잭션 관련 새 위험을 발견했을 때

기록 위치 원칙:
- 기능 기준 변경/주의: 해당 SSOT 문서
- 회귀 검증 기준 변경: `docs/meeting_regression_checklist.md`
- 화면 구조/CSS 책임 변경: `docs/meeting_ui_css_map.md`
- 저장/무결성 위험: `docs/meeting_integrity_rules.md`
- 대형 파일 구조/금지 패턴: `docs/large_files_overview.md`
- 세션 단위 요약: 작업 종료 시 `docs/session_handoff_template.md` 형식

원칙:
- 다음 작업자도 알아야 하는 정보면 handoff에만 남기지 말고 기준 문서에도 남긴다.
- 아직 해결하지 못한 위험도 `주의` 또는 `알려진 위험` 형태로 먼저 기록한다.
- 같은 사용자 체감 이슈에 대해 패치를 1회 이상 시도했는데 재현되면, 추가 시도 전에 관련 SSOT에 먼저 기록한다.
- 숫자, 파일명, 기본 개수, CSV/경로 같은 literal 값이 바뀌면 문서 설명도 같은 값으로 즉시 맞춘다.

---

## 5. 작업 종료 프로토콜

### 5-1. 먼저 판단할 것

작업을 마칠 때는 아래 순서로 판단한다.

1. 이번 작업이 **동작/정책/UX/데이터 모델**을 바꿨는가
2. 바뀐 내용이 기존 문서의 **단일 기준(SSOT)** 을 흔드는가
3. 기존 문서가 없으면 새 문서가 필요한가, 아니면 기존 문서 한 곳에 흡수하는 게 맞는가
4. 기존 문서가 더 이상 현재 기준이 아니면 루트에 둘지, `docs/archive/`로 내릴지

### 5-2. 문서를 업데이트해야 하는 경우

다음 중 하나라도 해당하면 문서를 갱신한다.

- 사용자에게 보이는 동작이 바뀜
- 버튼 위치/활성 조건/상태 전이가 바뀜
- 백엔드 저장 기준, 시그니처, 검증 규칙이 바뀜
- 상수값(개수, 파일명, 기본값, 경로)이 바뀜
- 단일 기준 문서의 설명이 더 이상 코드와 일치하지 않음
- 새 기능이 추가되어 운영 규칙이나 회귀 체크가 필요함

### 5-3. 작업 종료 체크리스트

1. 바뀐 기능과 직접 연결된 단일 기준 문서를 찾는다.
2. 이번 작업의 변경 등급(`A`~`D`)과 실제 수정 범위가 일치하는지 다시 확인한다.
3. 해당 문서의 설명, 상태, 예시, 경로를 코드와 맞춘다.
4. 회귀 체크가 바뀌면 `docs/meeting_regression_checklist.md`를 같이 갱신한다.
5. 화면 구조가 바뀌면 `docs/meeting_ui_css_map.md` 또는 관련 스타일 문서를 같이 갱신한다.
6. **데이터 저장/무결성/트랜잭션 경계가 바뀌었으면 `docs/meeting_integrity_rules.md`를 갱신한다.**
7. **500줄 이상 파일이 추가되거나, 기존 파일의 라인 수가 크게 바뀌었으면 `docs/large_files_overview.md`를 갱신한다.**
8. **변경 등급이 `C` 이상이면 `manage.py test pracapp.tests`를 돌린다. 새 정책이 추가되면 대응 테스트도 함께 추가한다.**
9. 과거 기준이 된 문서는 루트에 남기지 말고 `docs/archive/`로 이동하거나, 최소한 아카이브 표기를 추가한다.
10. 문서 간 참조 경로가 깨지지 않았는지 확인한다.
11. 동일 주제 문서가 2개 이상 서로 다른 기준을 말하지 않는지 확인한다.
12. 정기 정합성 점검 대상(SSOT, URL, 상태 코드, 테스트 경로)에 새 변경이 생겼으면 `5-5. 정기 정합성 점검 루틴` 기준으로 재점검한다.
13. **이번 세션의 실제 작업 기록 기준으로, 현재 문서 체계가 무맥락 AI에게 비효율적이거나 헷갈렸던 지점이 있었는지 먼저 판단한다.**
14. 문서 체계 피드백이 있으면 handoff에만 남기지 말고, 기존 SSOT/인덱스 문서에 흡수할지 먼저 결정한다.
15. 다음 AI에게 넘겨야 하는 작업이면 `docs/session_handoff_template.md` 형식으로 handoff를 정리한다.

문서 체계 피드백 판단 기준:
- SSOT를 찾는 데 문서 왕복이 2회 이상 필요했는가
- 스타팅 맵이 실제 코드 진입점과 달라서 추가 탐색이 필요했는가
- 같은 주제를 설명하는 문서가 둘 이상처럼 느껴졌는가
- 이번 세션에서 새로 알게 된 반복 위험/운영 절차가 있는데, 현재 문서 구조상 놓치기 쉬운가

원칙:
- 문서 체계가 충분히 작동했다면 “문제 없음”으로 끝내도 된다.
- 피드백이 있으면 새 문서를 만들기보다, 먼저 기존 SSOT나 `docs/README.md`에 흡수 가능한지 본다.

### 5-4. 하지 말아야 할 것

- 같은 주제의 새 문서를 반복 생성해서 기준을 분산시키는 것
- 현재와 안 맞는 문서를 루트에 두고 방치하는 것
- 과거 문서를 현재 기준처럼 보이게 두는 것
- 코드 변경은 컸는데 회귀 체크 문서를 안 고치는 것
- 뷰/모델 로직을 바꿨는데 테스트가 깨지는지 확인하지 않는 것

### 5-5. 정기 정합성 점검 루틴

아래 경우에는 기능 작업과 별도로 문서-코드 정합성 점검을 수행한다.

- `C` 또는 `D` 등급 작업을 마친 뒤
- 대형 파일(`match_result.html`, `meeting_detail.html`, `matching_views.py`, `meeting_views.py`) 수정 뒤
- 릴리즈 전 또는 사용자에게 넘기기 전

최소 점검 항목:
1. 관련 SSOT의 함수명, URL, 상태 코드, 모델 속성명이 실제 코드와 일치하는지 확인한다.
2. `pracsite/urls.py`의 라우트와 `docs/meeting_reference_pages.md`가 일치하는지 확인한다.
3. `docs/meeting_process_state_machine.md`의 상태 전이 설명과 `models.py`/관련 뷰가 일치하는지 확인한다.
4. 테스트 실행 경로와 최소 검증 규칙이 현재 저장소 구조와 맞는지 확인한다.

원칙:
- 정합성 점검에서 새 불일치를 찾으면 즉시 관련 SSOT를 수정한다.
- 점검 사실만 handoff에 남기지 말고, 바뀐 기준은 루트 `docs/` 문서에 반영한다.

---
