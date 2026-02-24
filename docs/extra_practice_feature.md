# 추가 합주 잡기 기능

> 작성일: 2026-02-24
> 관련 브랜치: main

---

## 개요

최종 합주 시간표(`FINAL_CONFIRMED`)가 확정된 뒤, 실제 합주가 진행되는 1~2주차에 특정 곡의 **추가 합주**가 필요한 경우를 위한 기능이다.

| 항목 | 내용 |
|---|---|
| 기존 자동 매칭과의 관계 | 완전히 분리 — 별도 모델(`ExtraPracticeSchedule`), 별도 보드 |
| 사용 시점 | FINAL_CONFIRMED 이후 합주 진행 1~2주차 |
| 누가 사용하나 | 해당 곡의 **Session.assignee** 또는 **미팅 관리자** |
| 확정 방식 | 즉시 확정 (승인 절차 없음) |
| 합주실 | 밴드 등록 합주실 선택 + **임시합주실 생성 가능** (밴드 합주실 신규 등록 불가) |
| 충돌 방지 | 저장 시 `RoomBlock`도 함께 생성 → 다른 미팅의 매칭/예약에서 차단 |

---

## 타임라인

```
합주 확정(FINAL_CONFIRMED)
    ↓  ~1개월
합주 1주차 시작  ← 추가합주 필요 시 이 시점부터 사용
합주 2주차 시작
    ...
```

---

## 진입점: schedule_final 화면의 곡 카드

`schedule_final` 보드(`match_result.html`)에서 곡 카드(`.board-event`) 우하단에 **"+합주" 버튼**이 조건부로 표시된다.

**버튼 노출 조건** (둘 중 하나)
- `isManagerRole === true` (매니저)
- `songParticipantSongIds.has(songId)` (현재 로그인 유저가 해당 곡의 Session.assignee)

버튼은 `isConfirmedFinal`(`FINAL_CONFIRMED` 상태)일 때만 렌더되며, JS 초기화 시점에 Set 조회로 `d-none`을 제거한다.

### 관련 코드

**`matching_views.py` — `schedule_final`**
```python
context['song_participant_song_ids_json'] = json.dumps([
    str(sid) for sid in Session.objects.filter(
        song__meeting=meeting,
        assignee=request.user,
    ).values_list('song_id', flat=True).distinct()
])
```

**`match_result.html`**
```javascript
const songParticipantSongIds = new Set(
    JSON.parse('{{ song_participant_song_ids_json|default:"[]"|escapejs }}')
);

// 초기화 시 버튼 표시
if (isConfirmedFinal) {
    document.querySelectorAll('.js-extra-practice-btn').forEach((btn) => {
        const songId = String(btn.dataset.songId || '');
        if (isManagerRole || songParticipantSongIds.has(songId)) {
            btn.classList.remove('d-none');
        }
    });
}
```

---

## 데이터 모델: `ExtraPracticeSchedule`

파일: `pracapp/models.py`

```python
class ExtraPracticeSchedule(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    meeting      = models.ForeignKey(Meeting, on_delete=models.CASCADE,
                                     related_name='extra_practice_schedules')
    song         = models.ForeignKey(Song, on_delete=models.CASCADE,
                                     related_name='extra_practice_schedules')
    room         = models.ForeignKey(PracticeRoom, on_delete=models.CASCADE,
                                     related_name='extra_practice_schedules')
    date         = models.DateField()
    start_index  = models.IntegerField()   # 18~47 (30분 슬롯, 09:00~24:00)
    end_index    = models.IntegerField()   # start_index < end_index
    created_by   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, related_name='created_extra_practices')
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('room', 'date', 'start_index')   # 같은 방·날짜·시작슬롯 중복 불가
        indexes = [
            models.Index(fields=['meeting', 'song'],        name='eps_meeting_song_idx'),
            models.Index(fields=['meeting', 'date'],        name='eps_meeting_date_idx'),
            models.Index(fields=['room', 'date', 'start_index'], name='eps_room_date_start_idx'),
        ]
```

**슬롯 인덱스 기준**: `start_index=18` → 09:00, `end_index=48` → 24:00. 슬롯 1개 = 30분.

---

## URL 구조

| URL | 이름 | 메서드 |
|---|---|---|
| `/meeting/<uuid>/song/<uuid>/extra-practice/` | `extra_practice` | GET |
| `/meeting/<uuid>/song/<uuid>/extra-practice/save/` | `extra_practice_save` | POST |
| `/meeting/<uuid>/song/<uuid>/extra-practice/delete/` | `extra_practice_delete` | POST |

---

## 뷰 설명 (`pracapp/views/extra_practice_views.py`)

