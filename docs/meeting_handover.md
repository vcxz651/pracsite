# Meeting Handover (2026-02-25, Full Rewrite)

이 문서는 기존 인수인계 문서를 폐기하고 새로 작성한 단일 기준 문서다.
이후 작업자는 이 문서 기준으로만 판단한다.

## 1) 범위와 목적
- 핵심 범위: `매칭 조율 -> 공유 -> 예약 확정 -> 최종 확정` 전체 흐름.
- 핵심 파일:
  - `pracapp/views/matching_views.py`
  - `pracapp/templates/pracapp/match_result.html`
  - `pracapp/models.py` (`Meeting`, `MeetingFinalDraft`, `MeetingWorkDraft`, `PracticeSchedule`)
  - `pracapp/migrations/0043_meetingfinaldraft_match_params.py`
- 목적:
  - 배포 직전 안정성 유지
  - 서버/클라이언트 검증 경계 일치
  - 임시합주실/강제배치/예약 임시저장 복원 안정화

## 2) 현재 결론 (요약)
- 매칭 설정 파라미터의 단일 기준은 `MeetingFinalDraft.match_params`.
- 예약 페이지 새로고침 복원은 `MeetingWorkDraft.events` 우선 로드.
- 예약 완료 여부는 `booking_completed_keys`로 서버 재검증.
- 예약 확정 단계에서는 강제 배치 멤버중복을 서버가 재차단하지 않도록 완화 적용.
- 임시합주실은 토글 기반 생성/유지 전제이며, 저장 시 이름/위치 미확정이면 서버가 409 차단.
- 리모콘 필터(`강제 배치만`, `공유 후 변경만`, `임시합주실만`, `일반/룸 보기`)는 관리자 hover-preview + click-pin 동작.

## 3) 상태 플래그 의미 (Meeting)
`pracapp/models.py`
- `is_schedule_coordinating`
  - 조율 단계(공유 전 수정 중) 여부.
- `is_final_schedule_released`
  - 공유본 공개 여부.
- `is_booking_in_progress`
  - 관리자 예약 확정 단계 진입 여부.
- `is_final_schedule_confirmed`
  - 최종 확정 완료 여부.
- `schedule_version`
  - 공유/확정 등 주요 단계 전환 시 증가. 멤버 확인 제출 버전 키.

주의:
- 플래그 조합이 화면 권한/버튼 활성/리다이렉트 조건에 직결됨.
- 플래그 변경은 보통 `schedule_final_prepare`, `schedule_booking_start`, `schedule_save_result`, `schedule_final_reset`에서 발생.

## 4) Draft/확정 데이터 소스
### 4-1. 모델 역할
`pracapp/models.py`
- `MeetingFinalDraft(events, match_params, updated_by)`
  - 공유 기준 보드(공용).
  - 최종/예약 화면의 기준 파라미터(`d`, `c`, `r`, `rp`, ...) 저장.
- `MeetingWorkDraft(meeting,user,events,match_params)`
  - 관리자 개인 임시저장 보드.
  - 예약 페이지 새로고침 복원 소스.
- `PracticeSchedule`
  - 최종 확정 저장본(DB 확정 스케줄).

### 4-2. 소스 우선순위
- 최종/예약 렌더링(`schedule_final`):
  1. 예약 편집 모드(`?mode=booking`) + 관리자 + `MeetingWorkDraft.events` 존재 시 최우선
  2. 없으면 `MeetingFinalDraft.events`
  3. 없으면 `PracticeSchedule`
- 매칭 파라미터(`effective_match_params_json`)는 공유본인 `MeetingFinalDraft.match_params` 단일 기준.

## 5) 핵심 함수 시그니처/계약
`pracapp/views/matching_views.py`
- `_build_events_signature(events)`
  - 이벤트를 `(song_id,date,room_id)` 단위로 병합 정규화 후 signature JSON 생성.
  - 공유 이후 변조 감지/비교에 사용.
