'use strict';

/**
 * @file UI 배선 모듈 — 상단 버튼(세션·닫기·가시성·투명도·화면인식) + 투명도 팝업.
 */
window.Jarvis = window.Jarvis || {};

Jarvis.ui = (() => {
  const SEL_SESSIONS = '.char-btn--sessions';
  const SEL_CLOSE = '.char-btn--close';
  const ID_VISIBILITY = 'btn-visibility';
  const ID_OPACITY = 'btn-char-opacity';
  const ID_POPUP = 'char-opacity-popup';
  const ID_SLIDER = 'char-opacity-slider';
  const CLASS_ACTIVE = 'char-btn--active';
  const CLASS_POPUP_OPEN = 'opacity-popup--open';
  const SLIDER_MAX = 100;   // 슬라이더 값 → 0~1 투명도 변환

  const scope = Jarvis.dom.createScope();

  /**
   * 상단 버튼과 투명도 팝업 이벤트를 배선한다. app.js가 1회 호출.
   * 
   * @returns {void}
   */
  function init() {
    const btnSessions = Jarvis.dom.$(SEL_SESSIONS);
    const btnClose = Jarvis.dom.$(SEL_CLOSE);
    const btnVisible = Jarvis.dom.$id(ID_VISIBILITY);
    const btnOpacity = Jarvis.dom.$id(ID_OPACITY);
    const popup = Jarvis.dom.$id(ID_POPUP);
    const slider = Jarvis.dom.$id(ID_SLIDER);

    // 세션창 토글 / 앱 종료
    scope.on(btnSessions, 'click', () => window.electronAPI?.toggleSessionWin());
    scope.on(btnClose, 'click', () => window.electronAPI?.closeWindow());

    // 캐릭터 표시/숨김
    scope.on(btnVisible, 'click', () => {
      const isVisible = Jarvis.avatar.toggleVisibility();
      btnVisible.classList.toggle(CLASS_ACTIVE, !isVisible);
    });

    // 투명도 팝업
    scope.on(btnOpacity, 'click', () => {
      const willOpen = !popup.classList.contains(CLASS_POPUP_OPEN);
      popup.classList.toggle(CLASS_POPUP_OPEN, willOpen);
      btnOpacity.classList.toggle(CLASS_ACTIVE, willOpen);
    });
    scope.on(slider, 'input', (e) => Jarvis.avatar.setOpacity(e.target.value / SLIDER_MAX));
  }

  Jarvis.bus.on(Jarvis.EVENTS.TEARDOWN, () => scope.dispose());

  return { init };
})();