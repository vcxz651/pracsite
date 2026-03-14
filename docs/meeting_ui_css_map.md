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
- `:root` 내부 meeting_detail 전용 색상/표면 토큰 (`--meeting-*`)도 이 파일 상단에서 함께 관리한다. 상태색/패널색뿐 아니라 border, shadow, hover 계층도 literal 추가보다 기존 토큰 재사용을 우선한다

## 번호열
- `.song-order-badge`
- `.js-song-card`의 좌측 패딩(번호열 공간)
- `.song-order-badge`는 절대배치 레이어라 부모 `.js-song-card`의 `border-radius`가 자식 배경을 자동으로 클리핑하지 않는다. 번호열에 배경색을 줄 때는 배지 자체의 좌측 radius도 함께 맞출 것

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
- 부모 컨테이너(`.manager-page`, `.meeting-body:not(...)`, `.container.mt-4 ...`)의 상위 오버라이드가 하위 컴포넌트 스타일을 자주 덮어쓴다. 하위 셀렉터만 수정하고 "왜 안 먹지"로 끝내지 말고, 실제로 어떤 부모 규칙이 최종 우선권을 갖는지 먼저 확인할 것
- 특히 배경색, display, padding, width 계열은 카드/버튼 자신보다 부모 레벨 규칙이 최종 결과를 바꾸는 경우가 많다. 새 스타일을 추가할 때는 부모 예외 규칙을 늘리기보다, 어느 계층이 스타일 책임을 가져야 하는지 먼저 정리할 것

## 현재 스타일 톤 점검 (2026-02-28)
- 현재 `meeting_detail`은 가독성과 상태 구분은 양호하지만, 시각 톤은 전반적으로 실무형/보수형에 가깝고 "트렌디한 UI"로 보기는 어렵다.
- 강점:
  - 상태색(배정/지원/부족) 체계가 비교적 일관되고, hover/active 피드백도 충분하다.
  - 반응형 분기와 관리자/일반인 분리가 명확해 실제 사용성은 안정적이다.
- 한계:
  - 템플릿 안 1,000줄 규모의 인라인 CSS에 색상 literal과 Bootstrap override가 섞여 있어, 시각 언어가 컴포넌트 단위로 정리돼 보이지 않는다.
  - `#e8f5e9`, `#dff3e6`, `#ffe2b3` 같은 연한 상태색이 반복되어 정보 전달은 되지만, 화면 인상이 다소 평평하고 제품 개성이 약하다.
  - `!important`, breakpoint별 예외 규칙, 개별 selector override가 많아 미세 조정이 누적될수록 디자인 일관성이 더 약해질 위험이 있다.
- UI 리프레시를 진행한다면 우선순위:
  - 색상, radius, shadow, transition을 CSS 변수 토큰으로 먼저 묶는다.
  - 카드/패널/버튼 surface 계층을 2~3단계로 단순화해 대비를 더 명확히 만든다.
  - Bootstrap 기본 버튼색 override를 늘리기보다, 이 화면 전용 컴포넌트 클래스 단위로 스타일 책임을 분리한다.