- `_build_booking_event_key(song_id,date,start,duration,room_id)`
  - 예약 완료 키 생성.
- `_validate_normalized_events_against_external_conflicts(meeting, normalized_events, allow_forced_member_overlap=False)`
  - 외부 미팅/RoomBlock 충돌 + 멤버중복 검사.
  - `allow_forced_member_overlap=True`면 강제배치 관련 중복 완화.

### 5-1. 엔드포인트
- `schedule_final_prepare` (공유)
  - 입력: `{ events: [...], match_params: {...} }`
  - 동작: 검증 -> `MeetingFinalDraft` 저장 -> `MeetingWorkDraft` 동기화 -> 공개 플래그 전환.
- `schedule_booking_start` (예약 단계 진입)
  - 입력: `{ events: [...], match_params: {...} }`
  - 동작: 공유본 시그니처 비교 -> draft 동기화 -> `is_booking_in_progress=True`.
- `schedule_save_result` (최종 확정 저장)
  - 입력: `{ events: [...], booking_completed_keys: [...] }`
  - 동작:
    - 예약 단계면 `booking_completed_keys` 서버 재검증
    - 이벤트 정규화/임시합주실 처리
    - 외부 충돌 검증
    - `PracticeSchedule` 재기록 + 확정 플래그 세팅

## 6) 최근 주요 수정 포인트 (중요)
### 6-1. 예약 확정 차단 버그(시스템 메시지 중복 차단)
- 증상: 모달에서 확인했는데 서버가 `[날짜] 같은 멤버... 중복 배정`으로 409 차단.
- 원인: `schedule_save_result`의 마지막 서버 보수 검증이 예약 단계에서도 멤버중복 하드차단.
- 조치: `schedule_save_result` 검증 호출에
  - `allow_forced_member_overlap=bool(meeting.is_booking_in_progress)` 적용.
- 결과: 예약 확정 단계에서는 강제배치 중복을 모달 정책대로 허용.

### 6-2. 예약 임시저장/새로고침 시 보드 유실
- 조치:
  - 예약 보기에서 `MeetingWorkDraft.events` 우선 로드.
  - `booking_saved_completed_keys` 복원 시 signature 완전일치 강제 완화(존재 키만 프론트에서 매핑).
- 결과: 방 이동/길이 변경/예약 체크 복원 안정성 개선.

### 6-3. 매칭 설정 분/횟수 기준 흔들림
- 조치:
  - `MeetingFinalDraft.match_params` 추가(마이그레이션 `0043`).
  - 공유/예약 진입 시 `match_params` 저장 및 전달.
  - 최종 화면의 `effective_match_params_json`, `week_song_required_slots_json` 계산 소스 정리.

### 6-4. UI/조작 안정화
- 드래그 후 클릭 오작동 억제 로직 적용.
- `forced-assigned` z-index를 overlay 아래로 내려 가시성 개선.
- 임시합주실 일반보기 우측(최후순위) 정렬: `getRoomPriorityRank()`에서 `temp-*` 큰 rank 강제.
- 비관리자 리모콘에서 비활성 버튼 숨김.
- 관리자 리모콘 hover-preview + click-pin 동작 추가.

## 7) 임시합주실 규칙 (현재 정책)
- 생성: 토글 기반(주/일 단위 추가 버튼 경유).
- 저장 검증:
  - `room_id`가 `temp-*`이고
  - `temp_room_confirmed`도 false이며
  - 이름/위치 식별도 없으면
  - 서버가 `409: 임시합주실 이름/위치를 먼저 입력...` 반환.
- 주의:
  - 임시합주실 이벤트 payload에 `temp_room_confirmed`, `room_name`, `room_location` 누락 시 저장 실패 가능.

