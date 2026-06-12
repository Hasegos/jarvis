/**
 * 채팅 페이지
 */
'use strict';

/**
 * 1. 상수 & 상태
 */
const params           = new URLSearchParams(window.location.search);
const rawId            = params.get('id');
let   currentSessionId = (rawId && rawId !== 'new') ? parseInt(rawId, 10) : null;

// BEM 클래스명 상수 (CSS와 단일 소스)
const CSS = Object.freeze({
  MSG_ITEM      : 'chat-messages__item',
  MSG_USER      : 'chat-messages__item--user',
  MSG_ASSISTANT : 'chat-messages__item--assistant',
  VOICE_REC     : 'chat-input__voice-btn--recording',
});

/**
 * 2. DOM 참조 캐시 — init 1회만 조회
 */
const dom = {};

function initDom() {
  dom.chatBox      = document.getElementById('chatBox');
  dom.sendBtn      = document.getElementById('sendBtn');
  dom.voiceBtn     = document.getElementById('voiceBtn');
  dom.voiceBtnText = document.getElementById('voiceBtnText');
  dom.voiceStatus  = document.getElementById('voiceStatus');
  dom.textInput    = document.getElementById('textInput');
  dom.sessionLabel = document.getElementById('chatSessionLabel');
}

/**
 * 3. UI 헬퍼
 *
 * @param {string} role - 'user' 또는 'assistant'
 * @param {string} text - 표시할 텍스트
 * @returns {HTMLDivElement} 생성된 말풍선 요소 (스트리밍 갱신용)
 */
/**
 * 채팅 영역이 바닥 근처면 맨 아래로 스크롤한다.
 * 스트리밍 중 매 토큰마다 강제 스크롤하면 출렁이므로, 사용자가
 * 위로 올려둔 경우엔 건드리지 않는다.
 */
function scrollToBottomIfNear() {
  const box = dom.chatBox;
  const near = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
  if (near) box.scrollTop = box.scrollHeight;
}

function addMessage(role, text) {
  const div       = document.createElement('div');
  div.className   = `${CSS.MSG_ITEM} ${role === 'user' ? CSS.MSG_USER : CSS.MSG_ASSISTANT}`;
  div.textContent = text;   // textContent → XSS 방지
  dom.chatBox.appendChild(div);
  dom.chatBox.scrollTop = dom.chatBox.scrollHeight;
  return div;               // 스트리밍 중 textContent 를 갱신하기 위해 요소를 반환
}

/**
 * 전송·음성 버튼과 입력창의 비활성화 상태를 설정합니다.
 * 
 * @param {boolean} on - true 이면 비활성화 (요청 중), false 이면 활성화
 */
function setLoading(on) {
  dom.sendBtn.disabled   = on;
  dom.voiceBtn.disabled  = on;
  dom.textInput.disabled = on;
}

/**
 * 헤더의 세션 레이블 텍스트를 업데이트합니다.
 * 
 * @param {string} text - 표시할 레이블 문자열
 */
function setSessionLabel(text) {
  if (dom.sessionLabel) dom.sessionLabel.textContent = text;
}

/**
 * 현재 세션 ID를 갱신하고 URL·레이블을 동기화합니다.
 * 새 채팅에서 첫 응답 후 서버가 발급한 ID를 반영할 때 사용합니다.
 * 
 * @param {number} newId - 서버에서 받은 세션 ID
 * @returns {void}
 */
function updateSessionId(newId) {
  if (!newId || newId === currentSessionId) return;
  currentSessionId = newId;
  history.replaceState(null, '', `/chat?id=${newId}`);
  setSessionLabel(`SESSION #${newId}`);
}

/**
 * 4. 세션 로드 (기존 세션 메시지 복원)
 * 
 * @returns 
 */
async function loadSession() {
  if (!currentSessionId) {
    setSessionLabel('NEW SESSION');
    return;
  }

  setSessionLabel(`SESSION #${currentSessionId}`);

  try {
    const [messages, sessions] = await Promise.all([
      apiFetch(API_ENDPOINTS.messages(currentSessionId)),
      apiFetch(API_ENDPOINTS.sessions),
    ]);

    messages.forEach(m => addMessage(m.role, m.content));

    const found = sessions.find(s => s.session_id === currentSessionId);
    if (found?.summary) {
      setSessionLabel(`${found.summary} · #${currentSessionId}`);
    }
  } catch (e) {
    console.error('세션 복원 실패', e);
  }
}

/**
 * 5. 텍스트 전송 (SSE 스트리밍)
 *
 * 토큰이 도착하는 대로 말풍선에 실시간 표시하고,
 * 도구 실행 중에는 상태 문구를 보여준다.
 */
