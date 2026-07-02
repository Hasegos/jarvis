'use strict';

/**
 * @file 단일 상태 저장소 — 공유 전역(sessionId·busy·recording)을 통합.
 *       값 변경 시 bus로 'state:<key>' 이벤트를 발행한다 (단방향 데이터 흐름).
 */
window.Jarvis = window.Jarvis || {};

/** @constant {Readonly<Object>} 상태 키 (매직 문자열 방지) */
Jarvis.KEYS = Object.freeze({
  SESSION_ID: 'sessionId',
  BUSY      : 'busy',
  RECORDING : 'recording',
});

Jarvis.state = (() => {
  const STATE_EVENT_PREFIX = 'state:';

  /** @type {Object<string, *>} 내부 상태 저장소 */
  const store = {
    [Jarvis.KEYS.SESSION_ID]: null,   // 현재 세션 id
    [Jarvis.KEYS.BUSY]      : false,  // LLM 응답/음성 처리 중
    [Jarvis.KEYS.RECORDING] : false,  // 마이크 녹음 중
  };

  /**
   * 상태 값을 읽는다.
   * 
   * @param {string} key - 상태 키 (Jarvis.KEYS)
   * @returns {*} 현재 값
   */
  function get(key) {
    return store[key];
  }

  /**
   * 상태 값을 설정한다. 값이 실제로 바뀐 경우에만 'state:<key>' 이벤트를 발행한다.
   * 
   * @param {string} key - 상태 키 (Jarvis.KEYS)
   * @param {*} val - 새 값
   * @returns {void}
   */
  function set(key, val) {
    if (store[key] === val) return;
    store[key] = val;
    Jarvis.bus.emit(`${STATE_EVENT_PREFIX}${key}`, val);
  }

  return { get, set };
})();