# Meeting Required Reference Pages

선행 읽기:
1. `docs/project_overview.md`
2. `docs/ai_working_rules.md`
3. `docs/ai_task_triage_checklist.md`

이 문서는 빠른 코드 진입점 문서다.
특정 작업에 들어갈 때 "어느 화면에서 시작해서 어떤 URL, 뷰, 모델로 이어지는지"를 짧게 찾는 용도로 사용한다.

원칙:
- 상세 정책 판단은 이 문서가 아니라 기능별 SSOT 문서에서 한다.
- 이 문서는 화면-URL-뷰-모델 연결을 빠르게 추적하는 용도다.

---

## 빠른 기능 흐름표

### 1. 미팅 상세 / 세션 지원 / 참가자 관리

- 시작 화면: `pracapp/templates/pracapp/meeting_detail.html`
- 주요 URL:
  - `meeting/<uuid:pk>/` -> `meeting_detail`
  - `session/<uuid:session_id>/apply` -> `session_apply`
  - `session/<uuid:session_id>/manage-applicant/<uuid:user_id>/` -> `session_manage_applicant`
- 주요 뷰:
  - `pracapp/views/meeting_views.py`
  - `pracapp/views/song_session_views.py`
- 주요 모델:
  - `Meeting`
  - `Song`
  - `Session`
- 먼저 볼 때의 질문:
  - 이 변경이 곡/세션 카드 표시 문제인가?
  - 세션 지원/배정 규칙 문제인가?
  - 참가자 승인/권한 문제인가?

### 2. 매칭 실행 / 조율 / 예약 / 최종 일정

- 시작 화면: `pracapp/templates/pracapp/match_result.html`
- 주요 URL:
  - `meeting/<uuid:meeting_id>/match/run/` -> `schedule_match_run`
  - `meeting/<uuid:meeting_id>/match/work-draft/save/` -> `schedule_match_work_draft_save`
  - `meeting/<uuid:meeting_id>/match/save/` -> `schedule_save_result`
  - `meeting/<uuid:meeting_id>/final/prepare/` -> `schedule_final_prepare`
  - `meeting/<uuid:meeting_id>/final/booking/start/` -> `schedule_booking_start`
  - `meeting/<uuid:meeting_id>/final/` -> `schedule_final`
  - `meeting/<uuid:meeting_id>/final/ack/` -> `schedule_final_acknowledge`
  - `meeting/<uuid:meeting_id>/final/reset/` -> `schedule_final_reset`
- 주요 뷰:
  - `pracapp/views/matching_views.py`
- 보조 뷰:
  - `pracapp/views/schedule_views.py` (`schedule_confirm`)
- 주요 모델:
  - `Meeting`
  - `MeetingWorkDraft`
  - `MeetingFinalDraft`
  - `MeetingScheduleConfirmation`
- 먼저 볼 때의 질문:
  - 이 변경이 프론트 보드 동작인가, 서버 저장 규칙인가?
  - 조율 단계인지, 예약 단계인지, 최종 확정 단계인지?
  - `match_result.html` UI 문제인지 `matching_views.py` 검증 문제인지?
- 빠른 착수 팁:
  - 버튼 활성/비활성, 배너, 안내 문구 수정이면 `match_result.html`의 상단 액션 영역과 인라인 JS부터 본다.
  - 저장 거부/409 조건까지 바뀌면 `matching_views.py`의 해당 엔드포인트 검증을 바로 함께 본다.

### 3. 홈 화면 / 개인 일정

- 시작 화면:
  - `pracapp/templates/pracapp/home.html`
  - `pracapp/templates/pracapp/schedule_step2.html`
  - `pracapp/templates/pracapp/schedule_step3.html`
- 주요 URL:
  - `pracsite/urls.py` 내 `/schedule/` 관련 라우트
  - `pracsite/urls.py` 내 홈 관련 라우트
- 주요 뷰:
  - `pracapp/views/home_views.py`
  - `pracapp/views/schedule_views.py`
- 주요 모델:
  - `RecurringBlock`
  - `OneOffBlock`
  - `RecurringException`
- 먼저 볼 때의 질문:
  - 이 변경이 개인 가용 시간 입력 문제인가?
  - 홈 주간보드 렌더링 문제인가?
  - 일정 오버레이/팝오버 문제인가?

### 4. 데모 페이지

