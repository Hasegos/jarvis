/**
 * JARVIS 홀로그램 — 세션 관리 / 패널 모드
 */
'use strict';
window.JARVIS = window.JARVIS || {};

(function (J) {

  /**
   * 숨김 세션 목록 조회 (localStorage)
   *
   * @returns {number[]} 숨긴 세션 ID 배열
   */
  function getHidden() {
    try { return JSON.parse(localStorage.getItem(J.const.HIDDEN_KEY)) || []; }
    catch { return []; }
  }

  /**
   * 숨김 세션 목록 저장 (localStorage)
   *
   * @param {number[]} arr - 저장할 숨긴 세션 ID 배열
   */
  function setHidden(arr) { localStorage.setItem(J.const.HIDDEN_KEY, JSON.stringify(arr)); }

  /**
   * 세션을 숨김 목록에 추가
   *
   * @param {number} id - 숨길 세션 ID
   */
  function hideSession(id) { const h = getHidden(); if (!h.includes(id)) { h.push(id); setHidden(h); } }

  /**
   * 세션을 숨김 목록에서 제거 (복원)
   *
   * @param {number} id - 복원할 세션 ID
   */
  function unhideSession(id) { setHidden(getHidden().filter(x => x !== id)); }

  /**
   * 1. 최신 세션 로드
   *
   * 숨긴 세션을 제외하고 가장 최근 세션을 현재 세션으로 설정한다.
   */
  J.loadLatestSession = async function () {
    try {
      const sessions = await apiFetch(API_ENDPOINTS.sessions);
      const hidden = getHidden();
      const visible = sessions.filter(s => !hidden.includes(s.session_id));
      if (visible.length) {
        J.state.currentSessionId = visible[0].session_id;
        await J.loadMessages(J.state.currentSessionId);
      } else {
        J.state.currentSessionId = null;
      }
    } catch (e) {
      console.error('세션 로드 실패', e);
    }
  };

  /**
   * 세션 메시지 로드
   *
   * 채팅 패널을 비우고 해당 세션의 메시지를 다시 렌더한다.
   *
   * @param {number} id - 로드할 세션 ID
   */
  J.loadMessages = async function (id) {
    J.clearMessages();
    try {
      const msgs = await apiFetch(API_ENDPOINTS.messages(id));
      msgs.forEach(m => J.addMessage(m.role, m.content));
    } catch (e) {
      console.error('메시지 로드 실패', e);
    }
  };

  /**
   * 새 대화 시작
   *
   * 현재 세션을 null로 초기화하고 채팅 패널을 비운다.
   * 다음 메시지 전송 시 서버에서 새 세션이 자동 생성된다.
   */
  J.newSession = function () {
    J.state.currentSessionId = null;
    J.clearMessages();
    J.setPanelMode('collapsed');
  };

  /**
   * 2. 세션 목록 열기
   *
   * 패널을 sessions 모드로 전환하고, 표시/숨김 세션 목록을 렌더한다.
   */
  J.openSessions = async function () {
    J.setPanelMode('sessions');
    J.dom.sessionList.innerHTML = '불러오는 중…';
    J.dom.hiddenList.innerHTML = '';
    try {
      const sessions = await apiFetch(API_ENDPOINTS.sessions);
      const hidden = getHidden();
      J.dom.sessionList.innerHTML = '';
      sessions.filter(s => !hidden.includes(s.session_id))
        .forEach(s => J.dom.sessionList.appendChild(renderSessionItem(s, false)));
      sessions.filter(s => hidden.includes(s.session_id))
        .forEach(s => J.dom.hiddenList.appendChild(renderSessionItem(s, true)));
    } catch (e) {
      J.dom.sessionList.textContent = '목록을 불러오지 못했습니다.';
      console.error('세션 목록 실패', e);
    }
  };

  /**
   * 세션 항목 DOM 생성
   *
   * 표시 세션: 클릭 → 선택, ✕ → 숨기기.
   * 숨긴 세션: 복원 / 영구 삭제 버튼.
   *
   * @param {Object} s - 세션 객체 ({session_id, summary, started_at, last_active_at})
   * @param {boolean} isHidden - 숨긴 세션이면 true
   * @returns {HTMLElement} 세션 항목 DOM
   */
  function renderSessionItem(s, isHidden) {
    const item = document.createElement('div');
    item.className = 'session-item' + (s.session_id === J.state.currentSessionId ? ' session-item--active' : '');

    const main = document.createElement('div');
    main.className = 'session-item__main';
    const sum = document.createElement('div');
    sum.className = 'session-item__summary';
    sum.textContent = s.summary || `세션 #${s.session_id}`;
    const date = document.createElement('div');
    date.className = 'session-item__date';
    date.textContent = fmtDate(s.last_active_at || s.started_at);
    main.append(sum, date);

    if (!isHidden) {
      main.addEventListener('click', () => J.selectSession(s.session_id));
      const del = document.createElement('button');
      del.className = 'session-item__del';
      del.textContent = '✕';
      del.title = '목록에서 숨기기';
      del.addEventListener('click', e => {
        e.stopPropagation();
        hideSession(s.session_id);
        if (s.session_id === J.state.currentSessionId) { J.state.currentSessionId = null; J.clearMessages(); }
        J.openSessions();
      });
      item.append(main, del);
    } else {
      const restore = document.createElement('button');
      restore.className = 'session-item__btn session-item__btn--restore';
      restore.textContent = '복원';
      restore.addEventListener('click', () => { unhideSession(s.session_id); J.openSessions(); });
      const purge = document.createElement('button');
      purge.className = 'session-item__btn session-item__btn--purge';
      purge.textContent = '영구 삭제';
      purge.addEventListener('click', () => J.purgeSession(s.session_id));
      item.append(main, restore, purge);
    }
    return item;
  }

  /**
   * 세션 선택
   *
   * 해당 세션의 메시지를 로드하고 패널을 축소한다.
   *
   * @param {number} id - 선택할 세션 ID
   */
  J.selectSession = async function (id) {
    J.state.currentSessionId = id;
    await J.loadMessages(id);
    J.setPanelMode('collapsed');
  };

  /**
   * 세션 영구 삭제
   *
   * confirm 경고 후 DB에서 삭제하고 숨김 목록에서도 제거한다.
   *
   * @param {number} id - 삭제할 세션 ID
   */
  J.purgeSession = async function (id) {
    if (!confirm('이 대화를 영구 삭제합니다. 복구할 수 없습니다. 계속하시겠습니까?')) return;
    try {
      await apiFetch(API_ENDPOINTS.session(id), { method: 'DELETE' });
    } catch (e) {
      console.error('영구 삭제 실패', e);
    }
    unhideSession(id);
    if (id === J.state.currentSessionId) { J.state.currentSessionId = null; J.clearMessages(); }
    J.openSessions();
  };

  /**
   * 3. 패널 모드 전환
   *
   * collapsed(최근 대화) / expanded(전체 기록) / sessions(세션 목록).
   *
   * @param {string} mode - 'collapsed' | 'expanded' | 'sessions'
   */
  J.setPanelMode = function (mode) {
    J.state.panelMode = mode;
    const p = J.dom.hudPanel;
    p.classList.toggle('hud-panel--expanded', mode !== 'collapsed');
    p.classList.toggle('hud-panel--collapsed', mode === 'collapsed');
    const showSessions = mode === 'sessions';
    J.dom.sessions.hidden = !showSessions;
    J.dom.messages.hidden = showSessions;
    if (!showSessions) J.dom.messages.scrollTop = J.dom.messages.scrollHeight;
  };

  /**
   * 패널 확장/축소 토글
   *
   * sessions 모드에서는 expanded로 전환한다.
   */
  J.toggleExpand = function () {
    if (J.state.panelMode === 'sessions') { J.setPanelMode('expanded'); return; }
    J.setPanelMode(J.state.panelMode === 'collapsed' ? 'expanded' : 'collapsed');
  };

  /**
   * 패널 숨기기
   *
   * 패널을 완전히 숨기고 FAB 아이콘만 표시한다.
   * 숨겨진 동안에도 F9 음성은 동작한다.
   */
  J.hidePanel = function () {
    J.state.panelHidden = true;
    J.dom.hudPanel.hidden = true;
    J.dom.fab.hidden = false;
  };

  /**
   * 패널 보이기
   *
   * FAB 아이콘을 숨기고 패널을 collapsed 상태로 복원한다.
   */
  J.showPanel = function () {
    J.state.panelHidden = false;
    J.dom.fab.hidden = true;
    J.dom.fabDot.hidden = true;
    J.dom.hudPanel.hidden = false;
    J.setPanelMode('collapsed');
  };

})(window.JARVIS);