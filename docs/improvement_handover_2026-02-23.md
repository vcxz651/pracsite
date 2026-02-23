# Improvement Handover (2026-02-23)

## 1) 이번 턴 실제 변경 요약
- 변경 파일:
  - `docs/improvement_worklog_2026-02-23.md`
  - `docs/improvement_handover_close_template.md`
  - `docs/improvement_handover_2026-02-23.md`
  - `pracapp/views/_meeting_common.py`
  - `pracapp/views/matching_views.py`
  - `pracapp/views/song_session_views.py`
  - `pracapp/views/meeting_views.py`
  - `pracapp/views/band_views.py`
  - `pracapp/templates/pracapp/song_confirm_delete.html`
  - `pracapp/templates/pracapp/match_result.html`
  - `pracapp/templates/pracapp/meeting_detail.html`
  - `pracapp/templates/pracapp/room_detail.html` (삭제)
- 핵심 변경 의도:
  - 작업 인수인계 체계를 먼저 고정해 중간 중단 시 이어받기 가능하도록 구성
  - 템플릿 동적 문자열 주입 구간의 XSS 위험 완화
  - 권한/잠금/합주실 조회 공통 헬퍼 분해 시작점 도입
  - 동적 HTML 블록의 인라인 이벤트 제거로 템플릿 보안/유지보수성 추가 개선

## 2) 완료/미완료
- 완료:
  - 인수인계 문서 체계 생성(시작 worklog + 종료 템플릿 + 실제 종료 문서)
  - `match_result.html` 위험 문자열 이스케이프 적용
  - `meeting_detail.html` 모달 렌더링 문자열 이스케이프 적용
  - `_meeting_common.py` 신규 추가 및 `matching_views.py`/`song_session_views.py`/`meeting_views.py` 1차 적용
  - `song_confirm_delete.html` 문구/오타 정리
  - 검증: `python3 -m py_compile ...`, `./.venv/bin/python manage.py check`
- 미완료:
  - `meeting_views.py`에서 participant 기반 판정 helper까지 공통화할지 정책 확정 후 추가 정리
  - `match_result.html`/`meeting_detail.html` 구조 분해(모듈화)
- 보류 사유:
  - 회귀 리스크를 낮추기 위해 대형 파일은 작은 단위로 순차 적용 중

## 3) 이번 턴 세부 변경 포인트
### A. 템플릿 안전화
- `pracapp/templates/pracapp/match_result.html`
  - 불가능 사유 셀의 `onclick=alert(...)` 제거
  - title 문자열 이스케이프 적용
  - 드래그 preview/new event 생성 시 `songTitle`, `roomName` 이스케이프 적용
  - 핵심 동적 이벤트 카드 2구간을 DOM API(`replaceChildren`) 방식으로 전환
  - 동적 생성 블록의 inline `onclick` 제거(위임 이벤트로 전환):
    - 예약 필요 목록/변경 목록 카드 클릭
    - 예약 불가 목록 삭제 버튼
    - 실패곡 요약 카드(주차 이동)
    - 룸 토글/임시합주실 추가 버튼
  - 카드 생성 `innerHTML` 축소:
    - `ensureFailedWrapForWeek` 래퍼 생성 DOM API 전환
    - `ensureFailedCardForSongWeek` 카드 생성 DOM API 전환
    - `createSuccessStorageCard` 카드 생성 DOM API 전환
  - 정적 버튼 인라인 `onclick` 일부 제거:
    - 상단 액션/예약 리모콘/공유·확인/모달 닫기·적용 버튼을 `id + addEventListener`로 전환
    - `bindStaticActionButtons()` 추가 후 초기화 시 바인딩
  - 카드/이벤트 인라인 이벤트 제거:
    - `.board-event`/`.failed-week-card` 초기 렌더 요소를 JS 바인딩으로 통일
    - `bindInitialBoardAndFailedCardInteractions()` + `bindFailedCardInteractions()` 추가
    - `event-room-change-btn`는 document 위임 클릭으로 처리
  - 잔여 정적 인라인 이벤트 제거:
    - resume 링크/주차·일자 예약 버튼/주차 컨트롤/내 합주 필터를 `data-* + JS 바인딩`으로 전환
    - `match_result.html` 내 `onclick/onmouseenter/onmouseleave` 0건 달성
