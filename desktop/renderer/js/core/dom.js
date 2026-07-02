'use strict';

/**
 * @file DOM 헬퍼 + AbortController 기반 리스너 스코프.
 */
window.Jarvis = window.Jarvis || {};

/**
 * @typedef {Object} ListenerScope
 * @property {AbortSignal} signal - 등록 리스너에 부여되는 취소 시그널
 * @property {(target: EventTarget, type: string, handler: Function, opts?: Object) => void} on - 리스너 등록
 * @property {() => void} dispose - 등록된 리스너 일괄 해제
 */

Jarvis.dom = (() => {
  /**
   * 첫 번째 매칭 요소를 반환한다 (querySelector).
   * 
   * @param {string} sel - CSS 셀렉터
   * @param {ParentNode} [root] - 탐색 기준 (기본 document)
   * @returns {Element|null}
   */
  const $ = (sel, root = document) => root.querySelector(sel);

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
   * @returns {ListenerScope}
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

  return { $, $id, createScope };
})();