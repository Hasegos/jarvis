// ─────────────────────────────────────────────────────────
// chatInput.js  —  채팅 UI 보조
//   1. textarea 자동 높이 조절
//   2. 메시지 문장 단위 줄바꿈 (표시 전용, DB/TTS 무영향)
// ─────────────────────────────────────────────────────────
(function () {
    'use strict';

    // ─────────────────────────────────────
    // 1. textarea 자동 높이 조절
    // ─────────────────────────────────────
    function initTextarea() {
        const ta = document.getElementById('textInput');
        if (!ta) return;

        function resize() {
            ta.style.height = 'auto';
            ta.style.height = Math.min(ta.scrollHeight, 180) + 'px';
        }

        ta.addEventListener('input', resize);

        // chat.js가 ta.value = '' 로 초기화할 때 input 이벤트 미발생
        // → value setter를 가로채서 resize() 를 같이 호출한다
        const orig = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
        Object.defineProperty(ta, 'value', {
            get() { return orig.get.call(this); },
            set(v) { orig.set.call(this, v); resize(); },
        });
    }


    // ─────────────────────────────────────
    // 2. 문장 단위 줄바꿈
    // ─────────────────────────────────────
    // LLM 응답이 긴 한 단락으로 오면 읽기 어렵다.
    // 마침표·물음표·느낌표 뒤 공백을 줄바꿈으로 바꿔 문장을 분리한다.
    //
    // 규칙:
    //  - [.!?。]+ 뒤에 공백이 오면 줄바꿈으로 교체
    //  - 소수점(숫자.숫자), 약어 "etc." 등은 완벽 제외 어려우나
    //    한국어 AI 답변 특성상 오탐 거의 없음
    //  - LLM이 이미 \n 을 넣었으면(코드블록 등) 그대로 둔다
    function formatSentences(node) {
        if (!node.classList || !node.classList.contains('message')) return;

        const raw = node.textContent || '';

        // 이미 줄바꿈 있으면 LLM이 직접 구분한 것 → 건드리지 않음
        if (raw.includes('\n')) return;

        // 소수점 제외: \d.\d 패턴은 건너뜀
        // 일반 문장 끝: [.!?。]+ 뒤 공백 1개 이상
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


    // ─────────────────────────────────────
    // 3. 초기화
    // ─────────────────────────────────────
    function init() {
        initTextarea();
        initSentenceBreaks();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();