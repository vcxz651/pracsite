# 튜토리얼 페이지 기획안

작성일: 2026-02-24
상태: 기획 확정(구현 대기)

---

## 0. 이 문서의 목적

이 서비스를 처음 보는 사람이 읽어도 튜토리얼 페이지를 빠짐없이 구현할 수 있도록 작성한다.
서비스 배경부터 구현 상세까지 단일 문서에서 완결한다.

---

## 1. 서비스 요약 (이 앱이 무엇인가)

**밴드 합주 선곡회의 스케줄링 서비스**다.

밴드 관리자가 "이번 달에 어떤 곡을 언제 어느 합주실에서 연습할지"를 자동으로 매칭하고, 멤버들과 공유·확정하는 전 과정을 처리한다.

### 전체 워크플로우 (이 순서가 핵심)

```
밴드 생성
  └→ 멤버 가입 신청 / 관리자 승인
  └→ 합주실 등록
       └→ 선곡회의(Meeting) 생성
            └→ 곡(Song) 등록
            └→ 세션 지원 (각 곡에 기타/보컬/드럼 등 파트 신청)
            └→ 세션 배정 (관리자 확정)
                 └→ 자동 매칭 실행
                      └→ 수동 조율 (드래그앤드롭으로 카드 이동/리사이즈)
                      └→ 임시 저장 / 공유
                           └→ 예약 반영 (합주실 예약 확정 처리)
                                └→ 최종 확정 → 멤버 공유 → 멤버 확인(ack)
```

### 핵심 상태 전이 (Meeting 기준)

| 상태 | 의미 |
|---|---|
| `DRAFT_MATCHING` | 자동/수동 매칭 결과를 조정 중 |
| `BOOKING_IN_PROGRESS` | 실제 합주실 예약 반영 단계 |
| `FINAL_SHARED` | 최종안 공유됨, 멤버 확인 수집 중 |
| `FINAL_CONFIRMED` | 최종 확정, 이후 변경 불가 |

### 주요 화면 (URL → 역할)

| URL 패턴 | 역할 |
|---|---|
| `/meeting/<uuid>/` | 선곡회의 상세 (곡 목록, 세션 지원/배정) |
| `/meeting/<uuid>/match/settings/` | 매칭 조건 설정 |
| `/meeting/<uuid>/match/run/` | 자동 매칭 실행 (POST) |
| `/meeting/<uuid>/final/` | 매칭 결과/예약반영/최종 공유 화면 |
| `/schedule/confirm/` | 최종 확정 |
| `/dashboard/` | 내 밴드/회의 현황 |

---

## 2. 튜토리얼 페이지의 목적

| 항목 | 내용 |
|---|---|
| 대상 | 배포 후 처음 접속한 신규 유저 |
| 목적 | 실제 밴드/데이터 없이 전체 워크플로우를 직접 체험 |
| 핵심 가치 | 5~10분 안에 "이 서비스가 뭔지" 체감하게 한다 |
| 방식 | 샌드박스 환경 + 더미 데이터 자동 생성 + 단계별 안내 |
| 데이터 정책 | 체험 중 생성된 모든 데이터는 종료 시 자동 삭제 |

---

## 3. URL 구조

```
/tutorial/                    # 튜토리얼 소개 + 시작 버튼
/tutorial/start/              # (POST) 샌드박스 초기화 → 더미 데이터 생성 → step 1 리다이렉트
/tutorial/step/<int:step>/    # 단계별 안내 페이지 (1~6)
/tutorial/exit/               # (POST) 샌드박스 세션 종료 + 데이터 삭제
```

---

## 4. 샌드박스 설계

### 선택한 방식: 유저별 독립 인스턴스 생성

튜토리얼 시작(`/tutorial/start/`) 시:

1. 임시 유저 계정 자동 생성 (username: `tutorial_<uuid4 앞 8자>`)
2. 임시 Band 생성 (name: `[체험] 샌드박스 밴드`)
3. 더미 멤버 15명 자동 가입 (기존 `create_dummy.py` 로직 재활용)
4. 합주실 2개 자동 등록
5. 선곡회의(Meeting) 1개 자동 생성
6. 곡 10개 자동 등록 (밴드 음악 명곡 선정)
7. 더미 멤버들의 세션 지원 자동 완료 처리
8. 세션 ID를 세션(session)에 저장하여 이후 단계에서 재사용

세션에 저장하는 키:

```python
request.session['tutorial_mode'] = True
request.session['tutorial_step'] = 1
request.session['tutorial_user_id'] = <임시유저 pk>
request.session['tutorial_band_id'] = <밴드 uuid>
request.session['tutorial_meeting_id'] = <미팅 uuid>
```

