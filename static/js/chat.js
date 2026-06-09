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
 * @param {*} role 
 * @param {*} text 
 */
function addMessage(role, text) {
  const div       = document.createElement('div');
  div.className   = `${CSS.MSG_ITEM} ${role === 'user' ? CSS.MSG_USER : CSS.MSG_ASSISTANT}`;
  div.textContent = text;   // textContent → XSS 방지
  dom.chatBox.appendChild(div);
  dom.chatBox.scrollTop = dom.chatBox.scrollHeight;
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
 * 5. 텍스트 전송
 * 
 * @returns 
 */
async function sendText() {
  const message = dom.textInput.value.trim();
  if (!message) return;

  dom.textInput.value = '';
  addMessage('user', message);
  setLoading(true);

  try {
    const data = await apiFetch(API_ENDPOINTS.chat, {
      method: 'POST',
      body  : JSON.stringify({ session_id: currentSessionId, message }),
    });

    updateSessionId(data.session_id);
    addMessage('assistant', data.answer);
    if (data.audio_b64) await playAudio(data.audio_b64);

  } catch (e) {
    const msg = e instanceof ApiError
      ? `서버 오류 (${e.status}). 다시 시도해 주세요.`
      : '연결 오류가 발생했습니다. 다시 시도해 주세요.';
    addMessage('assistant', msg);
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
 * @param {*} b64 
 */
async function playAudio(b64) {
  const bytes = new Uint8Array(atob(b64).split('').map(c => c.charCodeAt(0)));
  const url   = URL.createObjectURL(new Blob([bytes], { type: 'audio/mpeg' }));
  const audio = new Audio(url);
  audio.onended = () => URL.revokeObjectURL(url);
  await audio.play();
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