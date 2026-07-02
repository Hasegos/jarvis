'use strict';

/**
 * @file 채팅 모듈 — 텍스트 전송, SSE 스트림 소비, 승인/거절 패널.
 */
window.Jarvis = window.Jarvis || {};

Jarvis.chat = (() => {
  const HTTP_POST = 'POST';
  const JSON_HEADERS = { 'Content-Type': 'application/json' };
  const ABORT_ERROR = 'AbortError';

  const SSE_DELIM = '\n\n';
  const SSE_PREFIX = 'data:';
  // SSE는 LLM 생성 시간만큼 길어질 수 있어 고정 타임아웃 대신 "유휴" 감시
  const STREAM_IDLE_MS = 90000;

  /** @constant {Readonly<Object>} SSE 이벤트 타입 */
  const SSE = Object.freeze({
    TOKEN   : 'token',
    DONE    : 'done',
    STATUS  : 'status',
    CONFIRM : 'confirm_required',
    ERROR   : 'error',
    OPEN_URL: 'open_url',
  });

  const MSG_ERROR = '오류가 발생했습니다.';
  const MSG_STATUS = '처리 중...';

  /** @constant {Readonly<Object>} agent_type → 배지 라벨 (이모지는 UI 전용) */
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

  /**
   * 승인 패널 기본 안내 문구를 만든다.
   * 
   * @param {string} tool - 도구명
   * @returns {string}
   */
  const confirmDefaultMsg = (tool) => `[${tool}] 실행을 승인하시겠습니까?`;

  const confirmPanel = Jarvis.dom.$id('confirm-panel');
  const confirmPreview = Jarvis.dom.$id('confirm-preview');
  const agentBadge = Jarvis.dom.$id('agent-badge');

  /**
   * Agent 배지를 갱신한다. 알 수 없는 타입은 general 라벨로 표시.
   * 
   * @param {string} agentType - done 이벤트의 agent_type
   * @returns {void}
   */
  function _setAgentBadge(agentType) {
    if (!agentBadge) return;
    agentBadge.textContent = AGENT_LABELS[agentType] || AGENT_LABELS[AGENT_DEFAULT];
  }

  let abortCtrl = null;
  let pendingActionId = null;
  let perfT0 = 0;
  let perfFirstToken = false;

  const MSG_IMAGE_PROMPT = '이 이미지를 분석해줘.';   // 텍스트 없이 이미지만 첨부한 경우

  /**
   * 텍스트(+선택 이미지들) 메시지를 전송하고 SSE 응답을 소비한다. 이전 스트림은 취소된다.
   * 
   * @param {string} text - 사용자 입력 (이미지만 보낼 땐 빈 문자열 허용)
   * @param {string[]} [imagesB64] - 첨부 이미지 base64 목록 (세션창 첨부)
   * @returns {Promise<void>}
   */
  async function send(text, imagesB64 = []) {
    const message = (text || '').trim() || (imagesB64.length ? MSG_IMAGE_PROMPT : '');
    if (Jarvis.state.get(Jarvis.KEYS.BUSY) || !message) return;
    Jarvis.avatar.interruptAudio();   // 진행 중 발화(능동 발화 등) 중단

    if (abortCtrl) { abortCtrl.abort(); abortCtrl = null; }
    Jarvis.state.set(Jarvis.KEYS.BUSY, true);
    abortCtrl = new AbortController();
    perfT0 = performance.now();
    perfFirstToken = false;

    try {
      const body = { message, session_id: Jarvis.state.get(Jarvis.KEYS.SESSION_ID) };
      if (imagesB64.length) body.images_b64 = imagesB64;
      const res = await fetch(Jarvis.api.chatStream, {
        method : HTTP_POST,
        headers: JSON_HEADERS,
        body   : JSON.stringify(body),
        signal : abortCtrl.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await _consumeStream(res);
    } catch (e) {
      if (e.name === ABORT_ERROR) return;
      console.warn('[chat] 전송 실패:', e);   // 네트워크 실패 → 복구 가능
      Jarvis.avatar.showBubble(MSG_ERROR);
    } finally {
      Jarvis.state.set(Jarvis.KEYS.BUSY, false);
      abortCtrl = null;
    }
  }

  /**
   * SSE 스트림을 읽어 이벤트 단위로 처리한다. 잔여 버퍼의 done 이벤트도 처리.
   * 
   * @param {Response} res - fetch 응답 (스트림 body)
   * @returns {Promise<void>}
   */
  async function _consumeStream(res) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let answer = '';
    let watchdog = null;
    const resetWatchdog = () => {
      clearTimeout(watchdog);
      watchdog = setTimeout(() => { try { reader.cancel(); } catch {} }, STREAM_IDLE_MS);
    };

    try {
      resetWatchdog();
      while (true) {
        const { done, value } = await reader.read();
        resetWatchdog();
        if (value) buf += decoder.decode(value, { stream: !done });
        if (done) break;

        let idx;
        while ((idx = buf.indexOf(SSE_DELIM)) !== -1) {
          const line = buf.slice(0, idx).trim();
          buf = buf.slice(idx + SSE_DELIM.length);
          if (!line.startsWith(SSE_PREFIX)) continue;

          let ev;
          try { ev = JSON.parse(line.slice(SSE_PREFIX.length)); } catch { continue; }
          answer = await _handleEvent(ev, answer);
        }
      }

      const remaining = buf.trim();
      if (remaining.startsWith(SSE_PREFIX)) {
        try {
          const ev = JSON.parse(remaining.slice(SSE_PREFIX.length));
          if (ev.type === SSE.DONE) _setAgentBadge(ev.agent_type);
          if (ev.type === SSE.DONE && ev.audio_b64) await Jarvis.avatar.playAudio(ev.audio_b64, ev.answer);
        } catch {}
      }
    } finally {
      clearTimeout(watchdog);
      reader.releaseLock();
    }
  }

  /**
   * SSE 이벤트 1건을 처리한다.
   * 
   * @param {Object} ev - 파싱된 이벤트 객체
   * @param {string} answer - 지금까지 누적된 응답 텍스트
   * @returns {Promise<string>} 갱신된 누적 응답
   */
  async function _handleEvent(ev, answer) {
    if (ev.type === SSE.TOKEN) {
      if (!perfFirstToken) { perfFirstToken = true; Jarvis.api.perfLog('chat first-token', perfT0); }
      const next = answer + ev.text;
      Jarvis.avatar.showBubble(next);
      return next;
    }
    if (ev.type === SSE.DONE) {
      Jarvis.api.perfLog('chat done (답변+TTS 완성)', perfT0);
      _setAgentBadge(ev.agent_type);
      const prev = Jarvis.state.get(Jarvis.KEYS.SESSION_ID);
      const isNew = !prev && !!ev.session_id;
      if (ev.session_id) Jarvis.state.set(Jarvis.KEYS.SESSION_ID, ev.session_id);
      if (isNew) window.electronAPI?.refreshSessions?.();
      if (ev.answer) Jarvis.avatar.showBubble(ev.answer);
      if (ev.audio_b64) await Jarvis.avatar.playAudio(ev.audio_b64, ev.answer);
      else Jarvis.avatar.stopSpeaking();
      return answer;
    }
    if (ev.type === SSE.STATUS) {
      Jarvis.avatar.showBubble(ev.text || MSG_STATUS);
      return answer;
    }
    if (ev.type === SSE.CONFIRM) {
      _showConfirm(ev);
      return answer;
    }
    if (ev.type === SSE.OPEN_URL) {
      window.electronAPI?.openExternal?.(ev.url);  // 검색 결과 등을 이 기기 브라우저로 (main이 스킴 검증)
      return answer;
    }
    if (ev.type === SSE.ERROR) {
      console.warn('[chat] 서버 오류 이벤트:', ev.message);  // 원문은 콘솔에만
      Jarvis.avatar.showBubble(MSG_ERROR);
      return answer;
    }
    return answer;
  }

  /**
   * 승인/거절 패널을 표시한다.
   * @param {Object} ev - confirm_required 이벤트 (action_id, preview, tool)
   * @returns {void}
   */
  function _showConfirm(ev) {
    pendingActionId = ev.action_id;
    if (!confirmPanel || !confirmPreview) return;
    confirmPreview.textContent = ev.preview || confirmDefaultMsg(ev.tool);
    confirmPanel.hidden = false;
  }

  /**
   * 승인/거절 패널을 숨기고 대기 액션을 초기화한다.
   * 
   * @returns {void}
   */
  function _hideConfirm() {
    if (confirmPanel) confirmPanel.hidden = true;
    pendingActionId = null;
  }

  /**
   * 대기 중인 confirm 액션을 승인/거절로 해소하고 후속 스트림을 소비한다.
   * 
   * @param {boolean} approved - 승인 여부
   * @returns {Promise<void>}
   */
  async function resolveConfirm(approved) {
    const actionId = pendingActionId;
    _hideConfirm();
    if (!actionId) return;

    Jarvis.state.set(Jarvis.KEYS.BUSY, true);
    abortCtrl = new AbortController();
    perfT0 = performance.now();
    perfFirstToken = false;
    try {
      const res = await fetch(Jarvis.api.chatConfirm, {
        method : HTTP_POST,
        headers: JSON_HEADERS,
        body   : JSON.stringify({ action_id: actionId, approved }),
        signal : abortCtrl.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await _consumeStream(res);
    } catch (e) {
      if (e.name !== ABORT_ERROR) {
        console.warn('[chat] confirm 실패:', e);
        Jarvis.avatar.showBubble(MSG_ERROR);
      }
    } finally {
      Jarvis.state.set(Jarvis.KEYS.BUSY, false);
      abortCtrl = null;
    }
  }

  // 승인/거절 버튼 바인딩 + 종료 정리
  const scope = Jarvis.dom.createScope();
  scope.on(Jarvis.dom.$id('btn-approve'), 'click', () => resolveConfirm(true));
  scope.on(Jarvis.dom.$id('btn-reject'), 'click', () => resolveConfirm(false));

  Jarvis.bus.on(Jarvis.EVENTS.TEARDOWN, () => {
    if (abortCtrl) { abortCtrl.abort(); abortCtrl = null; }
    scope.dispose();
  });

  return { send, resolveConfirm };
})();