- `pracapp/templates/pracapp/meeting_detail.html`
  - `escapeHtml` 함수 추가
  - 세션 관리 모달 렌더링에서 메시지/사용자명/폼 action/sort 값 이스케이프 적용
  - 세션 관리 모달 assign 버튼의 inline `onclick` 제거(데이터 속성+리스너)
  - 매칭 액션 패널(roomCount=0 분기) 동적 버튼 inline `onclick` 제거(`js-open-match-settings-btn` + 리스너)
  - 세션관리/곡삭제/지원자토글/참가자관리/회의수정/시뮬레이션/매칭진입/초기화확인 등 정적 클릭 액션을 위임 이벤트로 전환
  - `meeting_detail.html` 내 `onclick/onmouseenter/onmouseleave` 0건 달성

### B. 공통 헬퍼 분해 시작
- `pracapp/views/_meeting_common.py` 추가
  - final lock 상태/메시지
  - 승인 membership 조회
  - manager 권한 판정
  - meeting manager participant 판정
  - available room queryset
- `pracapp/views/matching_views.py`
  - 기존 내부 helper들이 공통 헬퍼를 호출하도록 위임
  - 기존 동작 차이 유지: final lock은 `include_released=False`로 유지
- `pracapp/views/song_session_views.py`
  - 기존 내부 helper들이 공통 헬퍼를 호출하도록 위임
- `pracapp/views/meeting_views.py`
  - 잠금/권한/합주실 조회 helper의 공통 호출 위임 적용(동작 유지)
- `pracapp/templates/pracapp/song_confirm_delete.html`
  - 사용자 노출 문구 정리 및 오타 수정

## 4) 검증 결과
- `python3 -m py_compile pracapp/views/_meeting_common.py pracapp/views/matching_views.py pracapp/views/song_session_views.py pracapp/views/meeting_views.py` 통과
- `./.venv/bin/python manage.py check` 통과
- `song_confirm_delete.html` 문구/오타 정리 반영
- `match_result.html` 동적 클릭 액션(위임 방식) 적용 후 기본 체크 통과
- `meeting_detail.html` 동적 버튼 이벤트 변경 후 `./.venv/bin/python manage.py check` 재통과
- `match_result.html` 카드 생성부 DOM API 전환 후 `./.venv/bin/python manage.py check` 재통과
- `match_result.html` 정적 버튼 이벤트 전환 후 `./.venv/bin/python manage.py check` 재통과
- `match_result.html` 카드/이벤트 이벤트 전환 후 `./.venv/bin/python manage.py check` 재통과
- `match_result.html` 인라인 이벤트 0건 전환 후 `./.venv/bin/python manage.py check` 재통과
- `meeting_detail.html` 인라인 이벤트 0건 전환 후 `./.venv/bin/python manage.py check` 재통과

## 5) 다음 작업자 우선 작업
1. `meeting_views.py`의 중복 helper를 `_meeting_common.py`로 2차 이관
2. `match_result.html`에서 남은 `innerHTML` 조립 구간(특히 툴팁/오버레이/일부 보드 UI) DOM API 기반으로 단계적 치환
3. `meeting_detail.html` 모달 동적 렌더링 구간의 남은 문자열 주입 경로 점검

## 6) 주의 포인트
- `matching_views.py`의 `_is_final_locked`는 의도적으로 "확정만 잠금" 정책(`include_released=False`)을 유지해야 함
- `match_result.html`은 리팩터링 시 예약/최종 상태 분기 회귀가 가장 쉬운 구간이므로 기능 단위로만 분리할 것

## 7) 추가 정책 정합화
- `pracapp/views/matching_views.py`
  - `schedule_match_settings`에 `@login_required` 추가
  - `schedule_room_block_manage`의 시간 범위 검증을 `18~48`로 수정(다른 화면/API 정책과 통일)

## 8) 정리 완료 항목
- 라우팅/뷰 연결이 없고 URL 불일치가 있던 dead template `pracapp/templates/pracapp/room_detail.html` 삭제

## 9) 추가 버그/품질 수정 (views 전체 검토 후)
- `song_session_views.py`: `SongUpdateView.handle_no_permission`에서 `@property`인 `meeting_id`를 `()` 붙여 호출하던 버그 수정 (`TypeError` 유발, 비저자 접근 시 재현)
- `song_session_views.py`: `SongCreateView`에 `LoginRequiredMixin` 추가
- `band_views.py`: `DashboardView.get_context_data`에서 `my_membership`이 `None`일 때 `AttributeError` 방지 None 가드 추가
- `matching_views.py`: `schedule_match_run` 내 `_normalize_to_date` 중복 정의 제거
- `matching_views.py`: `schedule_final_acknowledge`에서 `exists()` + `create()` → `get_or_create()` 교체 (동시 요청 시 중복 생성 방지)
- 검증: `py_compile` 통과, `./.venv/bin/python manage.py check` 통과
