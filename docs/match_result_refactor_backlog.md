# match_result 리팩토링 백로그 (프로토타입 배포 후)

## 원칙
- 배포 전: 안정성 패치만 수행 (회귀 위험 최소화)
- 배포 후: 죽은 코드 제거 -> 기능 모듈 분리 순서로 진행

## 배포 전 이미 반영된 안정성 패치
- 로컬 날짜 기준 `is-today` 계산으로 UTC 오프셋 오작동 방지
- 예약 패널 `localStorage` 접근 예외 처리 (`getItem`/`setItem`)

## 1차 정리 대상 (Dead Path 제거)

### DOM 없음인데 참조 중인 ID
- `bookingBlockDate`
- `bookingBlockRoom`
- `bookingBlockStart`
- `bookingBlockEnd`
- `bookingBlockAddBtn`
- `bookingBlockList`
- `bookingRoomSummary`
- `resultTotalCount`
- `resultSuccessCount`
- `shareCurrentScheduleBtn` (inline 버튼 fallback이 있어 기능은 동작)

### 호출 없는 함수 (정적 기준)
- `renderBookingBlockRoomOptions`
- `mergeBlockedSegments`
- `getBookingConflictSummary`
- `renderBookingRoomSummary`
- `getOrCreateCoordinationTempRoomChoice`
- `getUnplacedFailedCardCount`
- `openSongConflict`
- `renderMissingPeopleHtml`
- `getContiguousSameSongRoomId`
- `isRoomShortageAtSlot`

## 2차 정리 대상 (모듈 분리)
- `booking` 영역: 예약 선택/확정/블록 페인터
- `drag_resize` 영역: 드래그/리사이즈/강제 확인 모달
- `hover_overlay` 영역: 충돌 오버레이/핀/팝오버
- `draft_guard` 영역: 임시저장/이탈 가드/재진입

## 검증 체크리스트
- 비최종 화면: 드래그/분할/리셋/공유/예약 진입
- 예약 확정 화면(관리자): 선택/해제/일괄 선택/완료 판정/확정
- 최종 읽기 화면(멤버): 오버레이/내 합주 필터/확인 제출
- 임시합주실: 생성/이름확정/저장 후 재진입
- 강제 배치: 인원중복/불가능시간/정원초과/룸중복

## 작업 순서 제안
1. Dead Path 제거 PR (동작 변경 없음 목표)
2. booking + draft_guard 분리 PR
3. drag_resize + hover_overlay 분리 PR
4. 통합 회귀 점검 후 문서 갱신
