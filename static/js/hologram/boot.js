/**
 * JARVIS 홀로그램 — 부팅 시퀀스
 */
'use strict';
window.JARVIS = window.JARVIS || {};

(function (J) {

  /**
   * 한 글자씩 타이핑 애니메이션
   *
   * @param {HTMLElement} el - 텍스트가 표시될 요소
   * @param {string} text - 타이핑할 문자열
   * @param {number} delay - 글자 간 지연 시간 (ms)
   * @returns {Promise<void>} 타이핑 완료 시 resolve
   */
  function typeText(el, text, delay) {
    return new Promise(res => {
      let i = 0;
      el.textContent = '';
      const tick = () => {
        el.textContent += text[i++];
        if (i < text.length) setTimeout(tick, delay);
        else res();
      };
      tick();
    });
  }

  /**
   * 파티클 수렴 진행도(0→1)를 J.three에 기록
   *
   * 흩어진 파티클이 구체로 모이는 부팅 애니메이션을 구동한다.
   *
   * @param {number} ms - 수렴 애니메이션 총 시간 (ms)
   * @returns {Promise<void>} 수렴 완료 시 resolve
   */
  function animateBoot(ms) {
    return new Promise(res => {
      J.three.booting = true;
      const t0 = performance.now();
      const tick = () => {
        J.three.bootProgress = Math.min(1, (performance.now() - t0) / ms);
        if (J.three.bootProgress < 1) requestAnimationFrame(tick);
        else { J.three.booting = false; res(); }
      };
      tick();
    });
  }

  /**
   * 인사 TTS 재생
   *
   * 부팅 클릭이 브라우저 오디오를 언락한 뒤 호출된다.
   * TTS 실패해도 부팅 자체는 정상 완료된다.
   */
  async function greet() {
    try {
      const data = await apiFetch(API_ENDPOINTS.tts, {
        method: 'POST', body: JSON.stringify({ text: J.const.GREETING }),
      });
      if (data.audio_b64) J.playAudio(data.audio_b64);
    } catch (e) {
      console.error('인사 TTS 실패', e);
    }
  }

  /**
   * 부팅 시퀀스 실행
   *
   * 타이핑("J.A.R.V.I.S") → 파티클 수렴(2.6초) → 오버레이 페이드아웃
   * → 채팅 패널 등장 → 최신 세션 로드 → 인사 TTS.
   */
  J.startBoot = async function () {
    const d = J.dom;
    d.boot.classList.add('boot--started');
    await typeText(d.bootTitle, 'J.A.R.V.I.S', 130);
    d.boot.classList.add('boot--typed');
    d.bootStatus.textContent = '시스템 초기화 중…';

    await animateBoot(2600);

    d.bootStatus.textContent = '온라인';
    d.boot.classList.add('boot--gone');
    setTimeout(() => { d.boot.hidden = true; }, 1000);

    d.hudPanel.hidden = false;
    J.state.bootDone = true;
    await J.loadLatestSession();
    greet();
  };

})(window.JARVIS);