# 주요 대형 파일 개요

> 작성일: 2026-02-24
> 향후 작업자가 코드 탐색 시 참고할 수 있도록, 라인 수 기준 주요 파일의 역할과 핵심 함수를 정리한다.

---

## 파일 크기 요약

| 파일 | 종류 | 라인 수 | 주요 역할 |
|---|---|---|---|
| `pracapp/templates/pracapp/match_result.html` | Template | ~10,000 | 스케줄 보드 인터랙티브 UI |
| `pracapp/templates/pracapp/meeting_detail.html` | Template | ~3,900 | 미팅 상세 페이지 전체 |
| `pracapp/views/matching_views.py` | View | ~2,850 | 매칭 알고리즘 + 스케줄 확정 |
| `pracapp/utils.py` | Utility | ~2,150 | 스케줄 알고리즘 · 가용성 계산 |
| `pracapp/views/meeting_views.py` | View | ~1,400 | 미팅 CRUD · 세션 승인 흐름 |
| `pracapp/templates/pracapp/match_settings.html` | Template | ~930 | 매칭 파라미터 설정 UI |
| `pracapp/views/song_session_views.py` | View | ~565 | 곡·세션 관리 |
| `pracapp/views/extra_practice_views.py` | View | ~500 | 추가 합주 스케줄 |
| `pracapp/models.py` | Model | ~710 | 전체 ORM 스키마 |
| `pracapp/forms.py` | Form | ~430 | 폼 클래스 모음 |
| `pracsite/urls.py` | URL | ~95 | 전체 URL 라우팅 |

---

## 파일별 상세

---

### `pracapp/templates/pracapp/match_result.html`
**라인 수:** ~10,000줄
**역할:** 자동 매칭 결과 및 최종 시간표를 표시·편집하는 인터랙티브 스케줄 보드. 단일 파일 안에 CSS · HTML · JS가 모두 포함된 거대 파일.

**주요 섹션 (CSS/HTML):**
- `:root` CSS 변수: `--slot-h`, `--ep-primary` 등 전체 테마 제어
- `.week-board` / `.board-day-grid`: 7일 × 시간 그리드 레이아웃
- `.board-event` / `.event-card`: 곡 타일 카드
- `.week-room-filter`: 주 단위 합주실 토글 바 (보드 외부)
- 드래그 홀로그램 (`.drag-preview`), hover 오버레이 (`.hover-conflict-overlay`)

**주요 JS 함수:**
| 함수 | 역할 |
|---|---|
| `calcDropTarget(x, y, state)` | 드래그 위치 → 날짜·슬롯·합주실 계산 |
| `resolveRoomAssignment(date, start, dur, el, preferred)` | 합주실 배정 알고리즘 |
| `relayoutDayGrid(grid)` | 카드 위치·너비 재계산 (roomslot 분할 포함) |
| `renderWeekRoomFilter(weekBoard)` | 주 단위 합주실 토글 바 렌더링 |
| `toggleWeekRoom(weekBoard, roomId)` | 주 전체 합주실 활성/비활성 토글 |
| `applyBookingRoomVisibilityForDate(dateKey)` | 비활성 합주실 카드 숨김·재배치 |
| `renderBookingRoomSplitGuidesForGrid(grid)` | 합주실 컬럼 분할선 렌더링 |
| `buildHoverOverlayTextHtml(...)` | 마우스 오버 시 멤버 충돌 요약 HTML |
| `initBookingToolControls()` | 예약 확정 뷰 초기화 (bookingToolsEnabled 전용) |
| `bindWeekRoomToggleHandler()` | 합주실 토글 클릭 핸들러 등록 (뷰 무관) |
| `isRoomSlotLayoutEnabled()` | roomslot 모드 여부 판단 |
| `bookingToolsEnabled()` | 예약 확정 뷰 + 매니저 여부 판단 |

**연관 파일:**
- `matching_views.py` → context 제공 (`schedule_match_run`, `schedule_final`, `schedule_booking_start`)
- `extra_practice_ui_style.md` → CSS 스타일 레퍼런스

---

### `pracapp/views/matching_views.py`
**라인 수:** ~2,850줄
**역할:** 자동 매칭 알고리즘 실행부터 최종 시간표 확정까지 전체 흐름 처리.

**주요 함수:**
| 함수 | 역할 |
|---|---|
| `schedule_match_settings()` | 매칭 파라미터 설정 화면 |
| `schedule_match_run()` | 자동 매칭 실행 + 결과 조율 화면 |
| `schedule_final()` | 최종 시간표 확인 화면 (FINAL_CONFIRMED 포함) |
| `schedule_booking_start()` | 예약 확정 단계 진입 |
| `schedule_save_result()` | 최종 시간표 DB 저장 |
| `schedule_move_event()` | 드래그 이동 API |
| `schedule_match_work_draft_save()` | 작업 임시저장 |
| `schedule_room_block_manage()` | 합주실 블록 관리 |
| `_sync_room_blocks_for_confirmed_schedule()` | 확정 시간표 → RoomBlock 동기화 |

**의존 관계:**
- `utils.py`: `_recompute_forced_flags`, `_build_song_conflict_and_member_maps`, `auto_schedule_match`
- `_meeting_common.py`: 권한 체크, 공통 컨텍스트
- 렌더링 템플릿: `match_result.html`, `match_settings.html`

