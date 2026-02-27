# 데모 피드백 수용 기록 (2026-02-25)

> 상태: 과거 수용 기록(히스토리). 현재 단일 기준 문서는 `docs/demo_page_plan.md`.
> 주의: 이 문서는 2026-02-25 시점의 판단 기록이며, 현재 시나리오 A/B/C 재구성과 완전히 일치하지 않을 수 있다.

작성일: 2026-02-25  
목적: 데모 기능 관련 리뷰 피드백 4건에 대한 **판단 근거 + 실제 수용 조치 + 후속 주의사항**을 기록하여, 이후 작업하는 AI/개발자가 맥락 없이도 동일 판단을 재현할 수 있게 한다.

관련 문서:
- `docs/demo_page_plan.md`
- `docs/meeting_handover.md`

관련 코드:
- `templates/base.html`
- `pracapp/static/pracapp/js/tutorial_demo.js`
- `pracapp/views/demo_views.py`
- `pracapp/views/matching_views.py`
- `pracapp/management/commands/cleanup_demo_data.py`
- `pracapp/middleware.py`

---

## 1) tutorial_demo.js의 body attribute 체크

### 피드백
- `tutorial_demo.js` L2의 아래 조건이 참이 아니면 투어가 조용히 비활성화된다.
- `if (!document.body || document.body.dataset.isDemoMode !== '1') return;`
- 따라서 `base.html`에 `data-is-demo-mode="1"`이 실제로 들어가는지 확인 필요.

### 검토 결과
- **수용(확인 완료, 코드 수정 불필요)**
- 현재 `templates/base.html`의 `<body>`에 다음 속성이 이미 존재:
  - `data-is-demo-mode="{% if is_demo %}1{% else %}0{% endif %}"`
- 또한 투어 include 자체도 `{% if is_demo %}` 조건으로만 로드됨.

### 근거 코드
- `templates/base.html`
- `pracapp/templates/pracapp/demo/demo_tour_overlay.html`
- `pracapp/static/pracapp/js/tutorial_demo.js`

### 결론
- 현재 구현은 의도와 일치한다.
- 이 피드백은 버그 제보라기보다 "조용한 실패(silent fail) 구조"에 대한 확인 요청이며, 현재는 정상 구성 상태다.

---

## 2) 당시 예약 진행 시나리오의 booking_completed_keys 키 이름 일치 여부

### 피드백
- `demo_views.py`에서 `saved_params['booking_completed_keys']`로 저장하는데,
- 다른 쪽에서 `booking_saved_completed_keys`를 기대하면 불일치 가능성이 있음.

### 검토 결과
- **부분 수용(네이밍 혼동 리스크는 타당), 동작상 불일치는 없음**
- 저장 키명은 `booking_completed_keys`가 맞고,
- `matching_views.py`에서는 해당 저장 키를 읽어온 뒤,
- 템플릿 전달용 컨텍스트 변수명을 `booking_saved_completed_keys`로 사용하고 있음.

### 실제 데이터 흐름
1. 저장
- `pracapp/views/demo_views.py`
- `saved_params['booking_completed_keys'] = completed_keys`
- `MeetingWorkDraft.match_params`에 저장

2. 복원
- `pracapp/views/matching_views.py`
- `saved_keys = user_work_draft.match_params.get('booking_completed_keys') or []`
- `booking_saved_completed_keys` 변수로 재가공

3. 프론트 전달
- `pracapp/views/matching_views.py`
- context: `booking_saved_completed_keys_json`
- `pracapp/templates/pracapp/match_result.html`에서 복원 처리

### 결론
- 런타임 키 미스매치는 없다.
- 다만 "저장 키명"과 "컨텍스트 변수명"이 달라서 문서/대화에서 오해가 발생하기 쉬우므로,
- 핸드오버 문서에 둘의 역할을 분리 표기하도록 권장.

---

## 3) cleanup_demo_data edge case (Meeting 없는 Band 누수)