async function sendText() {
  const message = dom.textInput.value.trim();
  if (!message) return;

  dom.textInput.value = '';
  addMessage('user', message);
  setLoading(true);

  const bubble = addMessage('assistant', '');
  dom.chatBox.scrollTop = dom.chatBox.scrollHeight;  // 말풍선 생성 직후 바닥 고정
  let answerText = '';

  try {
    const res = await fetch(API_ENDPOINTS.chatStream, {
      method : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body   : JSON.stringify({ session_id: currentSessionId, message }),
    });
    if (!res.ok) throw new ApiError(res.status, await res.text());

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

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
          scrollToBottomIfNear();
        } else if (ev.type === 'status') {
          if (!answerText) bubble.textContent = `⏳ ${ev.text}`;
          if (ev.audio_b64) playAudio(ev.audio_b64);
        } else if (ev.type === 'done') {
          updateSessionId(ev.session_id);
          bubble.textContent = ev.answer;
          scrollToBottomIfNear();
          if (ev.audio_b64) playAudio(ev.audio_b64);
        } else if (ev.type === 'error') {
          bubble.textContent = `오류: ${ev.message}`;
        }
      }
    }
  } catch (e) {
    const msg = e instanceof ApiError
      ? `서버 오류 (${e.status}). 다시 시도해 주세요.`
      : '연결 오류가 발생했습니다. 다시 시도해 주세요.';
    bubble.textContent = msg;
    console.error('sendText 실패:', e);
  } finally {
    setLoading(false);
  }
}

/**
 * 6. 음성 녹음
 */
let mediaRecorder = null;
let isRecording   = false;

/**
 * 음성 녹음 토글 — 녹음 중이면 중지, 아니면 시작합니다.
 */
async function toggleVoice() {
  if (isRecording) stopRecording();
  else             await startRecording();
}

/**
 * 마이크 스트림을 열고 MediaRecorder 녹음을 시작합니다.
 * 녹음 종료 시 자동으로 sendVoice 를 호출합니다.
 */
async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const chunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = e => chunks.push(e.data);

    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      await sendVoice(new Blob(chunks, { type: mediaRecorder.mimeType }));
    };

    mediaRecorder.start();
    isRecording = true;
    dom.voiceBtn.classList.add(CSS.VOICE_REC);
    dom.voiceBtnText.textContent = '⏹ 녹음 중지';
    dom.voiceStatus.textContent  = '녹음 중...';
  } catch (e) {
    dom.voiceStatus.textContent = '마이크 권한이 필요합니다.';
    console.error('마이크 접근 실패:', e);
  }
}

/**
 * 진행 중인 녹음을 중지합니다.
 * MediaRecorder.stop() 호출 → onstop 핸들러에서 sendVoice 가 이어받습니다.
 * 
 * @returns {void}
 */
function stopRecording() {
  if (!mediaRecorder || !isRecording) return;
  mediaRecorder.stop();
  isRecording = false;
  dom.voiceBtn.classList.remove(CSS.VOICE_REC);
  dom.voiceBtnText.textContent = '🎤 음성 입력';
  dom.voiceStatus.textContent  = '처리 중...';
}

/**
 * 녹음된 오디오 Blob을 서버에 전송하고 응답을 화면에 표시합니다.
 * 
 * @param {Blob} blob - MediaRecorder가 생성한 오디오 Blob
 */
async function sendVoice(blob) {
  setLoading(true);
  try {
    const ext  = blob.type.includes('webm') ? 'webm' : 'ogg';
    const form = new FormData();
    form.append('file', blob, `audio.${ext}`);
    if (currentSessionId) form.append('session_id', String(currentSessionId));

    const data = await apiFetch(API_ENDPOINTS.voice, { method: 'POST', body: form });

    updateSessionId(data.session_id);
    if (data.user_text) addMessage('user',      data.user_text);
    if (data.answer)    addMessage('assistant', data.answer);
    if (data.audio_b64) await playAudio(data.audio_b64);

  } catch (e) {
    const msg = e instanceof ApiError
      ? `음성 처리 오류 (${e.status}). 다시 시도해 주세요.`
      : '음성 연결 오류가 발생했습니다.';
    addMessage('assistant', msg);
    console.error('sendVoice 실패:', e);
  } finally {
    setLoading(false);
    dom.voiceStatus.textContent = '';
  }
}

/**
 * 7. 오디오 재생
 * 
 * @param {string} b64 - base64 인코딩된 MP3 데이터
 */
async function playAudio(b64) {
  let url;
  try {
    const bytes = new Uint8Array(atob(b64).split('').map(c => c.charCodeAt(0)));
    url = URL.createObjectURL(new Blob([bytes], { type: 'audio/mpeg' }));
  } catch (e) {
    console.error('오디오 디코딩 실패:', e);
    return;
  }

  const audio = new Audio(url);
  audio.onended = () => URL.revokeObjectURL(url);

  try {
    await audio.play();
  } catch (e) {
    URL.revokeObjectURL(url);
    console.error('오디오 재생 실패:', e);
  }
}

/**
 * 8. 이벤트 바인딩
 */
function bindEvents() {
  dom.sendBtn.addEventListener('click', sendText);
  dom.voiceBtn.addEventListener('click', toggleVoice);
  dom.textInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendText();
    }
  });
}

/**
 * 9. 초기화
 */
function init() {
  initDom();
  bindEvents();
  loadSession();
  dom.textInput.focus();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}