### 종료/정리

- `/tutorial/exit/` 호출 시:
  `Band.objects.filter(id=tutorial_band_id).delete()` 한 번으로 연쇄 삭제 (cascade)
- 임시 유저 계정도 삭제
- 세션 키 전부 제거

### 다른 방안을 선택하지 않은 이유

| 방안 | 탈락 이유 |
|---|---|
| 읽기 전용 고정 demo 계정 | 다중 접속 시 동일 데이터 공유 → 충돌, 인터랙션 불가 |
| 별도 DB/스키마 | 인프라 복잡도 과다 |

---

## 5. 단계별 시나리오 (6단계)

튜토리얼 유저가 각 단계에서 실제로 클릭/입력하는 행위를 최소 1개 이상 포함한다.
더미 데이터는 미리 세팅되어 있어 "빈 화면" 상태를 유저에게 노출하지 않는다.

---

### Step 1 — 밴드와 선곡회의 둘러보기

**진입 URL**: `/meeting/<tutorial_meeting_id>/`
**화면**: `meeting_detail.html`

**사전 세팅 상태**:
- 밴드 멤버 15명 가입 승인 완료
- 합주실 2개 등록 완료
- 선곡회의 생성 완료
- 곡 10개 등록 완료

**유저 행동**:
- 화면을 스크롤하며 곡 목록, 멤버 현황 확인
- (가이드 박스) "우리 밴드에 10곡이 등록되어 있습니다. 다음 단계에서 곡을 하나 직접 추가해볼게요."

---

### Step 2 — 곡 직접 추가하기

**진입 URL**: `/meeting/<tutorial_meeting_id>/song/create/`
**화면**: `SongCreateView` 폼

**사전 세팅 상태**: Step 1 그대로

**유저 행동**:
- 곡명, 아티스트, 세션 구성(기타/보컬 등) 입력
- 저장 → 선곡회의 상세로 돌아와 목록에서 추가된 곡 확인

**가이드 포인트**:
"직접 추가한 곡도 자동 매칭에 포함됩니다."

---

### Step 3 — 세션 지원하기

**진입 URL**: `/meeting/<tutorial_meeting_id>/` (Step 1 화면)
**핵심 기능**: `session_apply` AJAX

**사전 세팅 상태**:
- 더미 멤버들은 자신의 세션에 이미 지원 완료
- 튜토리얼 유저는 아직 미지원 상태

**유저 행동**:
- 특정 곡의 세션 버튼 클릭 → 지원 완료 표시(AJAX) 확인
- 지원자 수 배지가 +1 되는 것 확인

**가이드 포인트**:
"지원을 완료하면 관리자가 배정합니다. 이번 체험에서는 배정도 자동으로 처리해두었습니다."

---

### Step 4 — 자동 매칭 실행하기

**진입 URL**: `/meeting/<tutorial_meeting_id>/match/settings/`
**화면**: `match_settings.html` → `match_result.html`

**사전 세팅 상태**: 세션 배정 완료 처리

**유저 행동**:
- 매칭 조건(합주실 수, 주차 수, 시간대) 기본값 확인
- "매칭 실행" 버튼 클릭 → 로딩 → `match_result.html` 진입
- 주차별로 자동 배치된 카드 확인

**가이드 포인트**:
"어떤 곡을 언제, 어느 합주실에서 연습할지 자동으로 계산했습니다.
배치가 마음에 들지 않으면 직접 조율할 수 있습니다."

---

### Step 5 — 수동 조율 & 예약 반영

**진입 URL**: `/meeting/<tutorial_meeting_id>/final/` (match_result.html)
**핵심 기능**: 드래그앤드롭 카드 이동, 리사이즈, 예약 반영 단계 진입

**유저 행동**:
- 보드에서 카드를 드래그하여 다른 시간대로 이동
- 카드 상단/하단 엣지 드래그로 30분 단위 리사이즈
- "예약 반영" 버튼 클릭 → `BOOKING_IN_PROGRESS` 단계 진입 확인

**가이드 포인트**:
"마음에 들지 않는 배치는 직접 옮길 수 있습니다.
조율이 끝나면 예약 반영 단계로 넘어갑니다."

**모바일 처리**:
터치 드래그가 지원되지 않을 수 있으므로 모바일에서는 드래그 대신 설명 + 스크린샷으로 대체한다.

---

### Step 6 — 최종 확정 & 멤버 공유

**진입 URL**: `/meeting/<tutorial_meeting_id>/final/` (최종 공유 모드)
**핵심 기능**: `schedule_final_acknowledge`, `schedule_confirm`

