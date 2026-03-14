# CSS Refactor Plan

이 문서는 프로젝트 전반의 CSS를 한 번에 뒤엎지 않고, **안전한 단계별 리팩터링**으로 정리하기 위한 계획 문서다.

선행 읽기:
1. `docs/ai_working_rules.md`
2. `docs/README.md`의 해당 화면 스타팅 맵
3. 화면별 전용 문서 (`docs/meeting_ui_css_map.md` 등)

## 1. 현재 상태

- 공통 UI 스타일 일부는 `templates/base.html`에 인라인으로 있다.
- 주요 화면(`home.html`, `meeting_detail.html`, `match_result.html`)은 각 템플릿 안에 큰 `<style>` 블록을 갖고 있다.
- 공용 static CSS 레이어는 거의 없었고, 화면별 CSS 중복이 누적되기 쉬운 구조였다.

## 2. 이번 세션에서 안전하게 적용한 범위

- 공용 CSS 파일 추가: `pracapp/static/pracapp/css/app.css`
- `templates/base.html`에서 공용 CSS 로드
- 전역 Bootstrap 오버라이드 대신 `app-*` 네임스페이스 공통 클래스만 추가
- 홈 화면에서만 아래 공통 클래스를 명시적으로 사용 시작
  - `app-card-surface`
  - `app-card-hover`
  - `app-section-title`
  - `app-btn-pill`
  - `app-btn-primary-strong`
  - `app-btn-secondary-soft`
  - `app-btn-accent-ghost`

원칙:
- 기존 템플릿 구조를 바꾸지 않는다.
- 이미 쓰고 있는 Bootstrap 기본 클래스의 의미를 전역적으로 재정의하지 않는다.
- 공용화는 “명시적으로 붙인 클래스만 적용” 방식으로 시작한다.

## 3. 지금 당장 하면 위험한 것

- `meeting_detail.html`, `match_result.html`의 대형 인라인 CSS를 한 번에 공용 CSS로 이동
- `.btn`, `.card`, `.container` 같은 Bootstrap 기본 셀렉터를 전역 강오버라이드
- 부모 셀렉터 의존(`.manager-page`, `.meeting-body:not(...)`)이 큰 규칙을 맥락 없이 공용화

이런 변경은 화면 간 회귀 가능성이 높아, 작은 미관 개선보다 리스크가 더 크다.

## 4. 권장 단계

### 4-1. 1단계: 공용 토큰/유틸 레이어 확장 (낮은 리스크)

- `app.css`에 색상, radius, shadow, spacing 토큰 추가
- 버튼/카드/섹션 헤더 같은 공통 유틸만 확대
- 각 화면에서 opt-in 클래스 방식으로 점진 적용

### 4-2. 2단계: 단순 화면부터 분리 (중간 리스크)

- `home.html`
- 로그인/회원가입
- 비교적 단순한 목록형 페이지

기준:
- 상태별 복잡한 색상 규칙이 적고
- 부모 오버라이드가 약한 화면부터 옮긴다.

### 4-3. 3단계: 대형 화면 토큰 치환 (중간~높은 리스크)

- `meeting_detail.html`
- `match_result.html`

기준:
- 구조를 공용화하려 하지 말고, 먼저 literal 색상/그림자/radius를 토큰으로 치환
- 레이아웃/상태/권한 분기 규칙은 페이지 전용 CSS에 남긴다.

## 5. 화면별 책임 분리 기준

- 공용 CSS로 올릴 것:
  - 버튼 surface
  - 카드 surface
  - 공통 제목 타이포
  - 색상/그림자/radius 토큰

- 화면에 남길 것:
  - 보드/grid 구조
  - 상태별 특수 색 규칙
  - 권한/모드 분기 셀렉터
  - 드래그/토글/절대배치 인터랙션과 결합된 스타일

## 6. 검증 원칙

- 공용 CSS를 건드렸으면 최소 `./.venv/bin/python manage.py check`
- 스타일이 여러 화면에 닿는 변경이면 해당 화면을 최소 2곳 이상 수동 스모크 확인
- 공용 규칙을 추가할 때는 “어느 화면이 이 클래스를 실제로 쓰는지”를 먼저 파악하고 적용

## 7. 다음 우선순위

1. `home.html`에서 아직 남아 있는 공통 카드/텍스트 톤을 `app.css`로 더 분리
2. `templates/base.html`의 navbar/auth 버튼 스타일도 `app.css`로 이동
3. 로그인/회원가입 화면을 `app-*` 공통 클래스 기반으로 맞춤
4. 그 다음 `meeting_detail`은 토큰 치환부터 시작하고, 구조 공용화는 뒤로 미룸
