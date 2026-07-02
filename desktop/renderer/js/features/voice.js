'use strict';

/**
 * @file 음성 입력 모듈 — STT 녹음 후 /voice 전송.
 *       트리거: F9 글로벌 단축키(voice-toggle IPC), 세션창 마이크 버튼(별도 창).
 */
window.Jarvis = window.Jarvis || {};

Jarvis.voice = (() => {
  const HTTP_POST = 'POST';
  const ABORT_ERROR = 'AbortError';
  const AUDIO_CONSTRAINTS = { audio: true };
  const MIME_WEBM = 'audio/webm';
  const FILE_NAME = 'audio.webm';
  const FIELD_FILE = 'file';
  const FIELD_SESSION = 'session_id';
  const VOICE_TIMEOUT_MS = 30000;
  const MSG_MIC_FAIL = '마이크에 접근할 수 없습니다.';
  const MSG_VOICE_FAIL = '음성 처리 오류가 발생했습니다.';

  let recorder = null;
  let chunks = [];

  /**
   * 녹음 상태에 따라 시작/정지를 토글한다.
   * 
   * @returns {void}
   */
  function toggle() {
    if (Jarvis.state.get(Jarvis.KEYS.RECORDING)) _stop();
    else                                         _start();
  }

  /**
   * 마이크 스트림을 열고 녹음을 시작한다.
   * 
   * @returns {Promise<void>}
   */
  async function _start() {
    Jarvis.avatar.interruptAudio();   // barge-in: 사용자가 말 걸면 캐릭터 발화 즉시 중단
    try {
      const stream = await navigator.mediaDevices.getUserMedia(AUDIO_CONSTRAINTS);
      chunks = [];
      recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
      recorder.onstop = _send;
      recorder.start();
      Jarvis.state.set(Jarvis.KEYS.RECORDING, true);
    } catch (e) {
      console.warn('[voice] 마이크 접근 실패:', e);   // 권한 거부 등 복구 가능
      Jarvis.avatar.showBubble(MSG_MIC_FAIL);
    }
  }

  /**
   * 녹음을 정지하고 트랙을 해제한다 (onstop → _send).
   * 
   * @returns {void}
   */
  function _stop() {
    if (!recorder || !Jarvis.state.get(Jarvis.KEYS.RECORDING)) return;
    recorder.stop();
    recorder.stream.getTracks().forEach((t) => t.stop());
    Jarvis.state.set(Jarvis.KEYS.RECORDING, false);
  }

  /**
   * 녹음 청크를 /voice로 전송하고 응답(텍스트·오디오)을 재생한다.
   * 
   * @returns {Promise<void>}
   */
  async function _send() {
    if (Jarvis.state.get(Jarvis.KEYS.BUSY)) return;
    Jarvis.state.set(Jarvis.KEYS.BUSY, true);

    try {
      const blob = new Blob(chunks, { type: MIME_WEBM });
      const form = new FormData();
      form.append(FIELD_FILE, blob, FILE_NAME);
      const sid = Jarvis.state.get(Jarvis.KEYS.SESSION_ID);
      if (sid) form.append(FIELD_SESSION, String(sid));

      const res = await Jarvis.api.fetchWithTimeout(Jarvis.api.voice, { method: HTTP_POST, body: form }, VOICE_TIMEOUT_MS);
      const data = await res.json();

      if (data.session_id) Jarvis.state.set(Jarvis.KEYS.SESSION_ID, data.session_id);
      if (data.answer)     Jarvis.avatar.showBubble(data.answer);
      if (data.audio_b64)  await Jarvis.avatar.playAudio(data.audio_b64, data.answer);
      else                 Jarvis.avatar.stopSpeaking();
    } catch (e) {
      if (e.name !== ABORT_ERROR) {
        console.warn('[voice] 전송 실패:', e);
        Jarvis.avatar.showBubble(MSG_VOICE_FAIL);
      }
    } finally {
      Jarvis.state.set(Jarvis.KEYS.BUSY, false);
    }
  }

  // 종료 시 녹음 중이면 스트림 해제
  Jarvis.bus.on(Jarvis.EVENTS.TEARDOWN, () => {
    if (recorder && Jarvis.state.get(Jarvis.KEYS.RECORDING)) {
      try {
        recorder.stop();
        recorder.stream.getTracks().forEach((t) => t.stop());
      } catch {}
    }
  });

  // F9 글로벌 단축키
  window.electronAPI?.onVoiceToggle?.(toggle);

  return { toggle };
})();