**유저 행동**:
- 최종 일정표 확인
- "확인했습니다" 버튼 클릭 (멤버 ack 체험)
- (선택) "최종 확정" 버튼 클릭

**가이드 포인트**:
"멤버들이 확인 버튼을 누르면 관리자가 최종 확정할 수 있습니다.
확정 이후에는 수정이 불가능합니다."

**완료 화면**:
모든 단계 완료 후 `/tutorial/` 홈으로 돌아가며 "체험이 완료되었습니다. 실제로 시작하려면 회원가입하세요." 안내

---

## 6. 공통 UI 컴포넌트

### 6-1. 고정 상단 배너 (샌드박스 표시)

```
┌─────────────────────────────────────────────────────────────────┐
│  [샌드박스 체험 중] 이 데이터는 실제 저장되지 않습니다    [체험 종료] │
└─────────────────────────────────────────────────────────────────┘
```

- 모든 튜토리얼 화면 최상단에 고정
- `[체험 종료]` 클릭 → `/tutorial/exit/` POST → 홈 리다이렉트
- CSS: 눈에 띄는 배경색(주황 또는 노랑 계열), z-index 최상위

### 6-2. 진행 단계 인디케이터

```
① 둘러보기  →  ② 곡 추가  →  [③ 세션 지원]  →  ④ 매칭  →  ⑤ 조율  →  ⑥ 확정
                                 (현재 단계 강조)
```

- 배너 아래 또는 가이드 박스 상단에 위치
- 완료된 단계: 체크 표시 + 비활성 스타일
- 현재 단계: 강조 스타일

### 6-3. 플로팅 가이드 박스

```
┌─────────────────────────────────────────────────────┐
│  👉 [안내 텍스트]                                    │
│                                   [다음 단계 →]     │
└─────────────────────────────────────────────────────┘
```

- 화면 우하단 또는 하단 중앙에 고정 플로팅
- 현재 단계에서 유저가 해야 할 행동을 1~2문장으로 안내
- `[다음 단계 →]` 버튼: `/tutorial/step/<n+1>/` 로 이동
- 기존 앱 화면을 가리지 않도록 반투명 또는 최소 높이 유지

### 6-4. 구현 방식

기존 앱 템플릿에 별도 튜토리얼 전용 뷰를 만들지 않는다.
기존 뷰(meeting_detail, match_result 등)를 그대로 사용하되, 컨텍스트에 `is_tutorial=True`, `tutorial_step=N`을 추가하고 템플릿에서 조건부로 배너/가이드 박스를 렌더링한다.

```python
# 기존 뷰 컨텍스트에 추가
context['is_tutorial'] = request.session.get('tutorial_mode', False)
context['tutorial_step'] = request.session.get('tutorial_step', 1)
```

```html
<!-- 기존 base.html 또는 각 템플릿 상단 -->
{% if is_tutorial %}
  {% include "pracapp/tutorial/tutorial_banner.html" %}
{% endif %}
```

---

## 7. 백엔드 구현 체크리스트

### 신규 파일

| 파일 | 역할 |
|---|---|
| `pracapp/views/tutorial_views.py` | 튜토리얼 시작/단계/종료 뷰 |
| `pracapp/templates/pracapp/tutorial/tutorial_home.html` | 소개 페이지 |
| `pracapp/templates/pracapp/tutorial/tutorial_banner.html` | 상단 배너 include 조각 |
| `pracapp/templates/pracapp/tutorial/tutorial_guide_box.html` | 플로팅 가이드 박스 include 조각 |
| `pracapp/templates/pracapp/tutorial/tutorial_complete.html` | 체험 완료 화면 |

### 기존 파일 수정

| 파일 | 수정 내용 |
|---|---|
| `pracsite/urls.py` | `/tutorial/` 관련 URL 4개 추가 |
| `pracapp/views/meeting_views.py` | `MeetingDetailView.get_context_data`에 `is_tutorial` 컨텍스트 주입 |
| `pracapp/views/matching_views.py` | `schedule_final`, `schedule_match_settings` 등에 `is_tutorial` 컨텍스트 주입 |
| `pracapp/templates/pracapp/meeting_detail.html` | 상단 배너/가이드 박스 조건부 include |
| `pracapp/templates/pracapp/match_result.html` | 상단 배너/가이드 박스 조건부 include |

### 더미 데이터 생성 함수

`create_dummy.py`의 로직을 함수로 추출하여 `tutorial_views.py`에서 호출한다.