### 권한 헬퍼

```python
def _is_song_participant_or_manager(meeting, song, user):
    is_manager = has_meeting_manager_permission(meeting, user)
    if is_manager:
        return True
    return Session.objects.filter(song=song, assignee=user).exists()
```

권한 실패 시 GET은 `Http404`, POST는 `403 JSON`으로 응답한다.

---

### `extra_practice` (GET)

주요 파라미터: `?week_offset=N` (기본 0 = 이번 주, 음수 = 과거 주, 양수 = 미래 주)

**보드 데이터 구성**

| context 키 | 내용 | 함수 |
|---|---|---|
| `room_block_map_json` | 합주실별 차단 슬롯 (주황 오버레이용) | `_build_room_block_maps()` |
| `room_block_detail_map_json` | 차단 슬롯 상세 사유 (툴팁용) | `_build_room_block_maps()` |
| `song_conflict_map_json` | 해당 곡 assignee들의 불가능 시간 (빨간 패턴용) | `_build_song_conflict_map_for_week()` |
| `existing_schedules_json` | 기존 PracticeSchedule + 다른 곡 ExtraPracticeSchedule (배경 회색 카드) | `_build_existing_schedules_json()` |
| `my_extra_schedules_json` | 이 곡의 ExtraPracticeSchedule 전체 (편집/삭제 가능 컬러 카드) | `_build_my_extra_schedules_json()` |
| `room_list_json` | 밴드 합주실 + 임시합주실 목록 | `available_rooms_qs(include_temporary=True)` |

**주 범위 계산**

```python
def _week_bounds(week_offset: int):
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(weeks=week_offset)
    sunday = monday + datetime.timedelta(days=6)
    return monday, sunday
```

`RoomBlock` 조회 시 `exclude_meeting=meeting`을 적용해 이 미팅 자체의 블록은 제외 (현재 곡 배치가 자기 자신을 차단하는 문제 방지).

---

### `extra_practice_save` (POST)

**요청 body (JSON)**

```json
{
  "date": "2026-03-15",
  "start_index": 20,
  "end_index": 24,
  "room_id": "<uuid>",

  // 임시합주실인 경우 추가
  "is_temp_room": true,
  "room_name": "소강당",
  "room_location": "본관 3층"
}
```

**처리 순서**
1. 파라미터 검증 (`18 <= start < end <= 48`)
2. 합주실 결정
   - `is_temp_room=true` → `PracticeRoom.get_or_create(band=..., name=..., is_temporary=True)`
   - 그 외 → `PracticeRoom.objects.get(id=room_id, band=meeting.band)`
3. 중복 체크 (겹치는 시간 범위 쿼리)
   - `PracticeSchedule` 충돌 → 409
   - `ExtraPracticeSchedule` 충돌 → 409
4. `ExtraPracticeSchedule.objects.create(...)`
5. `RoomBlock.objects.create(source_meeting=meeting, ...)` — 다른 미팅 매칭 충돌 방지

**응답 (성공)**
```json
{
  "status": "ok",
  "schedule_id": "<uuid>",
  "block_id": "<uuid>",
  "room_id": "<uuid>",
  "room_name": "소강당",
  "room_location": "본관 3층",
  "is_temporary": true
}
```

---

### `extra_practice_delete` (POST)

**요청 body**
```json
{ "schedule_id": "<uuid>" }
```

**권한**: `created_by == request.user` 또는 매니저

**처리**: ExtraPracticeSchedule 삭제 → 연관 RoomBlock(`room, date, start_index, end_index, source_meeting` 일치) 삭제

---

## 보드 UI (`pracapp/templates/pracapp/extra_practice.html`)

### 구성 요소

```
[← 이전 주]   2026년 3월 1주차   [다음 주 →]              [← 최종 시간표로]

[합주실 탭: 합주실A | 합주실B | ... | + 임시합주실 추가]

┌─ 7일 × 시간 그리드 ──────────────────────────────────────────┐
│  RoomBlock 오버레이        (주황 해칭, 툴팁: 차단 사유)          │
│  멤버 불가능 패턴           (빨간 해칭, 툴팁: 누가 안 되는지)      │
│  기존 PracticeSchedule     (배경 회색 카드, 읽기 전용)           │
│  다른 곡 ExtraPractice     (배경 회색 카드, 읽기 전용)           │
│  이 곡의 ExtraPractice     (컬러 카드 — 삭제 버튼 포함)          │
│  드래그 배치 → 즉시 save API 호출 → 보드 갱신                    │
└──────────────────────────────────────────────────────────────┘

[사이드 패널]
  배치 전: 드래그 소스 카드 (곡명)
  배치 후 목록: 날짜 / 시간 / 합주실 + 삭제 버튼
```