## 8) 불가능 사유/팝오버/프라이버시
- 카드 hover 팝오버와 불가능 오버레이 pinned/hover 로직이 분리되어 있음.
- 일반인 뷰에서는 개인 프라이버시 보호를 위해 타인의 상세 사유 노출 제한이 일부 경로에 존재.
- 합주 중복 사유 표기는 포맷 조정됨:
  - 같은 미팅: `이름(세션) - 합주곡`
  - 다른 미팅: `[미팅명] - 곡제목` 계열 문구
- 오버레이 hover 시 곡정보 팝오버 미노출이 의도이나, 이벤트 전파 경계에서 재발 가능성 높음.

## 9) 리모콘(Quick Remote) 현재 동작
`pracapp/templates/pracapp/match_result.html`
- 핵심 필터:
  - `quickForcedOnlyBtn` (`강제 배치만`)
  - `quickSharedDiffOnlyBtn` (`공유 후 변경만`)
  - `quickTempRoomOnlyBtn` (`임시합주실만`)
  - `quickLayoutToggleBtn` (`일반 보기`/`룸 보기`)
- 관리자:
  - hover 시 미리보기 반영
  - click 시 고정(pin)
- 비관리자:
  - 사용 불가 버튼은 숨김 처리
- 예약 패널:
  - 한 줄 1버튼 정렬
  - `임시 저장` 버튼 추가됨
  - 예약 단계에서 불필요한 조율 버튼 일부 제거됨

## 10) 서버/클라 경계에서 자주 터지는 지점
1. 시그니처 불일치
- 공유 후 예약 진입 시 `incoming_sig != shared_sig`면 409.
- 원인 대부분: 공유 이후 보드 변경, 이벤트 병합규칙 차이, duration/start 비정상.

2. 예약 완료 키 누락
- `booking_completed_keys` 누락이면 예약 확정 저장에서 409.
- 강제배치/예약불가 블록 제외 조건과 키 생성 규칙 일치 필요.

3. 임시합주실 식별 누락
- `temp-*` 이벤트에 확인 플래그/이름/위치 누락 시 저장 실패.

4. 플래그 전이 순서
- 예약/공유/확정 단계에서 플래그 세팅 순서가 틀리면 버튼/권한 꼬임.

## 11) 의사결정 이력 (왜 이렇게 했는지)
- 리팩토링 보류
  - 배포 12시간 내 안정성 우선으로 판단해 구조개편보다 버그 픽스를 선택.
- 임시합주실 유지
  - 핵심 기능이라 제거 불가. 대신 생성 경로를 토글 중심으로 고정하고 저장 검증을 강화.
- 레거시 공간분할/칸 나눠갖기 제거 방향
  - UX 가치 대비 버그 유발이 커서 신규 확장 중단, 안정성 중심으로 축소.
- 길게 눌러 타일 분리 기능
  - 고정 버그 리스크 때문에 개선보다 비활성/축소 운영 선택.
- 예약 확정 차단 정책
  - 모달에서 위험 인지 후 진행을 허용하는 UX인데 서버가 재차단하던 불일치 해소.
  - 결론: 예약 단계 강제배치 중복은 서버도 동일하게 허용.
- 공유본 기준 운영
  - 팀 커뮤니케이션 기준은 공유본이며, 예약은 공유본 기반 확정 단계라는 메시지를 UI에 반영.
- 공유 후 변경만/변동현황판 기준
  - 현재 예약 임시저장 기준으로 동작하므로 오해 가능성 있음.
  - 공유본 기준으로 재설계 전까지는 기능 노출 최소화/비활성화 방향 선택.

