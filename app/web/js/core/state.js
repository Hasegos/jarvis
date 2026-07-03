'use strict';

/**
 * @file 단일 상태 저장소 — 세션·처리중·녹음 상태. 공개: JarvisWeb.state
 */
window.JarvisWeb = window.JarvisWeb || {};

/** @constant {Readonly<Object>} 상태 키 */
JarvisWeb.KEYS = Object.freeze({
  SESSION_ID: 'sessionId',
  BUSY      : 'busy',
  RECORDING : 'recording',
});

JarvisWeb.state = (() => {
  /** @type {Object<string, *>} 내부 저장소 */
  const store = {
    [JarvisWeb.KEYS.SESSION_ID]: null,
    [JarvisWeb.KEYS.BUSY]      : false,
    [JarvisWeb.KEYS.RECORDING] : false,
  };

  /**
   * 상태 값을 읽는다.
   * 
   * @param {string} key - JarvisWeb.KEYS
   * @returns {*}
   */
  function get(key) {
    return store[key];
  }

  /**
   * 상태 값을 설정한다.
   * 
   * @param {string} key - JarvisWeb.KEYS
   * @param {*} val - 새 값
   * @returns {void}
   */
  function set(key, val) {
    store[key] = val;
  }

  return { get, set };
})();