'use strict';

/**
 * @file EventBus — 창 내부 모듈 간 pub/sub 통신
 */
window.Jarvis = window.Jarvis || {};

/** @constant {Readonly<Object>} 크로스 모듈 이벤트명 (매직 문자열 방지) */
Jarvis.EVENTS = Object.freeze({
  TEARDOWN: 'app:teardown',
  DRAG    : 'interact:drag',   // payload: boolean (드래그 시작/종료)
});

Jarvis.bus = (() => {
  /** @type {Map<string, Set<Function>>} 이벤트 → 핸들러 집합 */
  const handlers = new Map();

  /**
   * 이벤트를 구독한다.
   * 
   * @param {string} event - 이벤트명
   * @param {Function} fn - 핸들러
   * @returns {Function} 호출 시 구독을 해제하는 함수
   */
  function on(event, fn) {
    if (!handlers.has(event)) handlers.set(event, new Set());
    handlers.get(event).add(fn);
    return () => off(event, fn);
  }

  /**
   * 이벤트 구독을 해제한다.
   * 
   * @param {string} event - 이벤트명
   * @param {Function} fn - 제거할 핸들러
   * @returns {void}
   */
  function off(event, fn) {
    handlers.get(event)?.delete(fn);
  }

  /**
   * 이벤트를 발행한다. 개별 핸들러 예외는 격리되어 다른 핸들러에 전파되지 않는다.
   * 
   * @param {string} event - 이벤트명
   * @param {*} [payload] - 핸들러에 전달할 값
   * @returns {void}
   */
  function emit(event, payload) {
    handlers.get(event)?.forEach((fn) => {
      try { fn(payload); }
      catch (e) { console.error(`[bus:${event}] 핸들러 오류:`, e); }
    });
  }

  return { on, off, emit };
})();