## 12) 사용자 커스텀 제약사항 (반드시 준수)
- 임시합주실은 제거 금지, 반드시 지원.
- 임시합주실 생성은 토글 경로 중심으로 처리(임의 생성 플로우 확장 금지).
- 공간 부족 시 칸 나눠갖기(레거시 분할) 로직은 앞으로 사용하지 않음.
- 일반인 뷰에서 누를 수 없는 버튼은 아예 숨김(비활성 노출 금지).
- 관리자 리모콘의 일부 필터는 hover 즉시 미리보기, click 시 고정.
- 일반보기/룸보기에서 임시합주실은 최후순위(오른쪽) 배치.
- 불가능 오버레이는 정책상 다시 노출 가능하되, 프라이버시 노출 범위는 제한 유지.
- 공유/예약 경고 모달 문구는 “최종 공유본 기준” 의도를 전달해야 함.
- 예약 페이지에서도 임시 저장 필요(리모콘 포함).
- 예약 단계에서 조율용 버튼(추가합주 등)은 노출 금지.
- 예약 확정에서 시스템 메시지 이중차단 금지(모달 확인 후 진행 가능해야 함).
- 인원중복 사유 포맷은 `이름(세션) - 합주곡` 우선.

## 13) 배포 전 최소 회귀 체크 (필수)
1. 관리자 조율 -> 공유
- 공유 모달 노출, 경고 문구, 공유 성공 후 `is_final_schedule_released=True` 확인.

2. 공유본 기준 예약 진입
- 예약 진입 성공, `?mode=booking`, 일반 멤버 뷰 영향 없는지 확인.

3. 예약 편집 + 임시저장 + 새로고침
- 카드 이동/길이변경/임시합주실 카드 유지 여부 확인.
- `booking_completed_keys` 복원 여부 확인.

4. 강제배치 포함 예약 확정
- 모달 확인 후 서버 차단 없이 확정 저장되는지 확인.

5. 일반인 뷰
- 임시합주실 포함 일정 노출, 불가능 오버레이/사유 노출 정책 확인.

## 14) 작업 시 절대 규칙
- `match_result.html`은 9k+ 라인이라 작은 수정도 부작용 큼. 수정 전/후 핸들러 중복 바인딩 반드시 확인.
- `split`(길게 눌러 분리) 로직은 남아있다. 기능 확장보다 비활성/안정화 우선.
- 중복 조건을 클라에서만 허용하고 서버에서 차단하면 반드시 재발한다. 서버 정책 먼저 맞출 것.
- 임시합주실 관련 신규 로직 추가 시 `temp-*`와 실 DB room id 혼용을 항상 분리해 다룰 것.

## 15) 빠른 디버깅 포인트
- 서버:
  - `schedule_final_prepare`
  - `schedule_booking_start`
  - `schedule_save_result`
  - `_validate_normalized_events_against_external_conflicts`
- 프론트:
  - `confirmRiskSummaryModal`
  - `saveMyWorkDraft`
  - `applyQuickBoardFilters`
  - `syncQuickRemoteButtons`
  - `getRoomPriorityRank`

## 16) 현재 워크트리 참고 (주의)
- 이 프로젝트는 매칭/예약 외 파일도 다수 변경되어 있다.
- 인수인계 범위 밖 파일을 되돌리지 말고, 작업 범위를 먼저 사용자와 합의할 것.
- 현재 변경 파일 확인 명령:
  - `git status --short`
  - `git diff --name-only`

## 17) 후속 리팩토링 권장 순서 (프로토타입 배포 후)
1. `match_result.html` 분할
- remote, hover/overlay, drag/drop, booking panel, modal 모듈 분리.

2. 예약/공유/확정 상태머신 명시화
- 플래그 조합 enum화 + 서버 단일 가드 함수화.

3. 이벤트 스키마 타입 고정
- event payload 스키마를 서버/클라 공통 상수로 정의.

4. 검증 체인 일원화
- 외부충돌/멤버중복/정원초과/예약키 검증 단계를 명시적으로 분리.

