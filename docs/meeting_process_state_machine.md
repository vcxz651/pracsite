# Meeting Process State Machine

선행 읽기:
1. `docs/project_overview.md`
2. `docs/ai_working_rules.md`
3. `docs/ai_task_triage_checklist.md`

이 문서는 `Meeting` 상태 해석 기준이다. 버튼 문구나 화면 노출 상태로 플래그 의미를 추정하지 말고, 상태 전이는 이 문서를 기준으로 본다.

## 목적
선곡회의의 일정 처리 단계를 운영/개발 관점에서 동일하게 이해하기 위한 문서.

## 핵심 상태 플래그 (Meeting)
- `is_schedule_coordinating`
- `is_booking_in_progress`
- `is_final_schedule_released`
- `is_final_schedule_confirmed`
- `schedule_version`

참조: `pracapp/models.py` (`Meeting.schedule_stage_code`, `Meeting.schedule_stage_label`)

## 상태 해석
- `DRAFT_MATCHING`
  - 조건: `is_schedule_coordinating=True`, `is_booking_in_progress=False`
  - 의미: 자동/수동 매칭 결과를 조정 중
- `BOOKING_IN_PROGRESS`
  - 조건: `is_final_schedule_released=True`, `is_booking_in_progress=True`, `is_final_schedule_confirmed=False`
  - 의미: 실제 합주실 예약 반영 단계
- `RELEASED_FOR_REVIEW`
  - 조건: `is_schedule_coordinating=False`, `is_final_schedule_released=True`, `is_final_schedule_confirmed=False`
  - 의미: 최종안 공유됨(멤버 확인 수집)
- `FINAL_CONFIRMED`
  - 조건: `is_final_schedule_confirmed=True`
  - 의미: 최종 확정, 변경 금지 단계

## 주요 전이
- 매칭 실행/저장 시작
  - 관련: `schedule_match_run`, `schedule_save_result`
  - 결과: 조율 상태 진입 (`is_schedule_coordinating=True`)
- 최종 공유
  - 관련: `schedule_final_prepare`
  - 결과: `is_final_schedule_released=True`, `is_schedule_coordinating=False`
- 예약 반영 단계 진입
  - 관련: `schedule_booking_start`
  - 결과: `is_booking_in_progress=True` (공유본 기준으로 예약 편집 단계 진입)
- 최종 저장
  - 관련: `schedule_save_result` (final save)
  - 결과: `PracticeSchedule` 재기록, 필요 시 `is_final_schedule_confirmed=True`, 조율/예약중 해제
- 최종 확정
  - 관련: `schedule_confirm`
  - 결과: 개인 일정 확인/제출 흐름용 별도 화면. 미팅 스케줄 확정의 단일 진입점으로 간주하지 않음.
- 최종 리셋
  - 관련: `schedule_final_reset`
  - 결과: confirmation/공개/예약중/조율 플래그 초기화

## 버전/확인(ack) 규칙
- 멤버 확인은 `MeetingScheduleConfirmation.version`과 meeting의 `schedule_version`이 일치해야 유효
- 새 최종안 공유 시 `schedule_version`이 증가하므로 이전 확인은 자동으로 구버전이 됨
