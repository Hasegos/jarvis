'use strict';

/**
 * @file 음성 입력 모듈 — 마이크 녹음 후 /voice 전송.
 */
window.JarvisWeb = window.JarvisWeb || {};

JarvisWeb.voice = (() => {
  const HTTP_POST = 'POST';
  const AUDIO_CONSTRAINTS = { audio: true };
  const MIME_WEBM = 'audio/webm';
  const FILE_NAME = 'audio.webm';
  const FIELD_FILE = 'file';
  const FIELD_SESSION = 'session_id';
  const VOICE_TIMEOUT_MS = 65000;
  const MSG_ERROR = '오류가 발생했습니다.';
  const MSG_PENDING = '...';
  const MSG_MIC_FAIL = '마이크를 사용할 수 없습니다. (HTTPS 필요할 수 있음)';

  let recorder = null;
  let chunks = [];

  /**
   * 녹음 상태에 따라 시작/정지를 토글한다.
   * 
   * @returns {Promise<void>}
   */
  async function toggle() {
    const { ui, state, KEYS } = JarvisWeb;
    if (state.get(KEYS.RECORDING)) {
      recorder.stop();
      recorder.stream.getTracks().forEach((t) => t.stop());
      state.set(KEYS.RECORDING, false);
      ui.setMicRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia(AUDIO_CONSTRAINTS);
      chunks = [];
      recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
      recorder.onstop = _send;
      recorder.start();
      state.set(KEYS.RECORDING, true);
      ui.setMicRecording(true);
    } catch (e) {
      console.warn('[web/voice] 마이크 실패:', e);
      ui.addMsg(ui.ROLE.STATUS, MSG_MIC_FAIL);
    }
  }

  /**
   * 녹음 청크를 /voice로 보내고 응답을 표시·재생한다.
   * 
   * @returns {Promise<void>}
   */
  async function _send() {
    const { ui, state, api, KEYS } = JarvisWeb;
    if (state.get(KEYS.BUSY)) return;
    state.set(KEYS.BUSY, true);
    ui.setBusy(true);
    const bubble = ui.addMsg(ui.ROLE.BOT, MSG_PENDING);
    try {
      const form = new FormData();
      form.append(FIELD_FILE, new Blob(chunks, { type: MIME_WEBM }), FILE_NAME);
      const sid = state.get(KEYS.SESSION_ID);
      if (sid) form.append(FIELD_SESSION, String(sid));

      const ctrl = new AbortController();
      const tid = setTimeout(() => ctrl.abort(), VOICE_TIMEOUT_MS);
      const res = await fetch(`${api.BASE}/voice`, {
        method : HTTP_POST,
        headers: api.headers(false),
        body   : form,
        signal : ctrl.signal,
      });
      clearTimeout(tid);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.session_id) state.set(KEYS.SESSION_ID, data.session_id);
      if (data.user_text) ui.addMsg(ui.ROLE.USER, data.user_text);
      bubble.textContent = data.answer || MSG_ERROR;
      api.playAudio(data.audio_b64);
    } catch (e) {
      console.warn('[web/voice] 전송 실패:', e);
      bubble.textContent = MSG_ERROR;
    } finally {
      state.set(KEYS.BUSY, false);
      ui.setBusy(false);
    }
  }

  return { toggle };
})();