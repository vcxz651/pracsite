(function () {
  if (!document.body || document.body.dataset.isDemoMode !== '1') return;

  const OVERLAY = document.getElementById('tutorial-overlay');
  const TOOLTIP = document.getElementById('tutorial-tooltip');
  const TITLE = document.getElementById('tourTitle');
  const DESC = document.getElementById('tourDesc');
  const PROGRESS = document.getElementById('tourProgress');
  const NEXT_BTN = document.getElementById('tourNextBtn');
  const SKIP_BTN = document.getElementById('tourSkipBtn');
  const REPLAY_BTN = document.getElementById('demoTourReplayBtn');

  if (!OVERLAY || !TOOLTIP || !TITLE || !DESC || !PROGRESS || !NEXT_BTN || !SKIP_BTN) return;

  const STORAGE_KEY = 'demo_tour_skipped';
  let steps = [];
  let idx = 0;

  function getSteps() {
    const inMatch = !!document.querySelector('.match-result-wrap');
    const inMeeting = !!document.querySelector('.meeting-body');
    const items = [];
    if (inMatch) {
      items.push(
        { target: '.week-board', title: '합주 보드', desc: '주차별 배치 카드를 한눈에 확인할 수 있습니다.' },
        { target: '.board-event', title: '합주 카드', desc: '카드 이동/리사이즈로 일정을 조율합니다.' },
        { target: '#quickForcedOnlyBtn', title: '강제 배치 필터', desc: '강제 배치된 카드만 빠르게 모아볼 수 있습니다.' },
        { target: '#quickTempRoomOnlyBtn', title: '임시합주실 필터', desc: '임시합주실 카드만 분리해서 확인합니다.' },
        { target: '#quickLayoutToggleBtn', title: '일반/룸 보기', desc: '보드 표현 방식을 즉시 전환할 수 있습니다.' }
      );
    } else if (inMeeting) {
      items.push(
        { target: '.meeting-main-actions, .meeting-action-group, .btn-meeting-main', title: '주요 진입 버튼', desc: '매칭 실행/최종 일정 진입 등 핵심 동선입니다.' },
        { target: '.song-list-shell, .song-list, .meeting-song-list', title: '곡 목록', desc: '곡, 세션, 지원/배정 상태를 이 영역에서 확인합니다.' },
        { target: '.demo-role-banner', title: '역할 전환', desc: '멤버/매니저 뷰를 즉시 바꿔 UI 차이를 볼 수 있습니다.' }
      );
    } else {
      items.push({ target: '.container', title: '데모 화면', desc: '현재 화면을 자유롭게 탐색해보세요.' });
    }
    return items;
  }

  function setVisible(show) {
    OVERLAY.style.display = show ? 'block' : 'none';
    TOOLTIP.style.display = show ? 'block' : 'none';
  }

  function hideTour() {
    setVisible(false);
    idx = 0;
  }

  function safeRect(el) {
    const r = el.getBoundingClientRect();
    return {
      top: Math.max(8, r.top - 6),
      left: Math.max(8, r.left - 6),
      width: Math.max(24, r.width + 12),
      height: Math.max(24, r.height + 12),
    };
  }

  function positionTooltip(rect) {
    const ww = window.innerWidth;
    const wh = window.innerHeight;
    TOOLTIP.style.left = `${Math.min(ww - 340, rect.left)}px`;
    let top = rect.top + rect.height + 10;
    if (top + 180 > wh) {
      top = Math.max(10, rect.top - 170);
    }
    TOOLTIP.style.top = `${top}px`;
  }

  function showStep(nextIdx) {
    if (!steps.length) return hideTour();
    idx = nextIdx;
    if (idx >= steps.length) return hideTour();
    const step = steps[idx];
    const target = document.querySelector(step.target);
    if (!target) return showStep(idx + 1);

    const rect = safeRect(target);
    OVERLAY.style.top = `${rect.top}px`;
    OVERLAY.style.left = `${rect.left}px`;
    OVERLAY.style.width = `${rect.width}px`;
    OVERLAY.style.height = `${rect.height}px`;
    TITLE.textContent = step.title;
    DESC.textContent = step.desc;
    PROGRESS.textContent = `${idx + 1} / ${steps.length}`;
    NEXT_BTN.textContent = idx + 1 >= steps.length ? '완료' : '다음';
    positionTooltip(rect);
    setVisible(true);
  }

  function startTour(force) {
    const skipped = localStorage.getItem(STORAGE_KEY) === '1';
    if (!force && skipped) return;
    steps = getSteps();
    idx = 0;
    showStep(0);
  }

  NEXT_BTN.addEventListener('click', function () {
    showStep(idx + 1);
  });

  SKIP_BTN.addEventListener('click', function () {
    localStorage.setItem(STORAGE_KEY, '1');
    hideTour();
  });

  if (REPLAY_BTN) {
    REPLAY_BTN.addEventListener('click', function () {
      localStorage.removeItem(STORAGE_KEY);
      startTour(true);
    });
  }

  window.addEventListener('resize', function () {
    if (TOOLTIP.style.display !== 'block') return;
    showStep(idx);
  });

  window.setTimeout(function () {
    startTour(false);
  }, 220);
})();
