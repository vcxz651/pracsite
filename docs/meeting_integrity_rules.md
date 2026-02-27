# Meeting Data Integrity Rules

## 1. 임시 합주실(Temporary Room) 정책
- 임시 합주실은 "빈값 방지"를 위한 보조 개념이어야 함
- 임시 합주실 생성/사용이 실제 합주실 모델(`PracticeRoom`)의 의미를 오염하면 안 됨
- 예약 확정 이전의 임시 값은 운영상 가변 데이터로 취급
- **[알려진 위험]** `matching_views.py` 임시합주실 처리에서 `PracticeRoom.get_or_create(band=..., name=..., location=...)` 호출 시, 같은 이름/위치의 영구 합주실이 이미 존재하면 `is_temporary=True`로 강제 업데이트될 수 있음. 이 코드를 수정하거나 인근 로직을 건드릴 때는 반드시 이 경로를 확인한다. 근본 해결은 임시합주실 생성 경로에서 명시적 `create` + 고유 prefix를 사용하는 것.

## 2. 세션 배정/지원 무결성
- 배정된 세션은 지원 취소 불가
- 배정/지원 상태가 어긋나는(배정은 남고 지원만 사라지는) 상태를 허용하지 않음
- 관련 구현: `pracapp/views/song_session_views.py`
  - `session_apply`
  - `session_manage_applicant`

## 3. 최종 확정 게이트
- `is_final_schedule_confirmed=True` 이후에는 편집/매칭/지원 관련 변경 차단
- `is_final_schedule_released=True` 상태에서도 주요 변경은 제한
- 관련 공통 함수: final lock 검사 로직 (`meeting_views.py`, `matching_views.py`, `song_session_views.py`)

## 4. 공유/확정 전 버전 일치
- 최종 확정 전 멤버 확인은 현재 `schedule_version` 기준으로 집계
- 구버전 확인 수는 확정 근거에서 제외
- 관련 모델: `MeetingScheduleConfirmation`

## 5. 운영 원칙 (사용자 입력 누락 대응)
- 공유/예약 단계에서 "미입력 불가능 일정"을 추가 수렴하지 않는 운영을 기본으로 함
- 실무 원칙: 입력 누락으로 인한 불가능은 사용자 책임으로 간주
- 이유: 예약 타이밍 손실과 무한 재조정 루프 방지

## 6. 결과 지표 단일 진실원(SSOT)
- 동일 화면의 동일 지표(성공 곡 수, 실패 목록, 주차별 미배치)는 같은 데이터 소스에서 계산해야 한다.
- 금지: 서버 초기값과 프론트 재계산값을 병렬로 유지하여 서로 다른 숫자를 노출하는 구조.
- 권장: `weeks[].failed_items`를 기준으로 실패 관련 파생 지표를 일관 계산.

## 7. 공간 부족 사유 노출 규칙
- 현재 보드 내부 점유 사유(같은 미팅)는 공간 부족 사유 텍스트로 노출하지 않는다.
- 외부 미팅 요인만 `[미팅 이름] - 곡명`으로 표시한다.
- RoomBlock 수동 설정은 `예약 불가`로 유지한다.

## 8. RoomBlock 생성 원자성 규칙
- `ExtraPracticeSchedule`과 그에 대응하는 `RoomBlock`은 항상 함께 생성/삭제되어야 한다.
- 현재 `extra_practice_save`는 두 `create` 호출이 `transaction.atomic()` 없이 수행된다 — 동시 요청 경합 시 한쪽만 생성되는 부분 성공 상태가 발생할 수 있음.
- `extra_practice_views.py`에서 DB 저장 로직을 수정할 때는 두 `create`를 하나의 atomic 블록으로 감싸는 것을 원칙으로 한다.
- 운영 중 `schedule_id`는 존재하나 대응 `RoomBlock`이 없는 레코드가 관측되면 이 지점을 먼저 확인한다.