```python
# tutorial_views.py (개략)
def tutorial_start(request):
    # 1. 임시 유저 생성
    # 2. 임시 밴드 생성
    # 3. 더미 멤버 15명 생성 및 가입 승인
    # 4. 합주실 2개 생성
    # 5. 미팅 생성
    # 6. 곡 10개 생성
    # 7. 세션 지원 자동 처리
    # 8. 세션에 tutorial_* 키 저장
    # 9. step 1으로 리다이렉트
```

### 데이터 삭제 함수

```python
def tutorial_exit(request):
    band_id = request.session.get('tutorial_band_id')
    user_id = request.session.get('tutorial_user_id')
    if band_id:
        Band.objects.filter(id=band_id).delete()  # cascade로 연쇄 삭제
    if user_id:
        User.objects.filter(id=user_id).delete()
    # 세션 키 전부 제거
    for key in ['tutorial_mode', 'tutorial_step', 'tutorial_user_id',
                'tutorial_band_id', 'tutorial_meeting_id']:
        request.session.pop(key, None)
    return redirect('home')
```

---

## 8. 튜토리얼 홈 (`/tutorial/`) 페이지 구성

```
────────────────────────────────────────────────
  5분 만에 합주 일정 자동화 체험하기

  실제 계정 없이 바로 시작할 수 있습니다.
  밴드 만들기부터 최종 일정 확정까지
  전 과정을 직접 경험해보세요.

  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │1. 둘러보기│  │2. 곡 추가│  │3. 세션지원│
  └──────────┘  └──────────┘  └──────────┘
  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │4. 자동매칭│  │5. 수동조율│  │6. 최종확정│
  └──────────┘  └──────────┘  └──────────┘

        [ 지금 바로 시작하기 ]   ← /tutorial/start/ POST

  체험 데이터는 종료 시 자동으로 삭제됩니다.
────────────────────────────────────────────────
```

---

## 9. 구현 우선순위

| 순서 | 항목 | 이유 |
|---|---|---|
| 1 | `/tutorial/start/` — 샌드박스 초기화 | 모든 단계의 기반 |
| 2 | 상단 배너 + step indicator 템플릿 조각 | 모든 단계에 공통 필요 |
| 3 | Step 4 (자동 매칭) 가이드 | 서비스 핵심 기능, 임팩트 최대 |
| 4 | Step 1~3 가이드 | 진입 흐름 완성 |
| 5 | Step 5~6 가이드 | 마무리 흐름 완성 |
| 6 | `/tutorial/exit/` — 데이터 삭제 | 운영 안정성 |
| 7 | 세션 만료 시 자동 정리 (Celery 또는 주기 cleanup) | 운영 안전망 |

---

## 10. 주의 및 제약 사항

| 항목 | 내용 |
|---|---|
| 데이터 격리 | 튜토리얼 유저는 자신의 `tutorial_band_id` 소속 데이터에만 접근 가능해야 함. 기존 뷰의 권한 검사가 이를 자연스럽게 보장하므로 별도 가드 불필요. |
| 동시 접속 | 유저마다 독립된 Band/Meeting 인스턴스를 생성하므로 데이터 충돌 없음. |
| 모바일 | Step 5 드래그앤드롭은 터치 미지원 가능성 있음. 모바일 감지 시 "PC에서 직접 체험해보세요" 안내 텍스트로 대체. |
| 재진입 | 세션이 살아있으면 `/tutorial/step/<n>/`으로 직접 접근 시 이어서 진행 가능. 세션 만료 시 `/tutorial/`로 리다이렉트. |
| 기존 뷰 회귀 | `is_tutorial` 컨텍스트 주입은 `get_context_data` 말미에 추가하며, 기존 로직을 변경하지 않는다. |
| 더미 데이터 이름 풀 | `docs/dummy_name_pool.md` 참고. 남성 1~15번 + 여성 1~15번 = 30명에서 15명 선택. |

---

## 11. 관련 문서 / 참고 파일

| 문서/파일 | 내용 |
|---|---|
| `docs/meeting_process_state_machine.md` | Meeting 상태 전이 전체 정의 |
| `docs/meeting_handover.md` | 핵심 프로세스 및 최근 수정 이력 |
| `docs/meeting_integrity_rules.md` | 데이터 무결성 규칙 |
| `docs/meeting_regression_checklist.md` | 회귀 테스트 체크리스트 |
| `docs/dummy_name_pool.md` | 더미 유저 이름 풀 80명 |
| `create_dummy.py` | 더미 데이터 생성 스크립트 (재활용 대상) |
| `pracapp/views/admin_views.py` | `reset_db_data` — 데이터 일괄 삭제 패턴 참고 |
| `pracsite/urls.py` | 전체 URL 구성 |
