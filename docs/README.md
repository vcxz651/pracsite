# Docs Protocol

이 문서는 **아무 사전 지식 없는 다음 AI 작업자**가 바로 작업에 착수할 수 있도록,
`docs/`를 어떤 순서로 읽고, 어떤 문서를 기준으로 판단하고, 작업 종료 시 어떻게 정리할지를 정의한다.

---

## 1. 빠른 착수 절차

처음 들어온 작업자는 아래 순서로 시작한다.

1. 이 문서(`docs/README.md`)를 먼저 읽는다.
2. 작업 주제를 분류한다.
3. 분류에 맞는 **단일 기준 문서(SSOT)** 를 먼저 읽는다.
4. 관련 코드 진입점은 `docs/meeting_reference_pages.md`로 확인한다.
5. 작업 후에는 이 문서의 `4. 작업 종료 프로토콜`에 따라 문서를 정리한다.

원칙:
- 문서를 다 읽고 시작하는 게 아니라, **작업 주제에 맞는 문서만 먼저 읽고 시작**한다.
- 같은 책임의 문서가 이미 있으면 새 문서를 만들지 않는다.

---

## 2. 작업 주제별 스타팅 맵

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
./.venv/bin/python manage.py check
git diff -- docs
```

원칙:
- 기능 수정 후에는 최소 `manage.py check`는 항상 돌린다.
- 문서를 손댔으면 `git diff -- docs`로 문서 변경 범위를 확인한다.

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
| `docs/meeting_handover.md` | 미팅/매칭/예약/최종 일정의 실무 단일 기준 |
| `docs/meeting_process_state_machine.md` | `Meeting` 상태 전이 기준 |
| `docs/meeting_regression_checklist.md` | 회귀 점검 기준 |
| `docs/meeting_reference_pages.md` | 빠른 코드 진입점 |
| `docs/meeting_ui_css_map.md` | `meeting_detail` CSS 책임 범위 |
| `docs/meeting_integrity_rules.md` | 데이터 무결성 원칙 |
| `docs/demo_page_plan.md` | 현재 데모 단일 기준 |
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

## 4. 작업 종료 프로토콜

### 4-1. 먼저 판단할 것

작업을 마칠 때는 아래 순서로 판단한다.

1. 이번 작업이 **동작/정책/UX/데이터 모델**을 바꿨는가
2. 바뀐 내용이 기존 문서의 **단일 기준(SSOT)** 을 흔드는가
3. 기존 문서가 없으면 새 문서가 필요한가, 아니면 기존 문서 한 곳에 흡수하는 게 맞는가
4. 기존 문서가 더 이상 현재 기준이 아니면 루트에 둘지, `docs/archive/`로 내릴지

### 4-2. 문서를 업데이트해야 하는 경우

다음 중 하나라도 해당하면 문서를 갱신한다.

- 사용자에게 보이는 동작이 바뀜
- 버튼 위치/활성 조건/상태 전이가 바뀜
- 백엔드 저장 기준, 시그니처, 검증 규칙이 바뀜
- 단일 기준 문서의 설명이 더 이상 코드와 일치하지 않음
- 새 기능이 추가되어 운영 규칙이나 회귀 체크가 필요함

### 4-3. 작업 종료 체크리스트

1. 바뀐 기능과 직접 연결된 단일 기준 문서를 찾는다.
2. 해당 문서의 설명, 상태, 예시, 경로를 코드와 맞춘다.
3. 회귀 체크가 바뀌면 `docs/meeting_regression_checklist.md`를 같이 갱신한다.
4. 화면 구조가 바뀌면 `docs/meeting_ui_css_map.md` 또는 관련 스타일 문서를 같이 갱신한다.
5. **데이터 저장/무결성/트랜잭션 경계가 바뀌었으면 `docs/meeting_integrity_rules.md`를 갱신한다.**
6. **500줄 이상 파일이 추가되거나, 기존 파일의 라인 수가 크게 바뀌었으면 `docs/large_files_overview.md`를 갱신한다.**
7. 과거 기준이 된 문서는 루트에 남기지 말고 `docs/archive/`로 이동하거나, 최소한 아카이브 표기를 추가한다.
8. 문서 간 참조 경로가 깨지지 않았는지 확인한다.
9. 동일 주제 문서가 2개 이상 서로 다른 기준을 말하지 않는지 확인한다.

### 4-4. 하지 말아야 할 것

- 같은 주제의 새 문서를 반복 생성해서 기준을 분산시키는 것
- 현재와 안 맞는 문서를 루트에 두고 방치하는 것
- 과거 문서를 현재 기준처럼 보이게 두는 것
- 코드 변경은 컸는데 회귀 체크 문서를 안 고치는 것

---