## 18) 미해결/관찰 필요 이슈
- 오버레이 hover/클릭과 곡정보 팝오버 이벤트 전파 경계는 회귀 가능성이 높음.
- `split` 관련 코드가 남아 있어, 비활성 정책과 실제 동작 간 불일치 가능성 있음.
- `공유 후 변경만` 기준이 공유본이 아닌 예약 임시저장본 기준으로 보일 수 있음.
- 일반인 뷰 프라이버시 규칙(특히 중복 합주 사유)은 경계 케이스에서 재검증 필요.
- 임시합주실 이름/위치 검증은 UX와 충돌 가능성이 있으므로 오류 빈도 모니터링 필요.

## 19) 배포/롤백 런북 (최소)
1. 배포 전
- `python manage.py migrate`로 `0043_meetingfinaldraft_match_params` 반영 확인.
- 관리자 계정으로 회귀 체크(13장 1~5) 완료 후 배포.

2. 배포 후 스모크
- 공유 -> 예약 진입 -> 임시저장 -> 새로고침 -> 예약확정 1회 시나리오 통과 확인.
- 강제배치 포함 케이스에서 서버 409 차단 재발 여부 확인.

3. 롤백
- 코드 롤백 시 DB 컬럼(`MeetingFinalDraft.match_params`)은 남아도 무방(하위호환 영향 낮음).
- 장애 시 우선 `예약확정` 경로만 임시 비활성(권한/버튼) 후 원인 분석 권장.

## 20) 운영 관측 포인트 (로그/응답)
- `schedule_save_result` 409 응답 메시지 빈도:
  - `아직 예약이 필요한 타일이 남아 있습니다.`
  - `임시합주실 이름/위치를 먼저 입력...`
  - `외부 일정과 충돌합니다.`
- `schedule_booking_start` 409:
  - `공유 이후 일정이 변경되었습니다...`
- 프론트에서 모달 확인 후 서버 차단되는 사례가 나오면 서버/클라 정책 불일치 신호.

## 21) 재현 데이터 셋 가이드
- 회귀 재현용 미팅 1개를 고정해 아래를 항상 포함:
  - 강제배치 1건 이상
  - 임시합주실 1개 이상
  - 멤버 중복 가능한 곡 2개 이상
  - 정원 초과/미달 모두 발생하는 합주실
- 이 셋으로 배포 직전/직후 동일 시나리오를 반복해 차이를 확인.

## 22) 우선순위/작업 원칙 (배포 전)
- P0: 예약 확정 실패, 데이터 유실, 임시저장 복원 실패
- P1: 불가능 사유 표시 불일치, 리모콘 상태 반영 오류
- P2: 시각 스타일/정렬/문구 미세 불일치
- 원칙: 배포 전에는 구조개편 금지, 단일 버그의 최소 범위 패치 우선.

## 23) Payload 예시 (실무 참조)
1. 공유 (`schedule_final_prepare`)
```json
{
  "events": [
    {
      "song_id": "11111111-1111-1111-1111-111111111111",
      "date": "2026-03-26",
      "start": 36,
      "duration": 3,
      "room_id": "22222222-2222-2222-2222-222222222222",
      "room_name": "A룸",
      "room_location": "3F",
      "is_forced": false
    }
  ],
  "match_params": {
    "d": "90",
    "c": "1",
    "r": "22222222-2222-2222-2222-222222222222",
    "rp": "22222222-2222-2222-2222-222222222222",
    "w": "0",
    "re": "1",
    "h": "0",
    "ts": "18",
    "te": "48"
  }
}
```

2. 예약 진입 (`schedule_booking_start`)
```json
{
  "events": [/* 공유본과 동일 signature */],
  "match_params": {/* 공유 시점과 동일 권장 */}
}
```

3. 예약 확정 (`schedule_save_result`)
```json
{
  "events": [
    {
      "song_id": "11111111-1111-1111-1111-111111111111",
      "date": "2026-03-26",
      "start": 36,
      "duration": 3,
      "room_id": "temp-abc123",
      "room_name": "임시합주실",
      "room_location": "외부 스튜디오",
      "temp_room_confirmed": true,
      "is_forced": true
    }
  ],
  "booking_completed_keys": [
    "11111111-1111-1111-1111-111111111111|2026-03-26|36|3|22222222-2222-2222-2222-222222222222"
  ]
}
```

