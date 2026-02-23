# Meeting Required Reference Pages

## 필수 화면(템플릿)
- `pracapp/templates/pracapp/meeting_detail.html`
  - 선곡/세션 지원/배정/현황판/AJAX 상호작용의 중심 화면
- `pracapp/templates/pracapp/match_result.html`
  - 매칭 결과/예약반영/최종 공유 관련 화면

## 필수 뷰
- `pracapp/views/meeting_views.py`
  - `MeetingDetailView`
  - meeting 참여/방 생성/현황판 데이터/API
- `pracapp/views/matching_views.py`
  - 매칭 실행/결과 저장/예약반영/최종 공유/최종 확정/리셋
- `pracapp/views/song_session_views.py`
  - 세션 지원/배정/지원자 관리

## 필수 모델
- `pracapp/models.py`
  - `Meeting`
  - `Song`
  - `Session`
  - `MeetingScheduleConfirmation`

## 필수 URL (빠른 탐색)
참조: `pracsite/urls.py`
- `meeting/<uuid:pk>/` -> `meeting_detail`
- `meeting/<uuid:meeting_id>/match/run/` -> `schedule_match_run`
- `meeting/<uuid:meeting_id>/match/save/` -> `schedule_save_result`
- `meeting/<uuid:meeting_id>/final/prepare/` -> `schedule_final_prepare`
- `meeting/<uuid:meeting_id>/final/` -> `schedule_final`
- `meeting/<uuid:meeting_id>/final/ack/` -> `schedule_final_acknowledge`
- `schedule/confirm/` -> `schedule_confirm`
- `meeting/<uuid:meeting_id>/final/reset/` -> `schedule_final_reset`
- `session/<uuid:session_id>/apply` -> `session_apply`
- `session/<uuid:session_id>/manage-applicant/<uuid:user_id>/` -> `session_manage_applicant`

