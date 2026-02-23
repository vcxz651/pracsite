# Improvement Worklog (2026-02-23)

이 문서는 "뷰/템플릿 구조개선" 작업의 실시간 단일 진실원(SSOT)이다.
다음 작업자는 이 문서만 읽고 즉시 이어서 작업할 수 있어야 한다.

## 1) 작업 목표(고정)
- 뷰/템플릿 검토 결과에서 나온 개선 포인트만 우선 처리한다.
- 특히 다음 4축을 우선한다.
  1. 초대형 함수/템플릿 분해 기반 마련
  2. 권한/잠금/조회 규칙 중복 완화
  3. 템플릿 동적 HTML 주입(XSS 위험) 축소
  4. 죽은 템플릿/연결 불일치 정리

## 2) 시작 시점 스냅샷
- 환경 날짜: 2026-02-23
- 저장소: `/Users/kimminki/PycharmProjects/DjangoLearn`
- 참고 문서:
  - `docs/meeting_handover.md`
  - `docs/meeting_handover_2026-02-22.md`
  - `docs/engineer_onboarding_handover_2026-02-22.md`

### 검토 요약(이번 개선의 근거)
- 초대형 뷰:
  - `pracapp/views/matching_views.py` (`schedule_match_run`, `schedule_final` 등)
- 초대형 템플릿:
  - `pracapp/templates/pracapp/match_result.html` (9637+ lines)
  - `pracapp/templates/pracapp/meeting_detail.html` (3700+ lines)
- 보안/품질 리스크:
  - `innerHTML` 동적 조합부에서 이스케이프 누락 가능 구간 존재
- 연결 불일치:
  - `pracapp/templates/pracapp/room_detail.html`은 현재 URL/뷰 연결과 불일치 가능성 높음

## 3) 실행 계획(현재 턴)
1. 인수인계 문서 체계 먼저 생성(현재 문서 + 종료 템플릿)
2. 즉시 리스크 높은 템플릿 XSS 가능 구간 우선 패치
3. 공통 헬퍼/분해 시작점(최소 1개 파일) 적용
4. 변경 결과를 본 문서와 종료 직전 문서에 동기화

## 4) 진행 로그
- [완료] 작업 시작/종료 인수인계 체계 문서 생성
- [완료] 템플릿 동적 HTML 주입 구간 1차 안전화 패치
- [완료] 공통 헬퍼 도입 및 대형 뷰 분해 1단계 적용 (matching/song_session/meeting)
- [완료] `match_result.html` 동적 구간 인라인 `onclick` 2차 제거(요약/변경/예약불가/실패주차/룸토글)
- [완료] 전체 views 파일 검토 및 버그/품질 이슈 수정:
  - `song_session_views.py`: `SongUpdateView.handle_no_permission`에서 `@property`인 `meeting_id`를 `()` 붙여 호출하던 버그 수정
  - `song_session_views.py`: `SongCreateView`에 `LoginRequiredMixin` 추가 (비로그인 접근 시 `next` 파라미터 포함 로그인 페이지로 직접 이동)
  - `band_views.py`: `DashboardView`에서 `my_membership`이 `None`일 때 `AttributeError` 발생 가능 구간에 None 가드 추가
  - `matching_views.py`: `_normalize_to_date` 함수 동일 내용 중복 정의 제거 (1109~1124라인)
  - `matching_views.py`: `schedule_final_acknowledge`에서 `exists()` + `create()` 패턴을 `get_or_create()`로 교체 (Race Condition 방지)

## 5) 리스크/주의
- `match_result.html`은 단일 파일 리스크가 커서 한 번에 대분해하면 회귀 확률이 높음
- 따라서 "동작 보존 + 작은 단위"로 자르며 진행
- 기존 동작(예약/최종 상태 전이)은 반드시 유지

## 6) 다음 작업자 즉시 확인 순서
1. `docs/improvement_worklog_2026-02-23.md` 최신 섹션 확인
2. `docs/improvement_handover_close_template.md`의 체크리스트 기준으로 누락 점검
3. 변경 파일에서 `innerHTML`/`onclick`/동적 문자열 주입 우선 재검토


