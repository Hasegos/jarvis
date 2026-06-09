/**
 * 채팅 입력 UI 보조
 */
(function () {
  'use strict';

  const CSS_MSG_ITEM = 'chat-messages__item';

  /**
   * 1. textarea 자동 높이 조절
   * 
   * @returns 
   */
  function initTextarea() {
    const ta = document.getElementById('textInput');
    if (!ta) return;

    function resize() {
      ta.style.height = 'auto';
      ta.style.height = Math.min(ta.scrollHeight, 180) + 'px';
    }

    ta.addEventListener('input', resize);

    const orig = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
    Object.defineProperty(ta, 'value', {
      get() { return orig.get.call(this); },
      set(v) { orig.set.call(this, v); resize(); },
    });
  }

  /**
   * 2. 문장 단위 줄바꿈
   * 
   * @param {*} node 
   * @returns 
   */
  function formatSentences(node) {
    if (!node.classList || !node.classList.contains(CSS_MSG_ITEM)) return;

    const raw = node.textContent || '';

    if (raw.includes('\n')) return;

    const formatted = raw
      .replace(/(?<!\d)([.!?。]+)\s+(?!\d)/g, '$1\n')
      .trimEnd();

    if (formatted !== raw) node.textContent = formatted;
  }

  function initSentenceBreaks() {
    const box = document.getElementById('chatBox');
    if (!box) { setTimeout(initSentenceBreaks, 300); return; }

    new MutationObserver(muts => {
      muts.forEach(m => m.addedNodes.forEach(formatSentences));
    }).observe(box, { childList: true });
  }

  /**
   * 3. 초기화
   * 
   * @returns 
   */
  function init() {
    initTextarea();
    initSentenceBreaks();
  }

  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else{
    init();
  } 
})();