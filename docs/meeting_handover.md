# Meeting Handover

## 목적
- 매칭/조율/예약/최종확정 플로우의 최신 동작을 다음 작업자가 바로 이어받을 수 있게, "현재 기준 단일 진실원" 규칙과 최근 버그 수정 내역을 기록한다.

## 현재 핵심 프로세스
1. `schedule_match_settings`에서 매칭 조건 선택
2. `schedule_match_run`에서 자동 매칭 + 주차별 실패 카드 생성
3. `match_result`에서 수동 조율(드래그)
4. 필요 시 `임시 저장`/`공유`
5. 예약 단계(`schedule_final?mode=booking`)에서 예약 확정 처리
6. 최종 확정 후 `schedule_final` 읽기 중심 모드

## 최근 핵심 수정(중요)
- 예약 보드 합주실 불가능 타일 처리 분리
  - 타 미팅 유래 불가능 슬롯과 사용자 수동 불가능 슬롯을 분리 렌더링
  - 수동 블록 페인터(드래그 추가/삭제)는 manual 슬롯에만 작동
  - 타 미팅 슬롯 위로 수동 생성/삭제가 침범하지 않도록 차단
- 예약 완료 카드 편집 잠금
  - `booking-completed` 카드는 드래그 이동/길이 조절/합주실 변경 모두 차단
- 예약 진입 경고 강화
  - 미배치 카드(`failed-week-card`)가 남아 있으면 예약 진입 전 `경고!!` 모달 표시
- 최종 페이지 강제 오탐 차단
  - 최종 읽기 화면에서는 강제 배지 재계산을 비활성화하고 서버 `is_forced`만 반영
  - 최종 관련 페이지 플로팅 팝오버에서도 강제 패턴(중복/불가능/공간부족 강조) 비활성화
- 더미 데이터 이름 정책 반영
  - 사용자 제공 이름 풀(80명) 문서화: `docs/dummy_name_pool.md`
  - `create_dummy.py`에서 `test1~test60` 이름을 지정된 60명으로 적용하도록 변경
- 매칭 실패 집계 기준 통일
  - 주차별 실패 카드/전체 실패 목록/상단 성공 수치가 같은 기준으로 동작하도록 정리
  - 실패 계산은 `result['failed']`가 아니라 "배정 대상 전체 곡 + 주차별 부족 슬롯" 기준
- 매칭 설정 표시 불일치 보정
  - 현재 화면의 매칭 설정 패널은 렌더에 사용된 파라미터를 우선 표시
  - 파라미터 우선순위: URL > 개인 WorkDraft(match_params) > 세션 저장 설정
- 공간 부족 사유 표시 정책 변경
  - 같은 미팅 내 보드 점유 사유(`사용 중`)는 숨김
  - 외부 미팅 때문에 막힌 경우만 `[미팅 이름] - 곡명` 형태로 노출
  - 합주실 수동 블록(`예약 불가`)은 유지
  - 외부 미팅 사유 텍스트는 합주 계열과 동일 주황색 규칙 적용
- 호버 계층 조정
  - 내 곡 호버 카드가 요일 강조 오버레이보다 위에 오도록 z-index 보정
- 매칭 설정 UI 정리
  - 실험성 분할배치 옵션 제거(파라미터/세션/UI 모두 삭제)
  - 사전 확인 모달에 "이번 매칭 사용 합주실(선호도 순)" 노출

## 단일 진실원(SSOT) 원칙
- 실패 관련 모든 지표는 `weeks[].failed_items`(현재 보드 상태)를 기준으로 계산/표시한다.
- 동일 지표를 서버 초기값과 프론트 재계산 값으로 이중 관리하지 않는다.
- 사유 표시는 "외부 요인"과 "현재 보드 상태"를 명확히 분리한다.
  - 외부 요인: RoomBlock(다른 미팅/수동 블록)
  - 현재 보드 요인: 같은 화면의 배치 타일

## 운영 메모
- 검증 기본: `./.venv/bin/python manage.py check`
- 이번 실행에서 `./.venv/bin/python manage.py test` 결과는 `NO TESTS RAN` (테스트 발견 0개)
- 운영 지침: 앱 전체 테스트(`manage.py test`)를 루틴으로 매번 실행하지 말고, 기능 단위 검증 + 스모크 + `manage.py check` 중심으로 진행한다.

## 주요 수정 파일(최근)
- `pracapp/views/matching_views.py`
- `pracapp/templates/pracapp/match_result.html`
- `pracapp/templates/pracapp/match_settings.html`
- `pracapp/forms.py`
- `create_dummy.py`
- `docs/dummy_name_pool.md`

## 인수인계 체크리스트
1. 문서 확인
   - `docs/meeting_handover.md`
   - `docs/meeting_process_state_machine.md`
   - `docs/meeting_integrity_rules.md`
   - `docs/meeting_regression_checklist.md`
2. 로컬 검증
   - `./.venv/bin/python manage.py check`
3. 화면 일치성 점검
   - 주차별 실패 카드 수 vs 전체 실패 목록 vs 상단 성공 수치가 동일하게 변하는지
   - 매칭 설정 패널이 현재 보드 파라미터와 일치하는지
4. 공간 부족 사유 점검
   - 같은 미팅 점유 사유 미노출
   - 외부 미팅 사유만 `[미팅 이름] - 곡명`으로 노출
   - 수동 블록은 `예약 불가` 유지
