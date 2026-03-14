(function () {
  if (!document.body || document.body.dataset.isDemoMode !== '1') return;

  const DEMO_PAGE_NAME = String(document.body.dataset.demoPageName || '').trim();
  const DEMO_TUTORIAL_MODE = document.body.dataset.demoTutorialMode === '1';
  const DEMO_MEETING_DETAIL_URL = String(document.body.dataset.demoMeetingDetailUrl || '').trim();
  const DEMO_TUTORIAL_URL = String(document.body.dataset.demoTutorialUrl || '').trim();
  const TUTORIAL_CHOICE_MODAL_ENABLED = false;
  if (DEMO_PAGE_NAME === 'demo_feature_tutorial') return;
  const OVERLAY = document.getElementById('tutorial-overlay');
  const TOOLTIP = document.getElementById('tutorial-tooltip');
  const CHOICE_MODAL = document.getElementById('tutorial-choice-modal');
  const CHOICE_FREE_BTN = document.getElementById('tutorialChoiceFreeBtn');
  const CHOICE_START_BTN = document.getElementById('tutorialChoiceStartBtn');
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
  let choicePromptOpened = false;
  let bottomPromptBound = false;
  let tutorialModeAutoStarted = false;

  function syncScrollLock() {
    const choiceOpen = !!CHOICE_MODAL && CHOICE_MODAL.classList.contains('is-open');
    const tourOpen = TOOLTIP.style.display === 'block' || OVERLAY.style.display === 'block';
    document.body.classList.toggle('tutorial-scroll-locked', choiceOpen || tourOpen);
  }

  function getSteps() {
    const inMatch = !!document.querySelector('#matchResultRoot, .match-result-wrap');
    const inMeeting = !!document.querySelector('#liveMeetingRow, .meeting-body');
    const items = [];
    if (inMatch) {
      items.push(
        { target: '.week-board', title: '합주 보드', desc: '주차별 배치 카드와 시간축, 합주실 배치를 한 번에 확인하는 핵심 화면입니다.' },
        { target: '.board-event', title: '합주 카드', desc: '곡 카드를 드래그하거나 길이를 조절해 실제 시간표를 빠르게 조율합니다.' },
        { target: '#quickForcedOnlyBtn', title: '강제 배치만', desc: '충돌 때문에 강제로 들어간 카드만 모아서 위험 구간을 먼저 점검할 수 있습니다.' },
        { target: '#quickTempRoomOnlyBtn', title: '임시합주실만', desc: '실제 합주실이 아닌 임시합주실 카드만 따로 모아 후속 정리가 필요한 영역을 확인합니다.' },
        { target: '#shareCurrentScheduleBtnInline', title: '저장 후 공유', desc: '현재 보드를 공용 기준안으로 올립니다. 이후 예약 단계도 이 공유본 기준으로 이어집니다.' },
        { target: '#goBookingConfirmBtn, #goBookingConfirmFromMatchBtn', title: '예약 단계 진입', desc: '공유가 끝나면 예약 확정 단계로 넘어가 합주실 예약 여부를 체크하고 마무리할 수 있습니다.' }
      );
    } else if (inMeeting) {
      items.push(
        { target: '#matchActionPanel, #openMatchFromDetailBtn', title: '주요 진입 버튼', desc: '자동 매칭 실행과 결과 확인 같은 핵심 동선이 이 영역에 모여 있습니다.' },
        { target: '.js-song-card', title: '곡 카드', desc: '곡별 세션 구성과 현재 지원/배정 상태를 이 카드 단위로 확인합니다.' },
        { target: '.demo-role-banner', title: '체험 배너', desc: '가이드를 다시 열거나 체험을 종료할 수 있습니다. 현재 체험은 매니저 관점 핵심 흐름 기준입니다.' }
      );
    } else {
      items.push({ target: '.container', title: '체험 화면', desc: '현재 화면을 자유롭게 탐색해보세요.' });
    }
    return items;
  }

  function setVisible(show) {
    OVERLAY.style.display = show ? 'block' : 'none';
    TOOLTIP.style.display = show ? 'block' : 'none';
    syncScrollLock();
  }

  function hideTour() {
    setVisible(false);
    idx = 0;
  }

  function resetTutorialState() {
    steps = [];
    idx = 0;
    setChoiceModalVisible(false);
    setVisible(false);
  }

  function setChoiceModalVisible(show) {
    if (!CHOICE_MODAL) return;
    CHOICE_MODAL.classList.toggle('is-open', !!show);
    CHOICE_MODAL.setAttribute('aria-hidden', show ? 'false' : 'true');
    syncScrollLock();
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

  function ensureTargetInView(target) {
    if (!target || typeof target.getBoundingClientRect !== 'function') return;
    const rect = target.getBoundingClientRect();
    const margin = 28;
    const needsScrollUp = rect.top < margin;
    const needsScrollDown = rect.bottom > (window.innerHeight - margin);
    if (!needsScrollUp && !needsScrollDown) return;

    const targetCenter = window.scrollY + rect.top + (rect.height / 2);
    const desiredTop = Math.max(0, targetCenter - (window.innerHeight / 2));

    document.body.classList.remove('tutorial-scroll-locked');
    window.scrollTo({ top: desiredTop, behavior: 'smooth' });
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

    ensureTargetInView(target);

    window.setTimeout(function () {
      const refreshedTarget = document.querySelector(step.target);
      if (!refreshedTarget) {
        hideTour();
        return;
      }
      const rect = safeRect(refreshedTarget);
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
    }, 220);
  }

  function startTour(force) {
    const skipped = localStorage.getItem(STORAGE_KEY) === '1';
    if (!force && skipped) return;
    if (!force && TOOLTIP.style.display === 'block') return;
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
      if (DEMO_TUTORIAL_URL) {
        window.location.href = DEMO_TUTORIAL_URL;
        return;
      }
      localStorage.removeItem(STORAGE_KEY);
      setChoiceModalVisible(false);
      startTour(true);
    });
  }

  if (CHOICE_FREE_BTN) {
    CHOICE_FREE_BTN.addEventListener('click', function () {
      setChoiceModalVisible(false);
    });
  }

  if (CHOICE_START_BTN) {
    CHOICE_START_BTN.addEventListener('click', function () {
      setChoiceModalVisible(false);
      if (!DEMO_TUTORIAL_MODE && DEMO_TUTORIAL_URL) {
        window.location.href = DEMO_TUTORIAL_URL;
        return;
      }
      if (!DEMO_TUTORIAL_MODE && DEMO_MEETING_DETAIL_URL) {
        const legacyUrl = DEMO_MEETING_DETAIL_URL.includes('?')
          ? `${DEMO_MEETING_DETAIL_URL}&tutorial=1`
          : `${DEMO_MEETING_DETAIL_URL}?tutorial=1`;
        window.location.href = legacyUrl;
        return;
      }
      localStorage.removeItem(STORAGE_KEY);
      startTour(true);
    });
  }

  window.addEventListener('resize', function () {
    if (TOOLTIP.style.display !== 'block') return;
    showStep(idx);
  });

  function maybeOpenChoiceModal() {
    if (!TUTORIAL_CHOICE_MODAL_ENABLED) return;
    if (!CHOICE_MODAL) return;
    if (choicePromptOpened) return;
    const nextSteps = getSteps();
    if (!nextSteps.length) return;
    choicePromptOpened = true;
    setChoiceModalVisible(true);
  }

  function maybeOpenChoiceModalOnScrollEnd() {
    if (choicePromptOpened) return;
    const scrollBottom = window.scrollY + window.innerHeight;
    const docHeight = Math.max(
      document.body.scrollHeight,
      document.documentElement.scrollHeight,
      document.body.offsetHeight,
      document.documentElement.offsetHeight
    );
    if (docHeight <= window.innerHeight + 8) return;
    if (scrollBottom < docHeight - 24) return;
    maybeOpenChoiceModal();
  }

  function bindBottomPrompt() {
    if (!TUTORIAL_CHOICE_MODAL_ENABLED) return;
    if (bottomPromptBound) return;
    if (DEMO_PAGE_NAME === 'demo_home') return;
    bottomPromptBound = true;
    window.addEventListener('scroll', maybeOpenChoiceModalOnScrollEnd, { passive: true });
  }

  function maybeAutoStartTutorialMode() {
    if (!DEMO_TUTORIAL_MODE || tutorialModeAutoStarted) return;
    tutorialModeAutoStarted = true;
    localStorage.removeItem(STORAGE_KEY);
    startTour(true);
  }

  window.addEventListener('pageshow', function () {
    if (DEMO_TUTORIAL_MODE) {
      resetTutorialState();
      window.setTimeout(maybeAutoStartTutorialMode, 180);
      return;
    }
    if (TOOLTIP.style.display === 'block') {
      showStep(idx);
      return;
    }
    bindBottomPrompt();
  });
  if (DEMO_TUTORIAL_MODE) {
    resetTutorialState();
    window.setTimeout(maybeAutoStartTutorialMode, 220);
  } else {
    bindBottomPrompt();
  }

})();