## 24) 트러블슈팅 로그 패턴
1. 공유 이후 예약 진입 차단
- 증상: `공유 이후 일정이 변경되었습니다. 다시 공유 후 예약을 진행해주세요.`
- 확인:
  - `incoming_sig` vs `shared_sig`
  - 공유 이후 보드 수정 여부

2. 예약 확정 차단 (예약키 누락)
- 증상: `아직 예약이 필요한 타일이 남아 있습니다.`
- 확인:
  - `booking_completed_keys` payload 누락/직렬화 오류
  - 강제배치/예약불가 블록 제외 조건과 키 생성 조건 일치 여부

3. 임시합주실 저장 차단
- 증상: `임시합주실 이름/위치를 먼저 입력한 뒤 저장해주세요.`
- 확인:
  - `room_id=temp-*`
  - `temp_room_confirmed=true` 또는 `room_name/room_location` 유효값 포함 여부

4. 서버와 모달 정책 불일치
- 증상: 프론트에서 확인 눌렀는데 서버 409
- 확인:
  - `_validate_normalized_events_against_external_conflicts()` 호출 인자
  - `allow_forced_member_overlap` 분기

## 25) Handoff 체크리스트 (다음 담당자용)
1. 현재 플래그 상태 확인
- `is_schedule_coordinating`, `is_final_schedule_released`, `is_booking_in_progress`, `is_final_schedule_confirmed`

2. 기준 데이터 소스 확인
- 공유본: `MeetingFinalDraft.events/match_params`
- 개인 임시저장: `MeetingWorkDraft.events/match_params`

3. 핵심 시나리오 1회 재현
- 공유 -> 예약 진입 -> 임시저장 -> 새로고침 -> 예약확정

4. 정책 일치 확인
- 프론트 모달 허용 조건과 서버 차단 조건 일치

5. 변경 범위 확인
- `git diff --name-only`로 인수인계 범위 외 파일 수정 여부 체크

## 26) 검증 체인 순서도
```text
[클라이언트 액션]
   |
   v
collectCurrentEvents()
   |
   v
confirmRiskSummaryModal()  (사용자 인지/확인)
   |
   v
POST (prepare/share or booking-start or save-result)
   |
   v
서버 입력 검증 (method/json/type/range)
   |
   +--> 예약 단계면 booking_completed_keys 재검증
   |
   v
이벤트 정규화 (song/date/start/duration/room/temp-room)
   |
   v
_validate_normalized_events_against_external_conflicts()
   |
   +--> room block/external schedule 충돌 검사
   +--> 멤버 중복 검사 (예약단계는 allow_forced_member_overlap 적용)
   |
   v
DB 반영 (Draft or PracticeSchedule)
   |
   v
플래그 전이 / redirect_url 반환
```

---
최신 패치 반영 확인:
- 예약 페이지에서 시스템 메시지로 확정 차단하던 이슈는 `schedule_save_result`의 `allow_forced_member_overlap` 분기 조정으로 해소됨.

## 27) 2026-02-27 UX 업데이트 로그
이번 턴에서 반영한 내용은 "대규모 구조 변경 없이 체감 UX 개선"에 한정한다.

1. 홈(`home.html` + `home_views.py`) 주간 보드 개선
- 홈 최상단 영역을 기존 "목록형 내 합주"에서 "주간 보드형"으로 전환(밴드/내 일정 섹션보다 상단 배치).
- 시간축 압축 기준을 "18:00~24:00 고정"이 아니라 "해당 주 내 최초 합주/개인일정 시작 ~ 최후 종료"로 적용.
- 테스트 날짜 오버라이드 쿼리 파싱 유연화:
  - 허용: `YYYY-MM-DD`, `YYYY/MM/DD`, `M/D`, `M-D`
  - 해제: `?today=off`