### 주요 JS 동작

| 기능 | 설명 |
|---|---|
| 주 이동 | `?week_offset=N` 쿼리스트링으로 페이지 이동 |
| 합주실 탭 전환 | 탭 클릭 → 해당 합주실 컬럼만 표시 |
| 임시합주실 추가 | `prompt()`로 이름 입력 → 탭 동적 추가 → 배치 시 save API에 `is_temp_room: true` 전달 |
| 드래그 배치 | 사이드패널 소스 카드 → 그리드 드롭 → `calcDropTarget()` → save API 호출 |
| 불가능 오버레이 | `isRoomBlockedAtSlot(date, roomId, slot)`, `getUnavailableNames(date, slot)` |
| 카드 삭제 | 삭제 버튼 → delete API → 카드 + 사이드 목록 항목 제거 |
| 토스트 알림 | 저장/삭제/에러 피드백 |

---

## 수정된 파일 목록

| 파일 | 변경 내용 |
|---|---|
| `pracapp/models.py` | `ExtraPracticeSchedule` 모델 추가 |
| `pracapp/migrations/0039_add_extra_practice_schedule.py` | 마이그레이션 |
| `pracapp/views/extra_practice_views.py` | **신규** — GET/save/delete 3개 뷰 + 4개 헬퍼 함수 |
| `pracapp/views/__init__.py` | `extra_practice`, `extra_practice_save`, `extra_practice_delete` export 추가 |
| `pracsite/urls.py` | URL 3개 추가 (lines 69-71) |
| `pracapp/templates/pracapp/extra_practice.html` | **신규** — 전용 배치 보드 템플릿 |
| `pracapp/views/matching_views.py` | `schedule_final` context에 `song_participant_song_ids_json` 추가 |
| `pracapp/templates/pracapp/match_result.html` | `.btn-extra-practice` CSS, `songParticipantSongIds` JS Set, "+합주" 버튼 조건부 렌더 |

---

## 주요 설계 결정 & 이유

### PracticeSchedule과 모델 분리
기존 `PracticeSchedule`은 자동 매칭 결과를 담는다. 추가 합주는 미팅 상태(DRAFT/BOOKING 등)와 무관하고 즉시 확정되므로, 별도 `ExtraPracticeSchedule`로 분리해 관심사를 구분한다.

### RoomBlock 동시 생성
저장 시 `RoomBlock(source_meeting=meeting)`을 함께 생성해 다른 미팅의 자동 매칭/예약 화면에서 해당 시간대가 차단 표시된다. 삭제 시에는 RoomBlock도 함께 삭제.

### 주 단위 날짜 범위
추가 합주는 실제 합주 진행 주차에 이루어지므로 "오늘이 포함된 주"가 기본값으로 적절하다. 화살표 버튼으로 ±N주 이동 가능(`week_offset` 쿼리파라미터).

### 불가능 오버레이 데이터 소스
- **RoomBlock**: `_build_room_block_maps()` — 다른 미팅 점유 + 수동 블록 (주황 표시)
- **멤버 불가능**: `_build_song_conflict_map_for_week()` — 해당 곡 assignee들의 MemberAvailability + 기타 불가 사유 (빨간 패턴)

기존 `_build_song_conflict_and_member_maps()`는 미팅의 `practice_start/end` 기간에 묶여 있어 사용하지 않고, `_build_user_unavailable_reason_map()`을 직접 호출해 주 범위로 계산한다.

### 임시합주실 처리
`PracticeRoom.get_or_create(band=..., name=..., is_temporary=True)` — 같은 이름이면 재사용. 밴드 정식 합주실 신규 등록은 이 화면에서 불가.

---

## 검증 체크리스트

- [ ] assignee 유저로 schedule_final 진입 → 본인 곡 카드에만 "+합주" 버튼 노출
- [ ] 매니저로 진입 → 모든 곡 카드에 버튼 노출
- [ ] 비assignee·비매니저 유저가 extra-practice URL 직접 접근 → 404
- [ ] extra_practice 보드에서 불가능 오버레이(주황/빨간) 렌더링 확인
- [ ] 카드 드래그 배치 → DB에 `ExtraPracticeSchedule` + `RoomBlock` 생성 확인
- [ ] 같은 방·시간 중복 배치 → 409 응답 + 토스트 에러
- [ ] 삭제 → `ExtraPracticeSchedule` + `RoomBlock` 함께 삭제 확인
- [ ] 임시합주실 추가 후 배치 → `PracticeRoom(is_temporary=True)` 생성 확인
- [ ] 주 이동(← →) 동작 확인
