'use strict';

/**
 * @file 캐릭터창 부트스트랩 — 모듈 초기화 순서 조율 + IPC 연결 + 생명주기 관리.
 */
window.Jarvis = window.Jarvis || {};

(async function bootstrap() {
  const GREETING = '안녕하세요, 자비스입니다.';
  const GREETING_TIMEOUT_MS = 10000;
  const HTTP_POST = 'POST';
  const JSON_HEADERS = { 'Content-Type': 'application/json' };

  window.addEventListener('beforeunload', () => Jarvis.bus.emit(Jarvis.EVENTS.TEARDOWN), { once: true });

  await Jarvis.avatar.init();

  // IPC: 세션창 → 캐릭터창 (텍스트 + 선택 이미지들)
  window.electronAPI?.onChatText?.((payload) => Jarvis.chat.send(payload?.text ?? '', payload?.images_b64 ?? []));
  window.electronAPI?.onSwitchSession?.((id) => {
    Jarvis.state.set(Jarvis.KEYS.SESSION_ID, id);
    Jarvis.avatar.hideBubble();
  });

  Jarvis.ui.init();
  Jarvis.screen.start();   // 화면 인식 자동 시작 (전체 화면, 시간 간격 캡처)
  Jarvis.roam.start();     // 자율 이동 시작 (idle 시 배회)
  await greet();

  /**
   * 부팅 인사 TTS를 요청해 재생한다. 백엔드 미기동 시 조용히 무시(복구 가능).
   * 
   * @returns {Promise<void>}
   */
  async function greet() {
    try {
      const res = await Jarvis.api.fetchWithTimeout(Jarvis.api.tts, {
        method : HTTP_POST,
        headers: JSON_HEADERS,
        body   : JSON.stringify({ text: GREETING }),
      }, GREETING_TIMEOUT_MS);
      const data = await res.json();
      if (data.audio_b64) await Jarvis.avatar.playAudio(data.audio_b64, GREETING);
    } catch (e) {
      console.warn('[app] 부팅 인사 실패:', e);
    }
  }
})();