- 합주 보드에 개인일정(고정/단발, 예외 취소 반영) 오버레이를 렌더링.
- 개인일정 블록에 reason 텍스트 표시.
- 홈 이벤트 플로팅 팝오버를 `match_result` 계열과 동일한 `.floating-popover` 스타일로 통일.
- 팝오버 본문은 라벨(`곡/합주시간/합주실`) 텍스트를 제거하고 값만 표시하도록 조정.
- 추가합주 이벤트 팝오버 상단에 빨간 `추가합주` 라벨 표시.
- 팝오버 접근성 보강:
  - 마우스 hover 외 `focus`, `click`, `touchstart`에서도 표시.
  - 개인일정 블록도 팝오버 표시 가능하도록 `pointer-events` 허용.
- 홈 보드 가독성 조정:
  - 헤더/시간/이벤트/개인일정 텍스트 폰트 소폭 상향.

2. 참가자 관리 모달 UX 개선 (`meeting_participant_manage.html`)
- 컬럼 정렬(이름/세션/일정 등록 여부/직책) 시 현재 방향 `↑/↓` 표시.
- 참가자 액션(승인/거절/매니저 임명/해제/제외) 실패 시 무반응이 아니라 에러 토스트 표시.
- 성공 시 성공 토스트 표시.

3. 데모 시작 UX 개선 (`demo_home.html`)
- 시나리오 `시작하기` 클릭 시 버튼 즉시 비활성화 + 스피너 + `준비 중...` 텍스트 표시.
- 중복 클릭 방지로 체감 지연 구간의 사용자 혼란 완화.

4. 정책/리스크 메모
- `match_result.html` 본체 로직은 고위험 영역으로 이번 턴에서 구조 수정하지 않음.
- 홈/데모/모달 UX 계층에서만 개선해 회귀 리스크를 낮춤.
- 참가자 관리는 fetch 실패 시 토스트만 추가했으므로 서버 정책/권한 로직은 기존 그대로 유지.

## 28) 파일별 변경 맵 (다음 작업자 즉시 착수용)
아래는 "요구사항 -> 수정 파일/핵심 지점" 매핑이다.

1. 홈 상단 내 합주 보드를 주간 스케줄보드로 전환
- `pracapp/templates/pracapp/home.html`
  - 상단 섹션 렌더 구조(보드, 타임라인, 이벤트 카드) 추가
- `pracapp/views/home_views.py`
  - `_build_my_week_rehearsal_board()` 결과를 context(`my_week_board`)로 주입

2. 테스트 날짜 쿼리 기반 주차 이동
- `pracapp/views/home_views.py`
  - `_resolve_today_override()` 확장
  - 허용 포맷: `YYYY-MM-DD`, `YYYY/MM/DD`, `M/D`, `M-D`
  - 해제: `?today=off`

3. 시간축 압축(빈 시간 제거)
- `pracapp/views/home_views.py`
  - `slot_start/slot_end`를 실제 데이터(합주 + 개인일정) min/max로 계산

4. 홈 보드에 개인일정 오버레이 표시
- `pracapp/views/home_views.py`
  - `RecurringBlock`, `OneOffBlock(is_generated=False)`, `RecurringException` 반영
  - 개인일정 블록 병합 시 reason 기준으로 분리
- `pracapp/templates/pracapp/home.html`
  - `.home-week-personal-block` 렌더 및 텍스트 표시

5. 홈 팝오버 포맷 통일 + 추가합주 라벨
- `pracapp/templates/pracapp/home.html`
  - Bootstrap 기본 tooltip 제거
  - `.floating-popover` 커스텀 팝오버 사용
  - `추가` 이벤트 시 빨간 `추가합주` 라벨 표시
  - 본문 라벨 텍스트 제거(값만 출력)

