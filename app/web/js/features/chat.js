'use strict';

/**
 * @file 채팅 모듈 — 텍스트 전송, SSE 스트림 소비, confirm 해소.
 */
window.JarvisWeb = window.JarvisWeb || {};

JarvisWeb.chat = (() => {
  const HTTP_POST = 'POST';
  const SSE_DELIM = '\n\n';
  const SSE_PREFIX = 'data:';
  const MSG_ERROR = '오류가 발생했습니다.';
  const MSG_STATUS = '처리 중...';
  const MSG_PENDING = '...';
  const STREAM_IDLE_MS = 90000;
  const MSG_IMAGE_PROMPT = '이 이미지를 분석해줘.';   // 텍스트 없이 이미지만 첨부한 경우
  const CLASS_MSG_IMG = 'msg__img';
  const CLASS_MSG_IMGS = 'msg__imgs';
  const CLASS_MSG_TEXT = 'msg__text';

  /** @constant {Readonly<Object>} SSE 이벤트 타입 */
  const SSE = Object.freeze({
    TOKEN   : 'token',
    DONE    : 'done',
    STATUS  : 'status',
    CONFIRM : 'confirm_required',
    ERROR   : 'error',
    OPEN_URL: 'open_url',
  });

  /**
   * confirm 패널 기본 안내 문구를 만든다.
   * 
   * @param {string} tool - 도구명
   * @returns {string}
   */
  const confirmDefaultMsg = (tool) => `[${tool}] 실행을 승인하시겠습니까?`;

  let pendingActionId = null;

  /**
   * SSE 이벤트 1건을 처리한다.
   * 
   * @param {Object} ev - 파싱된 이벤트
   * @param {HTMLElement} bubble - 스트리밍 갱신할 버블
   * @param {string} answer - 누적 답변
   * @returns {string} 갱신된 누적 답변
   */
  function _handleEvent(ev, bubble, answer) {
    const { ui, state, api, KEYS } = JarvisWeb;
    if (ev.type === SSE.TOKEN) {
      const next = answer + ev.text;
      bubble.textContent = next;
      ui.scrollBottom();
      return next;
    }
    if (ev.type === SSE.DONE) {
      if (ev.session_id) state.set(KEYS.SESSION_ID, ev.session_id);
      if (ev.answer) bubble.textContent = ev.answer;
      ui.setBadge(ev.agent_type);
      api.playAudio(ev.audio_b64);
      return answer;
    }
    if (ev.type === SSE.STATUS) {
      ui.addMsg(ui.ROLE.STATUS, ev.text || MSG_STATUS);
      return answer;
    }
    if (ev.type === SSE.OPEN_URL) {
      ui.addLink(ev.url);
      return answer;
    }
    if (ev.type === SSE.CONFIRM) {
      pendingActionId = ev.action_id;
      ui.showConfirm(ev.preview || confirmDefaultMsg(ev.tool));
      return answer;
    }
    if (ev.type === SSE.ERROR) {
      bubble.textContent = MSG_ERROR;
      return answer;
    }
    return answer;
  }

  /**
   * SSE 응답 스트림을 소비한다 (stream·confirm 공용). 잔여 버퍼도 처리.
   * 
   * @param {Response} res - fetch 응답
   * @param {HTMLElement} bubble - 스트리밍 갱신할 버블
   * @param {AbortController} ctrl - 유휴 시 중단할 컨트롤러
   * @returns {Promise<void>}
   */
  async function _consumeStream(res, bubble, ctrl) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let answer = '';
    let watchdog = null;
    const resetWatchdog = () => {
      clearTimeout(watchdog);
      watchdog = setTimeout(() => ctrl.abort(), STREAM_IDLE_MS);
    };

    try {
      resetWatchdog();
      while (true) {
        const { done, value } = await reader.read();
        resetWatchdog();
        if (value) buf += decoder.decode(value, { stream: !done });
        let idx;
        while ((idx = buf.indexOf(SSE_DELIM)) !== -1) {
          const line = buf.slice(0, idx).trim();
          buf = buf.slice(idx + SSE_DELIM.length);
          if (!line.startsWith(SSE_PREFIX)) continue;
          try { answer = _handleEvent(JSON.parse(line.slice(SSE_PREFIX.length)), bubble, answer); } catch {}
        }
        if (done) break;
      }
      const rest = buf.trim();
      if (rest.startsWith(SSE_PREFIX)) {
        try { _handleEvent(JSON.parse(rest.slice(SSE_PREFIX.length)), bubble, answer); } catch {}
      }
    } finally {
      clearTimeout(watchdog);
    }
  }

  /**
   * 텍스트(+선택 이미지들) 메시지를 전송하고 스트림을 소비한다.
   * 
   * @param {string} text - 사용자 입력 (이미지만 보낼 땐 빈 문자열 허용)
   * @param {Array<{dataUrl: string}>} [images] - 첨부 이미지 목록 (attach.get())
   * @returns {Promise<void>}
   */
  async function send(text, images = []) {
    const { ui, state, api, KEYS } = JarvisWeb;
    const message = text.trim() || (images.length ? MSG_IMAGE_PROMPT : '');
    if (!message || state.get(KEYS.BUSY)) return;
    state.set(KEYS.BUSY, true);
    ui.setBusy(true);

    // 클로드식 말풍선: 이미지들을 가로로 정렬하고 그 아래 텍스트
    const userBubble = ui.addMsg(ui.ROLE.USER, '');
    if (images.length) {
      const row = document.createElement('div');
      row.className = CLASS_MSG_IMGS;
      for (const image of images) {
        const thumb = document.createElement('img');
        thumb.className = CLASS_MSG_IMG;
        thumb.src = image.dataUrl;
        thumb.alt = '첨부 이미지';
        row.appendChild(thumb);
      }
      userBubble.appendChild(row);
    }
    if (text.trim()) {
      const txt = document.createElement('div');
      txt.className = CLASS_MSG_TEXT;
      txt.textContent = text.trim();
      userBubble.appendChild(txt);
    }
    const bubble = ui.addMsg(ui.ROLE.BOT, MSG_PENDING);
    const ctrl = new AbortController();
    try {
      const body = { message, session_id: state.get(KEYS.SESSION_ID) };
      if (images.length) body.images_b64 = images.map((i) => i.dataUrl.split(',')[1]);
      const res = await fetch(`${api.BASE}/chat/stream`, {
        method : HTTP_POST,
        headers: api.headers(),
        body   : JSON.stringify(body),
        signal : ctrl.signal,
      });
      if (res.status === 401) {
        bubble.parentElement.remove();   // 대기 버블 잔류 방지
        ui.showGate(true);
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await _consumeStream(res, bubble, ctrl);
    } catch (e) {
      console.warn('[web/chat] 전송 실패:', e);
      bubble.textContent = MSG_ERROR;
    } finally {
      state.set(KEYS.BUSY, false);
      ui.setBusy(false);
    }
  }

  /**
   * 대기 중인 confirm을 승인/거절로 해소하고 후속 스트림을 소비한다.
   * 
   * @param {boolean} approved - 승인 여부
   * @returns {Promise<void>}
   */
  async function resolveConfirm(approved) {
    const { ui, state, api, KEYS } = JarvisWeb;
    const actionId = pendingActionId;
    pendingActionId = null;
    ui.hideConfirm();
    if (!actionId) return;
    state.set(KEYS.BUSY, true);
    ui.setBusy(true);
    const bubble = ui.addMsg(ui.ROLE.BOT, MSG_PENDING);
    const ctrl = new AbortController();
    try {
      const res = await fetch(`${api.BASE}/chat/confirm`, {
        method : HTTP_POST,
        headers: api.headers(),
        body   : JSON.stringify({ action_id: actionId, approved }),
        signal : ctrl.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await _consumeStream(res, bubble, ctrl);
    } catch (e) {
      console.warn('[web/chat] confirm 실패:', e);
      bubble.textContent = MSG_ERROR;
    } finally {
      state.set(KEYS.BUSY, false);
      ui.setBusy(false);
    }
  }

  return { send, resolveConfirm };
})();