- 시작 화면: `pracapp/templates/pracapp/demo/`
- 주요 URL:
  - `demo/` -> `demo_home`
  - `demo/dashboard/` -> `demo_dashboard`
  - `demo/start/` -> `demo_start`
  - `demo/scenario/<int:scenario>/` -> `demo_scenario`
  - `demo/switch-role/` -> `demo_switch_role`
  - `demo/exit/` -> `demo_exit`
- 주요 뷰:
  - `pracapp/views/demo_views.py`
- 주요 모델/데이터:
  - 데모 전용 세션 격리 데이터
- 먼저 볼 때의 질문:
  - 시나리오 선택 모달 문제인가?
  - A/B/C 시나리오 흐름 문제인가?
  - 투어 안내/자유 탐색 문제인가?
- 빠른 착수 팁:
  - 모달 문구/배치/첫 진입 노출 순서 수정이면 데모 템플릿과 `tutorial_demo.js`를 먼저 본다.
  - 시나리오 데이터 세팅, 역할 전환, 세션 격리 규칙이 바뀌면 `demo_views.py`를 바로 함께 본다.

### 5. 추가 합주

- 시작 화면: `pracapp/templates/pracapp/extra_practice.html`
- 주요 URL:
  - `pracsite/urls.py` 내 `extra-practice` 관련 라우트
- 주요 뷰:
  - `pracapp/views/extra_practice_views.py`
- 주요 모델:
  - `ExtraPracticeSchedule`
  - `RoomBlock`
- 먼저 볼 때의 질문:
  - 보드 렌더링 문제인가?
  - 저장/삭제 문제인가?
  - 합주실 불가 시간 반영 문제인가?
- 빠른 착수 팁:
  - 저장/삭제 정합성 문제면 `extra_practice_views.py`에서 `ExtraPracticeSchedule`와 `RoomBlock` 생성/삭제가 함께 처리되는지 먼저 본다.
  - 부분 성공/경합 의심이면 `transaction.atomic()` 경계부터 확인한다.

---

## 필수 화면(템플릿)
- `pracapp/templates/pracapp/meeting_detail.html`
  - 선곡/세션 지원/배정/현황판/AJAX 상호작용의 중심 화면
- `pracapp/templates/pracapp/match_result.html`
  - 매칭 결과/예약 단계/최종 공유 관련 화면
- `pracapp/templates/pracapp/meeting_participant_manage.html`
  - 참가자 관리 모달 (승인/거절/매니저 임명/해제/제외)
  - regression checklist §D 체크 대상. `meeting_views.py` 내 참가자 관련 API와 연동.

## 필수 뷰
- `pracapp/views/meeting_views.py`
  - `MeetingDetailView`
  - meeting 참여/방 생성/현황판 데이터/API
- `pracapp/views/matching_views.py`
  - 매칭 실행/결과 저장/공유/예약 진입/최종 확정/리셋
- `pracapp/views/schedule_views.py`
  - `schedule_confirm`
  - 개인 일정 확정/제출 관련 처리
- `pracapp/views/song_session_views.py`
  - 세션 지원/배정/지원자 관리

## 필수 모델
- `pracapp/models.py`
  - `Meeting`
  - `Song`
  - `Session`
  - `MeetingFinalDraft`
  - `MeetingWorkDraft`
  - `MeetingScheduleConfirmation`

## 필수 URL (빠른 탐색)
참조: `pracsite/urls.py`
- `meeting/<uuid:pk>/` -> `meeting_detail`
- `meeting/<uuid:meeting_id>/match/run/` -> `schedule_match_run`
- `meeting/<uuid:meeting_id>/match/work-draft/save/` -> `schedule_match_work_draft_save`
- `meeting/<uuid:meeting_id>/match/save/` -> `schedule_save_result`
- `meeting/<uuid:meeting_id>/final/prepare/` -> `schedule_final_prepare`
- `meeting/<uuid:meeting_id>/final/booking/start/` -> `schedule_booking_start`
- `meeting/<uuid:meeting_id>/final/` -> `schedule_final`
- `meeting/<uuid:meeting_id>/final/ack/` -> `schedule_final_acknowledge`
- `schedule/confirm/` -> `schedule_confirm` (`pracapp/views/schedule_views.py`)
- `meeting/<uuid:meeting_id>/final/reset/` -> `schedule_final_reset`
- `session/<uuid:session_id>/apply` -> `session_apply`
- `session/<uuid:session_id>/manage-applicant/<uuid:user_id>/` -> `session_manage_applicant`