### 피드백
- 기존 쿼리:
  - `Band.objects.filter(name__startswith='[데모DB] 락스타즈-').filter(meetings__created_at__lt=cutoff)`
- 이 경우 `meetings`가 아예 없는 Band는 조회되지 않아 누수 가능.

### 검토 결과
- **수용(실제 결함으로 판단) + 코드 수정 완료**
- 데모 생성 중 예외가 나서 band만 생성된 경우, 기존 쿼리로는 정리 대상에서 빠질 수 있었다.

### 적용한 수정
- 파일: `pracapp/management/commands/cleanup_demo_data.py`
- 변경 사항:
  - `from django.db.models import Q` 추가
  - 밴드 조회 조건을 다음으로 확장:
    - `Q(meetings__created_at__lt=cutoff) | Q(meetings__isnull=True)`

### 수정 후 의미
- 오래된 미팅이 있는 데모 밴드도 삭제
- 미팅이 하나도 없는(부분 생성 실패) 데모 밴드도 삭제

### 잔여 주의사항
- 데모 식별이 밴드명 prefix 기반(`'[데모DB] 락스타즈-'`)이므로,
- 운영 중 네이밍 정책이 바뀌면 커맨드 조건도 같이 갱신해야 한다.

---

## 4) 데모 정리 미들웨어의 DB 쿼리 비용

### 피드백
- 데모 모드 요청에서 `/session/<uuid>/`, `/song/<uuid>/` 경로 판별 시 DB `exists()`가 수행된다.
- 요청량 증가 시 비용 고려 필요.

### 검토 결과
- **수용(관측 포인트로 채택), 즉시 수정은 보류**
- 현재 구조상 쿼리가 발생하는 것은 사실이나,
- 적용 범위가 `demo_mode` 세션 사용자로 제한되고,
- 대부분 경로는 문자열 체크에서 종료되므로 현 트래픽에서 즉시 병목으로 보긴 어려움.

### 현재 동작
- 파일: `pracapp/middleware.py`
- `_is_demo_scope_request()`에서
  - `/demo/` 또는 demo_meeting_id/demo_band_id 포함 경로는 문자열로 빠르게 처리
  - `/session/<uuid>/`, `/song/<uuid>/`는 해당 ID의 meeting 연관성을 DB에서 `exists()` 검증

### 유지 결정 이유
- 데모 데이터 즉시 정리라는 안전성 목표가 우선
- 권한/스코프 오판으로 실제 데이터 접근 허용되는 리스크를 피하기 위해 보수적으로 검증

### 향후 최적화 옵션 (필요 시)
1. 데모 시작 시 `demo_song_ids`, `demo_session_ids`를 세션 캐시로 저장 후 집합 조회로 1차 판별
2. 미들웨어에서 경로 prefix별 단축 분기 강화
3. 쿼리 빈도 측정용 로그/메트릭 추가 후 임계치 기반 개선

---

## 최종 수용 요약

1. body attribute 이슈: **정상 구성 확인(수정 없음)**
2. booking 키 네이밍: **동작상 정상, 문서 혼동 리스크만 관리**
3. cleanup edge case: **실제 결함으로 수용, 코드 수정 완료**
4. 미들웨어 쿼리 비용: **관찰 항목으로 수용, 현시점 유지**

---

## 다른 AI를 위한 작업 규칙

1. `booking_completed_keys`는 **저장 키명**이다. 임의로 바꾸지 말 것.
2. `booking_saved_completed_keys_*`는 **뷰/템플릿 전달 변수명**이다.
3. 데모 정리 커맨드 수정 시, "미팅 없는 데모 밴드" 삭제 조건을 유지할 것. 미팅이 없는 데모 밴드는 생성 도중 실패한 고아 데이터이므로 정리 대상에서 제외하지 말 것.
4. `tutorial_demo.js` 초기 return 조건은 의도된 가드다. 제거하지 말 것.
5. 미들웨어 최적화 전에는 반드시 데모 스코프 이탈 시 즉시 삭제 동작 회귀 테스트를 같이 수행할 것.