## 7) 이번 턴 변경 파일
- `pracapp/views/_meeting_common.py`
- `pracapp/views/matching_views.py`
- `pracapp/views/song_session_views.py`
- `pracapp/views/meeting_views.py`
- `pracapp/views/band_views.py`
- `pracapp/templates/pracapp/song_confirm_delete.html`
- `pracapp/templates/pracapp/match_result.html`
- `pracapp/templates/pracapp/meeting_detail.html`
- `docs/improvement_handover_2026-02-23.md`
- `docs/improvement_worklog_2026-02-23.md`


## 8) 현재 남은 주요 작업
1. `match_result.html`의 동적 카드 생성부를 DOM API로 단계 전환
2. `meeting_detail.html` 모달 렌더링의 남은 문자열 주입 구간 점검
3. `meeting_views.py` participant 기반 권한 helper 공통화 정책 확정

- [완료] `schedule_match_settings`에 `@login_required` 적용
- [완료] `schedule_room_block_manage` 시간 범위 검증을 09:00~24:00(`18~48`)로 통일
- [완료] `match_result.html` 동적 이벤트 카드 2개 구간을 `innerHTML`에서 DOM API(`replaceChildren`)로 전환
- [완료] `match_result.html` 동적 생성 HTML의 인라인 `onclick` 제거:
  - 예약 필요 목록/변경 목록 카드: `data-event-id` + 위임 클릭
  - 예약 불가 목록 삭제 버튼: `data-booking-room-block-id` + 위임 클릭
  - 실패곡 요약 카드: `data-failed-week-no` + 위임 클릭
  - 룸 토글 버튼/임시합주실 추가: `data-toggle-*` + 위임 클릭
- [완료] `meeting_detail.html` 매칭 액션 패널의 동적 `innerHTML` 버튼 인라인 `onclick` 제거(`js-open-match-settings-btn` + 리스너)
- [완료] `match_result.html` 카드 생성 `innerHTML` 추가 축소:
  - `ensureFailedWrapForWeek`의 래퍼 생성 DOM API 전환
  - `ensureFailedCardForSongWeek` 카드 생성 DOM API 전환
  - `createSuccessStorageCard` 카드 생성 DOM API 전환
- [완료] `match_result.html` 정적 버튼 인라인 `onclick` 추가 제거:
  - 상단 액션/예약 리모콘/공유·확인/모달 닫기·적용 버튼을 `id + addEventListener`로 전환
  - `bindStaticActionButtons()` 도입 및 초기화 루틴에서 바인딩
- [완료] `match_result.html` 카드/이벤트 인라인 마우스 이벤트 제거:
  - 초기 `.board-event`/`.failed-week-card`를 JS 바인딩으로 통합
  - `bindInitialBoardAndFailedCardInteractions()` + `bindFailedCardInteractions()` 도입
  - `event-room-change-btn` 클릭은 위임 이벤트로 전환
- [완료] `match_result.html` 잔여 정적 인라인 이벤트 전부 제거:
  - resume 링크/주차·일자 예약 버튼/주차 컨트롤/내 합주 필터를 `data-* + JS 바인딩`으로 전환
  - 결과적으로 `match_result.html`의 `onclick/onmouseenter/onmouseleave` 0건
- [완료] `meeting_detail.html` 반복/관리 액션 인라인 이벤트 제거:
  - 세션 관리/곡 삭제/지원자 토글을 위임 클릭으로 전환
  - 참가자 관리/회의 수정/지원자 전체 토글/필터 해제/시뮬레이션/매칭 진입/초기화 확인 버튼까지 `id|data-* + JS`로 전환
  - 결과적으로 `meeting_detail.html`의 `onclick/onmouseenter/onmouseleave` 0건
- [완료] 미참조/불일치 템플릿 `pracapp/templates/pracapp/room_detail.html` 제거
- [완료] `meeting_detail.html` 세션 관리 모달 assign 버튼의 inline `onclick` 제거(데이터 속성+리스너 방식)

## 9) 최신 검증
- `python3 -m py_compile pracapp/views/_meeting_common.py pracapp/views/matching_views.py pracapp/views/song_session_views.py pracapp/views/meeting_views.py` 통과
- `./.venv/bin/python manage.py check` 통과
- `meeting_detail.html` 추가 수정 후 `./.venv/bin/python manage.py check` 재통과
- views 버그/품질 수정 후 `python3 -m py_compile pracapp/views/song_session_views.py pracapp/views/band_views.py pracapp/views/matching_views.py` 통과
- `./.venv/bin/python manage.py check` 재통과
