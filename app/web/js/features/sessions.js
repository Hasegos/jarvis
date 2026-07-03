'use strict';

/**
 * @file 세션 모듈 — 목록·열기·삭제·새 대화.
 */
window.JarvisWeb = window.JarvisWeb || {};

JarvisWeb.sessions = (() => {
  const HTTP_DELETE = 'DELETE';

  /** @constant {Readonly<Object>} 동적 생성 요소 클래스명 */
  const CLASS = Object.freeze({
    item       : 'session-item',
    itemActive : 'session-item--active',
    itemInfo   : 'session-item__info',
    itemTitle  : 'session-item__title',
    itemDate   : 'session-item__date',
    itemDelete : 'session-item__delete',
    placeholder: 'drawer__placeholder',
  });

  /** @constant {Readonly<Object>} 사용자 노출 문구 */
  const MSG = Object.freeze({
    empty        : '대화 기록이 없습니다',
    loadFail     : '불러오기 실패',
    sessionPrefix: '세션 #',
  });

  const DELETE_ICON = '✕';
  const DELETE_TITLE = '삭제';

  /** @constant {Readonly<Object>} 상대 시간 경계(초) */
  const SEC = Object.freeze({ MIN: 60, HOUR: 3600, DAY: 86400, WEEK: 604800 });
  /** @constant {Readonly<Object>} 상대 시간 접미사 */
  const REL = Object.freeze({ now: '방금 전', min: '분 전', hour: '시간 전', day: '일 전' });

  /**
   * ISO 시각을 상대/절대 문자열로 포맷한다.
   * 
   * @param {string} iso - ISO 8601 시각
   * @returns {string} 표시용 문자열
   */
  function _fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const diff = (new Date() - d) / 1000;
    if (diff < SEC.MIN)  return REL.now;
    if (diff < SEC.HOUR) return `${Math.floor(diff / SEC.MIN)}${REL.min}`;
    if (diff < SEC.DAY)  return `${Math.floor(diff / SEC.HOUR)}${REL.hour}`;
    if (diff < SEC.WEEK) return `${Math.floor(diff / SEC.DAY)}${REL.day}`;
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${d.getFullYear()}.${mm}.${dd}`;
  }

  /**
   * 목록 영역에 안내 문구를 표시한다.
   * 
   * @param {string} text - 안내 문구
   * @returns {void}
   */
  function _setPlaceholder(text) {
    const p = document.createElement('li');
    p.className = CLASS.placeholder;
    p.textContent = text;
    JarvisWeb.ui.el.sessionList.replaceChildren(p);
  }

  /**
   * 세션 1건의 드로어 아이템 요소를 생성한다.
   * 
   * @param {Object} s - 세션 데이터 (session_id, summary, last_active_at)
   * @returns {HTMLLIElement}
   */
  function _buildItem(s) {
    const { state, KEYS } = JarvisWeb;
    const li = document.createElement('li');
    li.className = CLASS.item
      + (s.session_id === state.get(KEYS.SESSION_ID) ? ` ${CLASS.itemActive}` : '');
    li.dataset.id = String(s.session_id);

    const info = document.createElement('div');
    info.className = CLASS.itemInfo;

    const title = document.createElement('div');
    title.className = CLASS.itemTitle;
    title.textContent = s.summary || `${MSG.sessionPrefix}${s.session_id}`;

    const date = document.createElement('div');
    date.className = CLASS.itemDate;
    date.textContent = _fmtDate(s.last_active_at || s.started_at);

    info.append(title, date);

    const del = document.createElement('button');
    del.className = CLASS.itemDelete;
    del.title = DELETE_TITLE;
    del.textContent = DELETE_ICON;

    li.append(info, del);
    return li;
  }

  /**
   * 세션 목록을 불러와 드로어에 렌더한다.
   * 
   * @returns {Promise<void>}
   */
  async function load() {
    const { ui, api } = JarvisWeb;
    try {
      const res = await fetch(`${api.BASE}/chat/sessions`, { headers: api.headers(false) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const sessions = await res.json();

      if (!sessions.length) {
        _setPlaceholder(MSG.empty);
        return;
      }
      const frag = document.createDocumentFragment();
      for (const s of sessions) frag.appendChild(_buildItem(s));
      ui.el.sessionList.replaceChildren(frag);
    } catch (e) {
      console.warn('[web/sessions] 목록 로드 실패:', e);
      _setPlaceholder(MSG.loadFail);
    }
  }

  /**
   * 세션의 메시지를 채팅 뷰로 불러온다.
   * 
   * @param {number} id - 세션 id
   * @returns {Promise<void>}
   */
  async function open(id) {
    const { ui, state, api, KEYS } = JarvisWeb;
    state.set(KEYS.SESSION_ID, id);
    ui.clearChat();
    try {
      const res = await fetch(`${api.BASE}/chat/sessions/${id}/messages`, { headers: api.headers(false) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const messages = await res.json();
      for (const m of messages) {
        ui.addMsg(m.role === ui.ROLE.USER ? ui.ROLE.USER : ui.ROLE.BOT, m.content || '');
      }
    } catch (e) {
      console.warn('[web/sessions] 메시지 로드 실패:', e);
    }
  }

  /**
   * 세션을 삭제하고 목록을 갱신한다.
   * 
   * @param {number} id - 세션 id
   * @returns {Promise<void>}
   */
  async function remove(id) {
    const { api } = JarvisWeb;
    try {
      await fetch(`${api.BASE}/chat/sessions/${id}`, { method: HTTP_DELETE, headers: api.headers(false) });
    } catch (e) {
      console.warn('[web/sessions] 삭제 실패:', e);
    }
    await load();
  }

  /**
   * 새 대화를 시작한다 (세션 초기화 + 화면 비움 + 드로어 닫기).
   * 
   * @returns {void}
   */
  function startNew() {
    const { ui, state, KEYS } = JarvisWeb;
    state.set(KEYS.SESSION_ID, null);
    ui.clearChat();
    ui.closeDrawer();
    ui.setBadge();
  }

  return { CLASS, load, open, remove, startNew };
})();