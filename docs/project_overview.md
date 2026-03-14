# Project Overview

이 문서는 **프로젝트를 처음 보는 AI 작업자**가 기능 문서를 읽기 전에
"이 앱이 무엇을 하는지"를 빠르게 파악하도록 돕는 최상위 개요다.

원칙:
- 상세 동작 기준은 이 문서가 아니라 각 기능별 SSOT 문서에서 판단한다.
- 이 문서는 전체 구조, 용어, 코드 진입점을 빠르게 이해시키는 용도다.

---

## 1. 프로젝트 한 줄 요약

이 프로젝트는 밴드 합주 일정을 관리하는 Django 앱이다.
관리자와 일반 멤버가 같은 미팅 안에서 곡/세션/참가/가용 시간/매칭/합주실 예약/최종 일정 공유를 진행한다.

핵심 목표:
- 멤버별 가능한 시간을 모은다.
- 곡별 필요한 세션과 인원을 정리한다.
- 자동/수동 매칭으로 합주 일정을 잡는다.
- 합주실 예약과 최종 확정을 거쳐 공유 가능한 시간표를 만든다.

---

## 2. 주요 사용자

### 2-1. 관리자(매니저)

- 미팅 생성/수정
- 참가자 승인/거절/관리
- 곡/세션 구성 관리
- 자동 매칭 실행
- 조율 보드 수정
- 예약 단계 진입 및 최종 일정 확정

### 2-2. 일반 멤버

- 미팅 참여 신청
- 세션 지원
- 개인 일정(가용 시간) 입력
- 확정된 일정 확인
- 필요한 경우 추가 합주 일정 확인/참여

---

## 3. 기능 지도

### 3-1. 미팅 상세(`meeting_detail`)

중심 화면:
- 곡 목록
- 세션 지원/배정
- 참가자 상태
- 스케줄 진입 링크

주요 코드:
- `pracapp/templates/pracapp/meeting_detail.html`
- `pracapp/views/meeting_views.py`
- `pracapp/views/song_session_views.py`

### 3-2. 매칭/조율/예약/최종 일정

중심 흐름:
- 자동 매칭 실행
- 결과 보드 조정
- 예약 확정 단계
- 최종 일정 확정/공유

주요 코드:
- `pracapp/templates/pracapp/match_result.html`
- `pracapp/views/matching_views.py`
- `pracapp/models.py`
- `pracapp/utils.py`

상세 기준 문서:
- `docs/meeting_handover.md`
- `docs/meeting_process_state_machine.md`
- `docs/meeting_regression_checklist.md`

### 3-3. 개인 일정

중심 흐름:
- 반복 가능 시간 입력
- 일회성 일정/예외 입력
- 홈 주간보드 및 매칭 계산에 반영

주요 코드:
- `pracapp/views/schedule_views.py`
- `pracapp/templates/pracapp/schedule_step2.html`
- `pracapp/templates/pracapp/schedule_step3.html`
- `pracapp/views/home_views.py`
- `pracapp/templates/pracapp/home.html`

### 3-4. 데모 페이지

목적:
- 공개 체험용 시나리오 A 진입과 기능 설명 흐름 제공
- 인트로 페이지 + 자동 매칭 보드 + `/demo/tutorial/` 인터랙티브 튜토리얼

주요 코드:
- `pracapp/views/demo_views.py`
- `pracapp/templates/pracapp/demo/`
- `pracapp/static/pracapp/js/tutorial_demo.js`
- `pracapp/templates/pracapp/demo/demo_feature_tutorial.html`

상세 기준 문서:
- `docs/demo_page_plan.md`

### 3-5. 추가 합주

목적:
- 본 매칭/예약 흐름과 별도로 추가 합주 스케줄을 잡는다.

주요 코드:
- `pracapp/views/extra_practice_views.py`
- `pracapp/templates/pracapp/extra_practice.html`
- `pracapp/models.py` (`ExtraPracticeSchedule`)

상세 기준 문서:
- `docs/extra_practice_feature.md`
- `docs/extra_practice_ui_style.md`

---

## 4. 핵심 도메인 용어

- `Meeting`: 합주 이벤트 단위. 전체 일정 조율의 중심 엔티티.
- `Song`: 미팅에서 다루는 곡.
- `Session`: 곡별 파트(보컬, 기타, 드럼 등).
- `MeetingWorkDraft`: 조율 중 임시 작업본.
- `MeetingFinalDraft`: 최종 확정 직전/직후의 기준 초안.
- `MeetingScheduleConfirmation`: 멤버별 최종 일정 확인 상태.
- `PracticeRoom`: 합주실. 임시 합주실 개념이 섞일 수 있으므로 무결성 주의.
- `RoomBlock`: 합주실 사용 불가 시간대.
- `RecurringBlock`: 반복되는 개인 일정 블록.
- `OneOffBlock`: 일회성 개인 일정 블록.
- `RecurringException`: 반복 일정의 예외.
- `ExtraPracticeSchedule`: 추가 합주 배정 데이터.

상태/무결성 판단은 아래 문서를 기준으로 본다.
- `docs/meeting_process_state_machine.md`
- `docs/meeting_integrity_rules.md`

---

## 5. Django 구조

### 5-1. 앱 구조

- `pracapp/`: 실제 기능 대부분이 들어있는 메인 앱
- `pracsite/`: 프로젝트 설정 및 URL 라우팅
- `templates/`: 공통 베이스 템플릿
- `docs/`: AI 작업자용 작업 기준 문서

### 5-2. 코드 읽기 우선순위

- URL 흐름 확인: `pracsite/urls.py`
- 데이터 구조 확인: `pracapp/models.py`
- 화면 동작 확인: `pracapp/views/*.py` + `pracapp/templates/pracapp/*.html`
- 대형 파일 탐색 부담이 크면: `docs/large_files_overview.md`

---

## 6. 가장 중요한 화면과 파일

우선순위가 높은 파일:
- `pracapp/templates/pracapp/meeting_detail.html`
- `pracapp/templates/pracapp/match_result.html`
- `pracapp/views/meeting_views.py`
- `pracapp/views/matching_views.py`
- `pracapp/models.py`
- `pracsite/urls.py`

이 파일들은 여러 기능의 교차점이라 작은 수정도 회귀 위험이 크다.

---

## 7. 첫 작업 전에 해야 할 일

1. `docs/README.md`에서 작업 주제별 스타팅 맵을 확인한다.
2. `docs/ai_working_rules.md`에서 공통 가드레일을 먼저 읽는다.
3. 이번 작업의 기능별 SSOT 문서 1개를 먼저 읽는다.
4. 코드 진입점은 `docs/meeting_reference_pages.md`로 확인한다.

이 문서만으로 구현 판단을 내리지 말고, 반드시 기능별 문서까지 내려가서 작업한다.

---

## 8. 현재 로드맵 메모

### 8-1. 배포 후 바로 할 일

- 대형 소스파일 리팩토링
- 특히 `match_result.html`, `meeting_detail.html`, 관련 대형 view 파일의 역할 분리와 구조 정리를 우선 검토한다.

### 8-2. 중장기 목표

- 커뮤니티 기능 추가
- `연합공연` 기능 추가
- 합주실 독립 모델을 본격 가동할 수 있는 구조로 정리

### 8-3. 장기 목표

- 실제 합주실 페이지/시스템과 연동