6. 홈 팝오버 접근성(모바일/키보드)
- `pracapp/templates/pracapp/home.html`
  - hover + focus + click + touchstart 지원
  - 개인일정 블록도 팝오버 표시 가능하도록 `pointer-events` 활성

7. 참가자 관리 정렬 UX/피드백 개선
- `pracapp/templates/pracapp/meeting_participant_manage.html`
  - 현재 정렬 방향 `↑/↓` 표시
  - 액션 성공/실패 토스트 표시

8. 데모 시작 로딩 UX
- `pracapp/templates/pracapp/demo/demo_home.html`
  - `시작하기` 클릭 시 버튼 비활성 + spinner + `준비 중...`
  - 중복 클릭 방지

9. 데모/매칭 정책 관련 기존 문서 보완
- `docs/meeting_handover.md`
  - 본 섹션 포함 최근 UX 수정 로그 추가

## 29) 수동 검증 체크리스트 (URL/기대결과)
다음 작업자는 아래만 확인하면 현재 상태를 재현/검증할 수 있다.

1. 홈 주차 이동/압축
- URL: `/` + `?today=2026-05-09` (또는 `?today=5/9`)
- 기대:
  - 해당 주(월~일)로 헤더 범위가 이동
  - 보드 세로 범위가 최초 일정 시작~최후 일정 종료로 압축

2. 홈 팝오버(합주/개인일정)
- 동작:
  - 합주 카드 hover/click/touch/focus
  - 개인일정 회색 블록 hover/click/touch/focus
- 기대:
  - 합주: 밴드·미팅 + 곡/시간/공간 값 표시
  - 추가합주: 맨 위 빨간 `추가합주`
  - 개인일정: `개인 일정` + reason 표시

3. 홈 폰트 가독성
- 기대:
  - 시간축/카드/개인일정 텍스트가 이전 대비 한 단계 크게 보임
  - 과도한 줄깨짐/겹침 없음

4. 참가자 관리 정렬
- 화면: 참가자 관리 모달
- 동작: 이름/세션/일정 등록 여부/직책 헤더 클릭
- 기대:
  - 정렬 토글
  - 현재 컬럼에 `↑` 또는 `↓` 표시

5. 참가자 관리 액션 토스트
- 동작: 승인/제외/회의 매니저 임명 등 버튼 클릭
- 기대:
  - 성공 시 성공 토스트
  - 실패(권한/네트워크) 시 실패 토스트

6. 데모 시작 로딩
- 화면: `/demo/`
- 동작: 시나리오 시작 버튼 클릭
- 기대:
  - 버튼 즉시 비활성
  - spinner + `준비 중...` 표시
  - 중복 클릭 불가

## 30) 오픈 이슈 / 의도된 미완료
1. `match_result.html` 대규모 리팩토링은 미착수
- 이유: 고위험(핸들러/오버레이/드래그 결합도 높음), 이번 턴은 UX 미세개선만 수행.

2. 홈 팝오버 닫힘 정책
- 현재는 document click으로 닫힘.
- 모바일에서 "고정 팝오버 + 닫기 버튼" UX로 바꿀 여지 있음.

3. 홈 개인일정 텍스트 밀집 케이스
- 일정이 촘촘한 날에는 텍스트가 생략(ellipsis)됨.
- 필요 시 최소 높이 이하에서는 reason 숨기고 아이콘/점 표시로 전환 고려.

4. 참가자 관리 토스트 메시지 문구
- 현재는 단문 공통 메시지 중심.
- 서버 응답 message를 세분 반영하면 디버깅/운영 편의가 더 좋아짐.

5. 데모 시작 지연의 근본 해결
- 현재는 버튼 로딩 표시만 보강.
- 근본 개선은 사전 캐시 준비 커맨드/백그라운드 워밍 강화가 필요.
