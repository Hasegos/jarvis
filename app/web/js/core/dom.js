'use strict';

/**
 * @file DOM 헬퍼 + AbortController 기반 리스너 스코프.
 */
window.JarvisWeb = window.JarvisWeb || {};

JarvisWeb.dom = (() => {
  /**
   * id로 요소를 반환한다.
   * 
   * @param {string} id - 요소 id
   * @returns {HTMLElement|null}
   */
  const $id = (id) => document.getElementById(id);

  /**
   * 리스너 스코프를 생성한다. dispose() 시 등록된 모든 리스너가 해제된다.
   * 
   * @returns {{signal: AbortSignal, on: Function, dispose: Function}}
   */
  function createScope() {
    const ac = new AbortController();
    return {
      signal: ac.signal,
      on(target, type, handler, opts = {}) {
        target.addEventListener(type, handler, { ...opts, signal: ac.signal });
      },
      dispose() { ac.abort(); },
    };
  }

  return { $id, createScope };
})();