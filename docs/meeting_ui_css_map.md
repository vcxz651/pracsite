# Meeting UI CSS Responsibility Map

선행 읽기:
1. `docs/project_overview.md`
2. `docs/ai_working_rules.md`
3. `docs/ai_task_triage_checklist.md`

이 문서는 `meeting_detail` 화면의 CSS 책임 범위를 정리한 문서다. 기능 동작 기준은 관련 SSOT를 먼저 보고, 스타일 책임만 이 문서로 판단한다.

파일: `pracapp/templates/pracapp/meeting_detail.html`

## 공통 레이아웃
- `.song-main-row`
- `.song-meta-col`
- `.song-session-col`
- `.song-footer-row`
- `.session-grid`, `.session-grid-wrapper`

## 번호열
- `.song-order-badge`
- `.js-song-card`의 좌측 패딩(번호열 공간)

## 일반인 인터랙션
- `.song-main-interactive`
- `.song-footer-collapsible`, `.is-expanded`
- JS: 본문 클릭/키보드 토글 로직
- 현재 규칙:
  - 모바일보다 큰 화면에서는 세션 칸이 항상 같은 줄에 보인다
  - 기본값은 접힘이지만, 세션 칸 자체는 숨기지 않는다
  - 일반 멤버 곡 카드 배경은 상태와 무관하게 흰색 고정

## 펼침 상태 정렬 제어
- `.js-song-card.song-applicants-expanded .song-session-col`
- `.js-song-card.song-applicants-expanded .session-grid`
- `.js-song-card.song-applicants-expanded .session-grid > div`

## 관리자 전용 오버라이드
- `.manager-page .song-main-row`
- `.manager-page .song-meta-col`
- `.manager-page .song-session-col`
- `.manager-page .song-footer-row`

## 세션 텍스트/카운트
- `.btn-truncate` (기본 텍스트 굵기)
- `.js-session-slot-btn.session-assigned-text`
- `.session-applicant-count-badge`

## 유지보수 원칙
- 관리자/일반인 분기 스타일은 반드시 `.manager-page` 기준으로 좁힐 것
- 레이아웃(폭/패딩)과 상태 효과(hover/expanded)를 섞어 수정하지 말 것
- JS가 토글하는 클래스와 CSS 셀렉터를 1:1 대응으로 유지할 것
- 일반 멤버 데스크톱 레이아웃에서 세션 칸 visibility를 footer collapse 로직과 분리해서 다룰 것
