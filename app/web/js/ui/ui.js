'use strict';

/**
 * @file UI 모듈 — DOM 참조·말풍선·배지·게이트·confirm·세션 드로어.
 */
window.JarvisWeb = window.JarvisWeb || {};

JarvisWeb.ui = (() => {
  /** @constant {Readonly<Object>} 표시 제어 클래스 */
  const CLASS = Object.freeze({
    hidden       : 'hidden',
    drawerOpen   : 'drawer--open',
    backdropShow : 'drawer-backdrop--show',
    micRecording : 'inputbar__mic--recording',
    msg          : 'msg',
    msgBubble    : 'msg__bubble',
    msgLink      : 'msg__link',
  });

  /** @constant {Readonly<Object>} 말풍선 역할 (msg--{role} 모디파이어) */
  const ROLE = Object.freeze({
    USER  : 'user',
    BOT   : 'assistant',
    STATUS: 'status',
  });

  /** @constant {Readonly<Object>} agent_type → 배지 라벨 */
  const AGENT_LABELS = Object.freeze({
    search : '🔍 검색',
    memo   : '📝 메모',
    file   : '📁 파일',
    system : '⚙ 시스템',
    nav    : '🗺 경로',
    screen : '👁 화면분석',
    general: '🤖 JARVIS',
  });

  const AGENT_DEFAULT = 'general';
  const LINK_LABEL = '🔗 링크 열기';

  const { $id } = JarvisWeb.dom;

  /** DOM 참조 (scripts는 body 하단 → 파싱 완료) */
  const el = {
    gate          : $id('gate'),
    gateToken     : $id('gate-token'),
    gateSubmit    : $id('gate-submit'),
    gateError     : $id('gate-error'),
    app           : $id('app'),
    badge         : $id('agent-badge'),
    btnDrawer     : $id('btn-drawer'),
    btnDrawerClose: $id('btn-drawer-close'),
    btnNew        : $id('btn-new'),
    drawer        : $id('drawer'),
    drawerBackdrop: $id('drawer-backdrop'),
    sessionList   : $id('session-list'),
    chat          : $id('chat-list'),
    confirmPanel  : $id('confirm-panel'),
    confirmPreview: $id('confirm-preview'),
    btnApprove    : $id('btn-approve'),
    btnReject     : $id('btn-reject'),
    input         : $id('chat-input'),
    btnSend       : $id('btn-send'),
    btnMic        : $id('btn-mic'),
    btnAttach     : $id('btn-attach'),
    attachInput   : $id('attach-input'),
    attachPreview : $id('attach-preview'),
    viewer        : $id('viewer'),
    viewerImg     : $id('viewer-img'),
  };

  /**
   * 채팅 목록에 말풍선을 추가하고 스크롤한다.
   * 
   * @param {string} role - ROLE.USER | ROLE.BOT | ROLE.STATUS
   * @param {string} text - 내용
   * @returns {HTMLElement} 버블 요소 (스트리밍 갱신용)
   */
  function addMsg(role, text) {
    const wrap = document.createElement('div');
    wrap.className = `${CLASS.msg} ${CLASS.msg}--${role}`;
    const bubble = document.createElement('div');
    bubble.className = CLASS.msgBubble;
    bubble.textContent = text;
    wrap.appendChild(bubble);
    el.chat.appendChild(wrap);
    scrollBottom();
    return bubble;
  }

  /**
   * open_url을 탭 가능한 링크 버튼으로 표시한다.
   * 
   * @param {string} url - http/https URL
   * @returns {void}
   */
  function addLink(url) {
    let parsed;
    try { parsed = new URL(url); } catch { return; }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return;

    const bubble = addMsg(ROLE.BOT, '');
    const a = document.createElement('a');
    a.className = CLASS.msgLink;
    a.href = parsed.href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.textContent = LINK_LABEL;
    bubble.appendChild(a);
  }

  /**
   * 채팅 목록을 최하단으로 스크롤한다.
   * 
   * @returns {void}
   */
  function scrollBottom() {
    el.chat.scrollTop = el.chat.scrollHeight;
  }

  /**
   * 채팅 목록을 비운다.
   * 
   * @returns {void}
   */
  function clearChat() {
    el.chat.replaceChildren();
  }

  /**
   * Agent 배지를 갱신한다 (알 수 없는 타입은 general 라벨).
   * 
   * @param {string} agentType - done 이벤트의 agent_type
   * @returns {void}
   */
  function setBadge(agentType) {
    el.badge.textContent = AGENT_LABELS[agentType] || AGENT_LABELS[AGENT_DEFAULT];
  }

  const MSG_GATE_TOKEN = '토큰이 올바르지 않습니다.';

  /**
   * 토큰 게이트를 표시한다.
   * 
   * @param {boolean} isError - 오류 문구 표시 여부
   * @param {string} [msg] - 표시할 오류 문구 (기본: 토큰 오류)
   * @returns {void}
   */
  function showGate(isError, msg = MSG_GATE_TOKEN) {
    el.gate.classList.remove(CLASS.hidden);
    el.app.classList.add(CLASS.hidden);
    el.gateError.textContent = msg;
    el.gateError.classList.toggle(CLASS.hidden, !isError);
  }

  /**
   * 앱 본체를 표시한다.
   * 
   * @returns {void}
   */
  function showApp() {
    el.gate.classList.add(CLASS.hidden);
    el.app.classList.remove(CLASS.hidden);
  }

  /**
   * confirm 패널을 표시한다.
   * 
   * @param {string} preview - 미리보기 문구
   * @returns {void}
   */
  function showConfirm(preview) {
    el.confirmPreview.textContent = preview;
    el.confirmPanel.classList.remove(CLASS.hidden);
  }

  /**
   * confirm 패널을 숨긴다.
   * 
   * @returns {void}
   */
  function hideConfirm() {
    el.confirmPanel.classList.add(CLASS.hidden);
  }

  /**
   * 세션 드로어를 연다.
   * 
   * @returns {void}
   */
  function openDrawer() {
    el.drawer.classList.add(CLASS.drawerOpen);
    el.drawerBackdrop.classList.add(CLASS.backdropShow);
  }

  /**
   * 세션 드로어를 닫는다.
   * 
   * @returns {void}
   */
  function closeDrawer() {
    el.drawer.classList.remove(CLASS.drawerOpen);
    el.drawerBackdrop.classList.remove(CLASS.backdropShow);
  }

  /**
   * 드로어가 열려 있는지 반환한다.
   * 
   * @returns {boolean}
   */
  function isDrawerOpen() {
    return el.drawer.classList.contains(CLASS.drawerOpen);
  }

  /**
   * 마이크 버튼 녹음 표시를 설정한다.
   * 
   * @param {boolean} on - 녹음 중 여부
   * @returns {void}
   */
  function setMicRecording(on) {
    el.btnMic.classList.toggle(CLASS.micRecording, on);
  }

  /**
   * 처리 중 상태를 입력바에 반영한다.
   * 
   * @param {boolean} on - 처리 중 여부
   * @returns {void}
   */
  function setBusy(on) {
    el.btnSend.disabled = on;
  }

  /**
   * 이미지 확대 뷰어를 연다 (아무 곳이나 탭하면 닫힘).
   * 
   * @param {string} src - 표시할 이미지 src (data URL)
   * @returns {void}
   */
  function openViewer(src) {
    el.viewerImg.src = src;
    el.viewer.classList.remove(CLASS.hidden);
  }

  /**
   * 이미지 확대 뷰어를 닫는다.
   * 
   * @returns {void}
   */
  function closeViewer() {
    el.viewer.classList.add(CLASS.hidden);
    el.viewerImg.src = '';
  }

  return {
    el, ROLE,
    addMsg, addLink, scrollBottom, clearChat, setBadge,
    showGate, showApp, showConfirm, hideConfirm,
    openDrawer, closeDrawer, isDrawerOpen,
    setMicRecording, setBusy,
    openViewer, closeViewer,
  };
})();