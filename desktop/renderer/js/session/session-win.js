'use strict';

/**
 * @file 세션창 모듈 (별도 렌더러 컨텍스트) — 세션 목록·대화 기록·텍스트 입력.
 */
window.Jarvis = window.Jarvis || {};

Jarvis.sessionPanel = (() => {
  const HTTP_DELETE = 'DELETE';
  const PANEL_W = 380;
  const FULL_H = 640;
  const MIN_H = 108;
  const SLIDER_MAX = 100;
  const ROLE_USER = 'user';

  const ICON_RESTORE = '□';
  const ICON_MINIMIZE = '−';

  const ATTACH_MAX_DIM = 1280;
  const ATTACH_MAX_COUNT = 4;
  const ATTACH_JPEG_MIME = 'image/jpeg';
  const ATTACH_JPEG_QUALITY = 0.8;
  const MSG_ATTACH_FAIL = '이미지를 불러올 수 없습니다.';
  const MSG_ATTACH_LIMIT = `이미지는 최대 ${ATTACH_MAX_COUNT}장까지`;
  const TITLE_RESTORE = '복원';
  const TITLE_MINIMIZE = '최소화';
  const DELETE_TITLE = '삭제';
  const DELETE_ICON = '✕';

  /** @constant {Readonly<Object>} 뷰 식별자 */
  const VIEW = Object.freeze({ SESSIONS: 'sessions', MESSAGES: 'messages' });
  /** @constant {Readonly<Object>} 상대 시간 경계(초) */
  const SEC = Object.freeze({ MIN: 60, HOUR: 3600, DAY: 86400, WEEK: 604800 });
  /** @constant {Readonly<Object>} 상대 시간 접미사 */
  const REL = Object.freeze({ now: '방금 전', min: '분 전', hour: '시간 전', day: '일 전' });

  /** @constant {Readonly<Object>} 동적 생성 요소 클래스명 */
  const CLASS = Object.freeze({
    hidden      : 'hidden',
    placeholder : 'session-panel__placeholder',
    item        : 'session-item',
    itemActive  : 'session-item--active',
    itemInfo    : 'session-item__info',
    itemTitle   : 'session-item__title',
    itemDate    : 'session-item__date',
    itemDelete  : 'session-item__delete',
    msg         : 'msg',
    msgUser     : 'msg--user',
    msgBot      : 'msg--assistant',
    msgLabel    : 'msg__label',
    msgBubble   : 'msg__bubble',
    btnActive   : 'session-panel__btn--active',
    micRecording: 'session-panel__mic--recording',
  });

  /** @constant {Readonly<Object>} 사용자 노출 문구 */
  const MSG = Object.freeze({
    loading      : '불러오는 중...',
    loadFail     : '불러오기 실패',
    emptySessions: '대화 기록이 없습니다',
    emptyMessages: '대화 기록이 없습니다',
    defaultTitle : '대화 기록',
    newTitle     : '새 대화',
    sessionPrefix: '세션 #',
    labelUser    : '나',
    labelBot     : 'Jarvis',
  });

  /** DOM 참조 (scripts 는 body 하단 → 파싱 완료) */
  const el = {
    panel       : Jarvis.dom.$('.session-panel'),
    title       : Jarvis.dom.$id('sw-title'),
    btnBack     : Jarvis.dom.$id('btn-back'),
    btnMinimize : Jarvis.dom.$id('btn-minimize'),
    btnNew      : Jarvis.dom.$id('btn-new'),
    btnClose    : Jarvis.dom.$id('btn-close'),
    btnOpacity  : Jarvis.dom.$id('btn-opacity'),
    btnSend     : Jarvis.dom.$id('btn-send'),
    btnMic      : Jarvis.dom.$id('btn-mic'),
    viewSessions: Jarvis.dom.$id('view-sessions'),
    viewMessages: Jarvis.dom.$id('view-messages'),
    sessionList : Jarvis.dom.$id('session-list'),
    messageList : Jarvis.dom.$id('message-list'),
    input       : Jarvis.dom.$id('chat-input'),
    opacityRow  : Jarvis.dom.$id('opacity-row'),
    opacitySlider: Jarvis.dom.$id('opacity-slider'),
    opacityVal  : Jarvis.dom.$id('opacity-val'),
    btnAttach   : Jarvis.dom.$id('btn-attach'),
    attachInput : Jarvis.dom.$id('attach-input'),
    attachPreview: Jarvis.dom.$id('attach-preview'),
    viewer      : Jarvis.dom.$id('viewer'),
    viewerImg   : Jarvis.dom.$id('viewer-img'),
  };

  let _sessions = [];
  let _activeId = null;
  let _isRecording = false;
  let _minimized = false;
  let _currentView = VIEW.SESSIONS;
  let _attachList = [];   // 전송 대기 첨부 목록 [{ b64, dataUrl }]

  /**
   * 세션 목록/대화 기록 뷰를 전환한다 (최소화 상태면 무시).
   * 
   * @param {string} name - VIEW.SESSIONS | VIEW.MESSAGES
   * @returns {void}
   */
  function _showView(name) {
    _currentView = name;
    if (_minimized) return;
    el.viewSessions.classList.toggle(CLASS.hidden, name !== VIEW.SESSIONS);
    el.viewMessages.classList.toggle(CLASS.hidden, name !== VIEW.MESSAGES);
    el.btnBack.hidden = (name !== VIEW.MESSAGES);
  }

  /**
   * 패널을 최소화/복원하고 창 크기를 조절한다.
   * 
   * @returns {void}
   */
  function _toggleMinimize() {
    _minimized = !_minimized;
    el.btnMinimize.textContent = _minimized ? ICON_RESTORE : ICON_MINIMIZE;
    el.btnMinimize.title = _minimized ? TITLE_RESTORE : TITLE_MINIMIZE;

    if (_minimized) {
      el.viewSessions.classList.add(CLASS.hidden);
      el.viewMessages.classList.add(CLASS.hidden);
      el.btnBack.hidden = true;
      el.opacityRow.classList.add(CLASS.hidden);
      el.btnOpacity.classList.remove(CLASS.btnActive);
    } else {
      el.viewSessions.classList.toggle(CLASS.hidden, _currentView !== VIEW.SESSIONS);
      el.viewMessages.classList.toggle(CLASS.hidden, _currentView !== VIEW.MESSAGES);
      el.btnBack.hidden = (_currentView !== VIEW.MESSAGES);
    }
    window.electronAPI?.setWinSize(PANEL_W, _minimized ? MIN_H : FULL_H);
  }

  /**
   * 세션 목록을 서버에서 불러와 렌더한다.
   * 
   * @returns {Promise<void>}
   */
  async function loadSessions() {
    _setPlaceholder(el.sessionList, MSG.loading);
    try {
      const res = await Jarvis.api.fetchWithTimeout(Jarvis.api.chatSessions);
      _sessions = await res.json();
      _renderSessions();
    } catch (e) {
      console.warn('[sessionPanel] 세션 목록 로드 실패:', e);
      _setPlaceholder(el.sessionList, MSG.loadFail);
    }
  }

  /**
   * 현재 _sessions 배열을 목록 DOM으로 렌더한다.
   * 
   * @returns {void}
   */
  function _renderSessions() {
    if (!_sessions.length) {
      _setPlaceholder(el.sessionList, MSG.emptySessions);
      return;
    }
    const frag = document.createDocumentFragment();
    for (const s of _sessions) frag.appendChild(_buildSessionItem(s));
    el.sessionList.replaceChildren(frag);
  }

  /**
   * 세션 1건의 목록 아이템 요소를 생성한다.
   * 
   * @param {Object} s - 세션 데이터 (session_id, summary, ...)
   * @returns {HTMLDivElement}
   */
  function _buildSessionItem(s) {
    const summary = s.summary || `${MSG.sessionPrefix}${s.session_id}`;

    const item = document.createElement('div');
    item.className = CLASS.item;
    item.dataset.id = String(s.session_id);
    item.dataset.summary = summary;
    if (s.session_id === _activeId) item.classList.add(CLASS.itemActive);

    const info = document.createElement('div');
    info.className = CLASS.itemInfo;

    const title = document.createElement('div');
    title.className = CLASS.itemTitle;
    title.textContent = summary;

    const date = document.createElement('div');
    date.className = CLASS.itemDate;
    date.textContent = _fmtDate(s.last_active_at || s.started_at);

    info.append(title, date);

    const del = document.createElement('button');
    del.className = CLASS.itemDelete;
    del.title = DELETE_TITLE;
    del.textContent = DELETE_ICON;

    item.append(info, del);
    return item;
  }

  /**
   * 세션을 선택해 캐릭터창에 전환 신호를 보내고 대화 기록을 로드한다.
   * 
   * @param {number} id - 세션 id
   * @param {string} summary - 표시 제목
   * @returns {Promise<void>}
   */
  async function _selectSession(id, summary) {
    _activeId = id;
    window.electronAPI?.switchSession(id);
    el.title.textContent = summary || `${MSG.sessionPrefix}${id}`;
    _showView(VIEW.MESSAGES);
    await _loadMessages(id);
  }

  /**
   * 세션을 삭제하고 목록을 갱신한다.
   * 
   * @param {number} id - 세션 id
   * @returns {Promise<void>}
   */
  async function _deleteSession(id) {
    try {
      await Jarvis.api.fetchWithTimeout(`${Jarvis.api.chatSessions}/${id}`, { method: HTTP_DELETE });
      _sessions = _sessions.filter((s) => s.session_id !== id);
      if (_activeId === id) {
        _activeId = null;
        el.title.textContent = MSG.defaultTitle;
        _showView(VIEW.SESSIONS);
      }
      _renderSessions();
    } catch (e) {
      console.warn('[sessionPanel] 세션 삭제 실패:', e);
    }
  }

  /**
   * 세션의 대화 기록을 서버에서 불러와 렌더한다.
   * 
   * @param {number} id - 세션 id
   * @returns {Promise<void>}
   */
  async function _loadMessages(id) {
    _setPlaceholder(el.messageList, MSG.loading);
    try {
      const res = await Jarvis.api.fetchWithTimeout(`${Jarvis.api.chatSessions}/${id}/messages`);
      const messages = await res.json();
      _renderMessages(messages);
    } catch (e) {
      console.warn('[sessionPanel] 메시지 로드 실패:', e);
      _setPlaceholder(el.messageList, MSG.loadFail);
    }
  }

  /**
   * 메시지 배열을 대화 기록 DOM으로 렌더하고 최하단으로 스크롤한다.
   * 
   * @param {Array<Object>} messages - 메시지 목록 (role, content)
   * @returns {void}
   */
  function _renderMessages(messages) {
    if (!messages || !messages.length) {
      _setPlaceholder(el.messageList, MSG.emptyMessages);
      return;
    }
    const frag = document.createDocumentFragment();
    for (const m of messages) frag.appendChild(_buildMessage(m));
    el.messageList.replaceChildren(frag);
    el.messageList.scrollTop = el.messageList.scrollHeight;
  }

  /**
   * 메시지 1건의 말풍선 요소를 생성한다.
   * 
   * @param {Object} m - 메시지 (role, content)
   * @returns {HTMLDivElement}
   */
  function _buildMessage(m) {
    const isUser = m.role === ROLE_USER;

    const wrap = document.createElement('div');
    wrap.className = `${CLASS.msg} ${isUser ? CLASS.msgUser : CLASS.msgBot}`;

    const label = document.createElement('div');
    label.className = CLASS.msgLabel;
    label.textContent = isUser ? MSG.labelUser : MSG.labelBot;

    const bubble = document.createElement('div');
    bubble.className = CLASS.msgBubble;
    bubble.textContent = m.content || '';

    wrap.append(label, bubble);
    return wrap;
  }

  /**
   * 컨테이너에 안내 문구(placeholder)를 표시한다.
   * 
   * @param {HTMLElement} container - 대상 컨테이너
   * @param {string} text - 안내 문구
   * @returns {void}
   */
  function _setPlaceholder(container, text) {
    const p = document.createElement('p');
    p.className = CLASS.placeholder;
    p.textContent = text;
    container.replaceChildren(p);
  }

  /**
   * 파일을 Image 요소로 로드한다.
   * 
   * @param {File} file - 이미지 파일
   * @returns {Promise<HTMLImageElement>}
   */
  function _loadImage(file) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = (e) => { URL.revokeObjectURL(url); reject(e); };
      img.src = url;
    });
  }

  /**
   * 첨부 미리보기 스트립을 현재 목록으로 다시 그린다.
   * 
   * @returns {void}
   */
  function _renderAttach() {
    el.attachPreview.replaceChildren();
    _attachList.forEach((item, idx) => {
      const wrap = document.createElement('div');
      wrap.className = 'attach-preview__item';

      const img = document.createElement('img');
      img.className = 'attach-preview__img';
      img.src = item.dataUrl;
      img.alt = `첨부 이미지 ${idx + 1}`;
      img.addEventListener('click', () => _openViewer(item.dataUrl));   // 클릭 → 확대 뷰어

      const del = document.createElement('button');
      del.className = 'attach-preview__remove';
      del.title = DELETE_TITLE;
      del.textContent = DELETE_ICON;
      del.addEventListener('click', () => {
        _attachList.splice(idx, 1);
        _renderAttach();
      });

      wrap.append(img, del);
      el.attachPreview.appendChild(wrap);
    });
    el.attachPreview.classList.toggle(CLASS.hidden, _attachList.length === 0);
  }

  /**
   * 선택/붙여넣기된 이미지들을 리사이즈해 첨부 목록에 추가한다 (최대 4장).
   * 
   * @param {FileList|File[]} files - 이미지 파일들
   * @returns {Promise<void>}
   */
  async function _addAttach(files) {
    for (const file of [...files]) {
      if (!file || !file.type.startsWith('image/')) continue;
      if (_attachList.length >= ATTACH_MAX_COUNT) {
        el.input.placeholder = MSG_ATTACH_LIMIT;
        break;
      }
      try {
        const img = await _loadImage(file);
        const ratio = Math.min(ATTACH_MAX_DIM / img.width, ATTACH_MAX_DIM / img.height, 1);
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(img.width * ratio);
        canvas.height = Math.round(img.height * ratio);
        canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
        // b64는 전송 시 dataUrl에서 파생 (중복 보관 방지)
        _attachList.push({ dataUrl: canvas.toDataURL(ATTACH_JPEG_MIME, ATTACH_JPEG_QUALITY) });
      } catch (e) {
        console.warn('[sessionPanel] 이미지 처리 실패:', e);
        el.input.placeholder = MSG_ATTACH_FAIL;
      }
    }
    _renderAttach();
  }

  /**
   * 이미지 확대 뷰어를 연다 (아무 곳이나 클릭하면 닫힘).
   * 
   * @param {string} src - 표시할 이미지 src (data URL)
   * @returns {void}
   */
  function _openViewer(src) {
    el.viewerImg.src = src;
    el.viewer.classList.remove(CLASS.hidden);
  }

  /**
   * 이미지 확대 뷰어를 닫는다.
   * 
   * @returns {void}
   */
  function _closeViewer() {
    el.viewer.classList.add(CLASS.hidden);
    el.viewerImg.src = '';
  }

  /**
   * 첨부 전체를 해제한다.
   * 
   * @returns {void}
   */
  function _clearAttach() {
    _attachList = [];
    el.attachInput.value = '';
    _renderAttach();
  }

  /**
   * 입력창 텍스트(+첨부 이미지들)를 캐릭터창으로 전송하고 입력 상태를 비운다.
   * 
   * @returns {void}
   */
  function _handleSend() {
    const text = el.input.value.trim();
    if (!text && !_attachList.length) return;
    el.input.value = '';
    el.input.style.height = '';
    window.electronAPI?.sendChatText(text, _attachList.map((a) => a.dataUrl.split(',')[1]));
    _clearAttach();
  }

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
   * 마이크 버튼 녹음 표시 상태를 토글한다.
   * 
   * @returns {void}
   */
  function _toggleMicUI() {
    _isRecording = !_isRecording;
    el.btnMic.classList.toggle(CLASS.micRecording, _isRecording);
  }

  const scope = Jarvis.dom.createScope();

  scope.on(el.btnMinimize, 'click', _toggleMinimize);

  scope.on(el.btnBack, 'click', () => {
    el.title.textContent = MSG.defaultTitle;
    _showView(VIEW.SESSIONS);
  });

  scope.on(el.btnNew, 'click', () => {
    window.electronAPI?.newSession();
    _activeId = null;
    el.title.textContent = MSG.newTitle;
    _showView(VIEW.SESSIONS);
    el.input.style.height = '';
    el.input.focus();
  });

  scope.on(el.btnClose, 'click', () => window.electronAPI?.closeWindow());

  scope.on(el.btnSend, 'click', _handleSend);

  scope.on(el.input, 'input', (e) => {
    e.target.style.height = '';
    e.target.style.height = `${e.target.scrollHeight}px`;
  });

  scope.on(el.input, 'keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      _handleSend();
    }
  });

  scope.on(el.btnMic, 'click', () => {
    _toggleMicUI();
    window.electronAPI?.micToggle();
  });

  // 이미지 첨부: 📎 다중 선택 / Ctrl+V 붙여넣기
  scope.on(el.btnAttach, 'click', () => el.attachInput.click());
  scope.on(el.attachInput, 'change', (e) => {
    if (e.target.files?.length) _addAttach(e.target.files);
  });
  scope.on(el.input, 'paste', (e) => {
    const files = [...(e.clipboardData?.items || [])]
      .filter((i) => i.type.startsWith('image/'))
      .map((i) => i.getAsFile());
    if (files.length) { e.preventDefault(); _addAttach(files); }
  });

  // 이미지 확대 뷰어: 아무 곳이나 클릭하면 닫힘
  scope.on(el.viewer, 'click', _closeViewer);

  // 세션 목록: 이벤트 위임
  scope.on(el.sessionList, 'click', (e) => {
    const item = e.target.closest(`.${CLASS.item}`);
    if (!item) return;
    const id = Number(item.dataset.id);
    if (e.target.closest(`.${CLASS.itemDelete}`)) {
      _deleteSession(id);
      return;
    }
    _selectSession(id, item.dataset.summary);
  });

  scope.on(el.btnOpacity, 'click', () => {
    const willShow = el.opacityRow.classList.contains(CLASS.hidden);
    el.opacityRow.classList.toggle(CLASS.hidden, !willShow);
    el.btnOpacity.classList.toggle(CLASS.btnActive, willShow);
  });

  scope.on(el.opacitySlider, 'input', (e) => {
    const val = e.target.value;
    el.opacityVal.textContent = `${val}%`;
    el.panel.style.opacity = val / SLIDER_MAX;
  });

  // F9 / voice-toggle IPC → 마이크 버튼 상태 동기화
  window.electronAPI?.onVoiceToggle?.(_toggleMicUI);
  // 새 세션 생성 시 목록 갱신
  window.electronAPI?.onRefreshSessions?.(() => loadSessions());

  // 생명주기 + 초기화
  window.addEventListener('beforeunload', () => Jarvis.bus.emit(Jarvis.EVENTS.TEARDOWN), { once: true });
  Jarvis.bus.on(Jarvis.EVENTS.TEARDOWN, () => scope.dispose());

  loadSessions();

  return { loadSessions };
})();