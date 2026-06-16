/**
 * JARVIS 홀로그램 — 채팅
 */
'use strict';
window.JARVIS = window.JARVIS || {};

(function (J) {

  function scrollBottom() { J.dom.messages.scrollTop = J.dom.messages.scrollHeight; }
  function clearConfirmEmphasis() { J.dom.hudPanel.classList.remove('hud-panel--confirm'); }

  /**
   * 1. 메시지 렌더
   */
  J.clearMessages = function () { J.dom.messages.innerHTML = ''; };

  /**
   * 메시지 추가
   *
   * @param {string} role - 메시지 발신자 ('user' | 'assistant')
   * @param {string} text - 메시지 내용
   * @returns {HTMLElement} 메시지 본문 요소 (스트리밍 시 텍스트 갱신용)
   */
  J.addMessage = function (role, text) {
    const wrap = document.createElement('div');
    wrap.className = `msg msg--${role}`;
    const r = document.createElement('div');
    r.className = 'msg__role';
    r.textContent = role === 'user' ? '아이언 님' : 'JARVIS';
    const b = document.createElement('div');
    b.className = 'msg__body';
    b.textContent = text;

    const copy = document.createElement('button');
    copy.type = 'button';
    copy.className = 'msg__copy';
    copy.title = '복사';
    copy.textContent = '⧉';
    copy.addEventListener('click', () => {
      navigator.clipboard.writeText(b.textContent || '').then(() => {
        copy.textContent = '✓';
        copy.classList.add('msg__copy--done');
        setTimeout(() => {
          copy.textContent = '⧉';
          copy.classList.remove('msg__copy--done');
        }, 1200);
      }).catch(e => console.error('복사 실패', e));
    });

    wrap.append(r, b, copy);
    J.dom.messages.appendChild(wrap);
    scrollBottom();
    if (J.state.panelHidden && role === 'assistant') J.dom.fabDot.hidden = false;
    return b;
  };

  /**
   * 2. SSE 스트림 소비
   *
   * token/status/confirm_required/done/error 이벤트를 처리하며
   * 구체 상태 전환 및 도구 색상 분기를 수행한다.
   *
   * @param {Response} res - fetch 응답 (SSE 스트림)
   * @param {HTMLElement} bubble - 답변이 렌더될 메시지 본문 요소
   */
  J.consumeStream = async function (res, bubble) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '', answerText = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      let idx;
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const line = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 2);
        if (!line.startsWith('data:')) continue;
        const ev = JSON.parse(line.slice(5));

        if (ev.type === 'token') {
          answerText += ev.text;
          bubble.textContent = answerText;
          scrollBottom();
        } else if (ev.type === 'status') {
          J.setToolColor(ev.tool || ev.text);
          J.setSphereState('tool', ev.text);
          if (!answerText) bubble.textContent = `⏳ ${ev.text}`;
        } else if (ev.type === 'confirm_required') {
          J.renderConfirm(bubble, ev);
        } else if (ev.type === 'done') {
          if (ev.session_id) J.state.currentSessionId = ev.session_id;
          bubble.textContent = ev.answer;
          scrollBottom();
          clearConfirmEmphasis();
          if (ev.audio_b64) J.playAudio(ev.audio_b64);
          else J.setSphereState('idle');
        } else if (ev.type === 'error') {
          bubble.textContent = `오류: ${ev.message}`;
          clearConfirmEmphasis();
          J.setSphereState('idle');
        }
      }
    }
  };

  /**
   * 3. confirm 버튼 / 패널 강조
   *
   * destructive 도구의 실행 미리보기와 실행/취소 버튼을 렌더한다.
   * 패널이 접혀 있으면 자동으로 펼친다.
   *
   * @param {HTMLElement} bubble - 버튼이 렌더될 메시지 본문 요소
   * @param {Object} ev - confirm_required SSE 이벤트 ({action_id, preview})
   */
  J.renderConfirm = function (bubble, ev) {
    J.dom.hudPanel.classList.add('hud-panel--confirm');
    if (J.state.panelHidden) J.showPanel();
    bubble.textContent = '';

    const box = document.createElement('div');
    box.className = 'confirm-box';
    const desc = document.createElement('div');
    desc.className = 'confirm-box__preview';
    desc.textContent = `⚠️ ${ev.preview}`;
    box.appendChild(desc);

    const mk = (label, approved, cls) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `confirm-box__btn ${cls}`;
      btn.textContent = label;
      btn.addEventListener('click', () => {
        box.querySelectorAll('button').forEach(b => (b.disabled = true));
        J.submitConfirm(ev.action_id, approved, bubble);
      });
      return btn;
    };
    box.appendChild(mk('실행', true, 'confirm-box__btn--yes'));
    box.appendChild(mk('취소', false, 'confirm-box__btn--no'));
    bubble.appendChild(box);
    scrollBottom();
  };

  /**
   * confirm 제출
   *
   * 보류된 작업을 승인/거부하고 이어지는 스트림을 소비한다.
   *
   * @param {string} actionId - 보류 작업 식별자
   * @param {boolean} approved - true면 실행, false면 취소
   * @param {HTMLElement} bubble - 결과가 렌더될 메시지 본문 요소
   */
  J.submitConfirm = async function (actionId, approved, bubble) {
    J.setBusy(true);
    bubble.textContent = '⏳ 처리 중…';
    try {
      const res = await fetch(API_ENDPOINTS.chatConfirm, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_id: actionId, approved }),
      });
      if (!res.ok) throw new ApiError(res.status, await res.text());
      await J.consumeStream(res, bubble);
    } catch (e) {
      bubble.textContent = '연결 오류가 발생했습니다.';
      clearConfirmEmphasis();
      J.setSphereState('idle');
      console.error('submitConfirm 실패', e);
    } finally {
      J.setBusy(false);
    }
  };

  /**
   * 4. 텍스트 전송
   *
   * 입력/전송 UI 잠금 상태를 전환한다.
   *
   * @param {boolean} b - true면 잠금(전송 중), false면 해제
   */
  J.setBusy = function (b) {
    J.state.busy = b;
    J.dom.textInput.disabled = b;
    J.dom.btnSend.disabled = b;
  };

  /**
   * textarea 높이 자동 조절
   *
   * 입력 내용에 따라 높이를 늘리고, INPUT_MAX_H 초과 시 스크롤한다.
   */
  J.autoResizeInput = function () {
    const el = J.dom.textInput;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, J.const.INPUT_MAX_H) + 'px';
  };

  /**
   * 채팅 메시지 전송
   *
   * 입력창 텍스트를 SSE 스트리밍으로 전송하고 응답을 실시간 렌더한다.
   * busy 상태이거나 빈 입력이면 무시한다.
   */
  J.sendText = async function () {
    const message = J.dom.textInput.value.trim();
    if (!message || J.state.busy) return;

    // GPS 갱신
    await J.updateLocation();

    J.dom.textInput.value = '';
    J.autoResizeInput();
    J.addMessage('user', message);
    const bubble = J.addMessage('assistant', '');
    J.setBusy(true);
    try {
      const res = await fetch(API_ENDPOINTS.chatStream, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: J.state.currentSessionId, message }),
      });
      if (!res.ok) throw new ApiError(res.status, await res.text());
      await J.consumeStream(res, bubble);
    } catch (e) {
      bubble.textContent = '연결 오류가 발생했습니다.';
      J.setSphereState('idle');
      console.error('sendText 실패', e);
    } finally {
      J.setBusy(false);
    }
  };

})(window.JARVIS);