---

### `pracapp/utils.py`
**라인 수:** ~2,150줄
**역할:** 스케줄 알고리즘·가용성 계산 유틸리티. 매칭 뷰와 기타 뷰가 공통으로 호출.

**주요 함수:**
| 함수 | 역할 |
|---|---|
| `auto_schedule_match(...)` | 자동 매칭 알고리즘 (제약 만족) |
| `_build_user_unavailable_reason_map(...)` | 멤버별 불가능 슬롯 맵 생성 |
| `_recompute_forced_flags(...)` | 강제 배치 여부 재계산 |
| `_build_song_conflict_and_member_maps(...)` | 곡 충돌·멤버 가용성 맵 생성 |
| `_get_multi_room_intersection(...)` | 여러 멤버 공통 가용 시간 교집합 |
| `calculate_user_schedule(...)` | 반복/일회성 블록 + 예외 적용해 가용 일정 계산 |
| `confirm_and_save_schedule(...)` | 스케줄 블록 DB 저장 |
| `group_schedule_by_week(...)` | 주별 그룹핑 (보드 표시용) |

---

### `pracapp/models.py`
**라인 수:** ~710줄
**역할:** 전체 앱 ORM 스키마.

**주요 모델:**
| 모델 | 역할 |
|---|---|
| `User` | 커스텀 유저 (AbstractUser 확장, 악기/닉네임) |
| `Band` | 밴드 그룹 |
| `Meeting` | 합주 이벤트 (상태: OPEN → FINAL_CONFIRMED) |
| `Song` / `Session` | 합주 곡 / 세션(파트) |
| `PracticeRoom` | 합주실 (임시합주실 포함) |
| `RoomBlock` | 합주실 사용 불가 시간대 |
| `PracticeSchedule` | 확정 합주 배정 |
| `ExtraPracticeSchedule` | 추가 합주 배정 |
| `RecurringBlock` / `OneOffBlock` / `RecurringException` | 멤버 가용성 블록 |
| `MeetingFinalDraft` / `MeetingWorkDraft` | 임시 작업 드래프트 |
| `MeetingScheduleConfirmation` | 멤버별 시간표 확인 상태 |

---

### `pracapp/views/meeting_views.py`
**라인 수:** ~1,400줄
**역할:** 미팅 CRUD, 참가자 승인, 세션 신청 관리.

**주요 함수/클래스:**
- `MeetingDetailView` — 탭 기반 상세 페이지 (곡/세션/참가자/스케줄)
- `MeetingCreateView` / `MeetingUpdateView` — 미팅 생성·수정
- `meeting_join_request()`, `meeting_participant_approve()` — 참가 신청·승인
- `reset_all_assignments()`, `random_assign_all()` — 세션 배정 초기화·랜덤

---

### `pracapp/views/extra_practice_views.py`
**라인 수:** ~500줄
**역할:** 추가 합주 스케줄 편집 (assignee 또는 매니저가 직접 배치).

**주요 함수:**
- `extra_practice()` — GET: 주차 보드 + 불가능 오버레이 데이터 제공
- `extra_practice_save()` — POST: ExtraPracticeSchedule + RoomBlock 생성
- `extra_practice_delete()` — POST: 삭제
- `_build_room_block_maps()` — 합주실 불가 맵 생성
- `_build_song_conflict_map_for_week()` — 같은 멤버 충돌 감지

**스타일 레퍼런스:** `docs/extra_practice_ui_style.md`

---

### `pracsite/urls.py`
**라인 수:** ~95줄
**역할:** 전체 URL 라우팅.

**주요 URL 그룹:**
- `/band/` — 밴드 관리
- `/meeting/<uuid>/` — 미팅 상세·관리
- `/meeting/<uuid>/match/` — 매칭 설정·실행·결과
- `/meeting/<uuid>/final/` — 최종 시간표
- `/meeting/<uuid>/song/<uuid>/extra-practice/` — 추가 합주
- `/schedule/` — 개인 일정 설정

---

## 아키텍처 메모

```
urls.py
  └─ views/
       ├─ matching_views.py   ← 가장 복잡한 뷰, match_result.html 렌더링
       ├─ meeting_views.py    ← 미팅 라이프사이클 전반
       ├─ extra_practice_views.py
       ├─ song_session_views.py
       ├─ schedule_views.py
       ├─ band_views.py
       └─ _meeting_common.py  ← 공통 권한·컨텍스트 헬퍼
  └─ utils.py                ← 스케줄 알고리즘 (matching_views 등이 import)
  └─ models.py               ← ORM 스키마
  └─ templates/
       ├─ match_result.html  ← 최대 단일 파일 (~10,000줄), CSS+HTML+JS 포함
       └─ meeting_detail.html ← 두 번째로 큰 템플릿 (~3,900줄)
```

**주의사항:**
- `match_result.html` 수정 시 CSS 변수(`--slot-h`, `--ep-primary`)와 JS 함수 간 의존관계 파악 필수
- `bookingToolsEnabled()` vs `isRoomSlotLayoutEnabled()` 구분 중요 (혼용 시 뷰별 동작 차이 발생)
- `matching_views.py`의 `schedule_final`과 `schedule_match_run`은 모두 `match_result.html`을 렌더링하지만 컨텍스트 플래그(`is_final_view`, `is_booking_confirm_view` 등)로 동작이 달라짐
