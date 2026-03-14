# demo_feature_tutorial 초기 장식형 CSS 보관

2026-02-28 기준 첫 구현에서 `pracapp/templates/pracapp/demo/demo_feature_tutorial.html`은
실제 서비스 화면과 거리감이 큰 전용 랜딩형 스타일을 사용했다.

배포 전 UX 정리 기준으로, 런타임 템플릿에서는 해당 장식형 레이아웃을 제거하고
`meeting_detail`에 가까운 담백한 카드/컨테이너 구조로 낮췄다.

아래 키워드는 당시 제거한 스타일 축을 추적하기 위한 보관 메모다.

- `.demo-tutorial-shell`: 그라데이션 배경 + 둥근 대형 패널
- `.demo-tutorial-kicker`: 별도 배지형 상단 라벨
- `.demo-shot`: 강조형 목업 카드
- `.demo-modal-mock`: 연출용 보라색 모달 카드
- `.demo-utility-card`: 장식형 유틸 카드

재사용이 필요하면 git history 기준으로 복원하고, 그대로 재도입하지 말고
실제 페이지 톤과 맞는 수준으로만 부분 차용한다.
