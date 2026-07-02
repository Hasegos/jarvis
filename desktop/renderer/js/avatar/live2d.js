'use strict';

/**
 * @file Live2D 아바타 모듈 — PIXI 렌더링, 말풍선, 립싱크(입 모션), 가시성/투명도.
 */
window.Jarvis = window.Jarvis || {};

Jarvis.avatar = (() => {
  const MODEL_URL = `${Jarvis.api.BASE}/static/live2d-models/mao_pro/runtime/mao_pro.model3.json`;
  const CANVAS_SELECTOR = '.avatar-canvas';
  const BUBBLE_SELECTOR = '.bubble';
  const BUBBLE_VISIBLE_CLASS = 'bubble--visible';

  const CANVAS_W = 400;
  const CANVAS_H = 700;
  const TARGET_FPS = 30;
  const MODEL_SCALE = 0.06;
  const MODEL_X = 200;
  const MODEL_Y = 350;

  const MOTION_COUNT = 6;
  const EXP_COUNT = 8;
  const EXP_NAME_PREFIX = 'exp_0';
  const IDLE_MOTION_GROUP = '';
  const SPEAK_MOTION_GROUP = 'Idle';
  const MOTION_PRIORITY_NORMAL = 2;
  const MOTION_PRIORITY_FORCE = 3;

  const EMOTION_EXP = {
    happy    : 'exp_01',
    curious  : 'exp_02',
    surprised: 'exp_03',
    sad      : 'exp_04',
    angry    : 'exp_05',
    neutral  : 'exp_06',
  };

  const BUBBLE_MS = 6000;
  const BACKEND_FAIL_MS = 15000;
  const SPEAK_IDLE_DELAY_MS = 3000;
  const IDLE_MIN_MS = 4000;
  const IDLE_RAND_MS = 4000;   // 4~8초 랜덤 간격

  const OPACITY_MIN = 0.2;
  const OPACITY_MAX = 1.0;
  const HIDDEN_OPACITY = '0';

  const BACKEND_FAIL_MSG = '백엔드에 연결할 수 없어 캐릭터를 불러오지 못했습니다.';

  const canvas = Jarvis.dom.$(CANVAS_SELECTOR);
  const bubble = Jarvis.dom.$(BUBBLE_SELECTOR);

  let app = null;
  let model = null;
  let bubbleTimer = null;
  let motionTimer = null;
  let speaking = false;
  let visible = true;
  let opacity = OPACITY_MAX;
  let currentAudio = null;
  let currentDone = null;

  /**
   * PIXI 앱을 생성하고 Live2D 모델을 로드한다.
   * 실패(백엔드 미기동) 시 말풍선으로 알린다.
   * 
   * @returns {Promise<void>}
   */
  async function init() {
    app = new PIXI.Application({
      view                 : canvas,
      transparent          : true,
      backgroundAlpha      : 0,
      autoStart            : true,
      width                : CANVAS_W,
      height               : CANVAS_H,
      preserveDrawingBuffer: true,   // interact.js readPixels 히트테스트에 필요
    });
    app.ticker.maxFPS = TARGET_FPS;

    try {
      model = await PIXI.live2d.Live2DModel.from(MODEL_URL);
      app.stage.addChild(model);

      model.scale.set(MODEL_SCALE);
      model.anchor.set(0.5, 0.5);
      model.position.set(MODEL_X, MODEL_Y);

      _setRandomExpression();
      _idleLoop();
    } catch (e) {
      console.warn('[Live2D] 모델 로드 실패:', e);
      showBubble(BACKEND_FAIL_MSG, BACKEND_FAIL_MS);
    }
  }

  /**
   * 말하는 중이 아닐 때만 랜덤 모션을 재생하는 재귀 타이머 루프.
   * 
   * @returns {void}
   */
  function _idleLoop() {
    if (motionTimer) clearTimeout(motionTimer);
    const delay = speaking ? SPEAK_IDLE_DELAY_MS : IDLE_MIN_MS + Math.random() * IDLE_RAND_MS;
    motionTimer = setTimeout(() => {
      if (!speaking && model) _playRandomMotion();
      _idleLoop();
    }, delay);
  }

  /**
   * "" 그룹에서 랜덤 모션을 1회 재생한다.
   * 
   * @returns {void}
   */
  function _playRandomMotion() {
    if (!model) return;
    const idx = Math.floor(Math.random() * MOTION_COUNT);
    try { model.motion(IDLE_MOTION_GROUP, idx, MOTION_PRIORITY_NORMAL); } catch {}
  }

  /**
   * 랜덤 표정(exp_01~exp_08)을 설정한다.
   * 
   * @returns {void}
   */
  function _setRandomExpression() {
    if (!model) return;
    const idx = Math.floor(Math.random() * EXP_COUNT);
    try { model.expression(`${EXP_NAME_PREFIX}${idx + 1}`); } catch {}
  }

  /**
   * 감정 키에 해당하는 표정을 적용한다.
   * 
   * @param {string} key - 감정 키 (Jarvis.emotion.detect 결과)
   * @returns {void}
   */
  function setEmotion(key) {
    if (!model) return;
    const exp = EMOTION_EXP[key] || EMOTION_EXP.neutral;
    try { model.expression(exp); } catch {}
  }

  /**
   * 말풍선을 표시하고 일정 시간 뒤 숨긴다.
   * 
   * @param {string} text - 표시할 문구
   * @param {number} [ms] - 유지 시간(ms)
   * @returns {void}
   */
  function showBubble(text, ms = BUBBLE_MS) {
    if (bubbleTimer) clearTimeout(bubbleTimer);
    bubble.textContent = String(text);
    bubble.classList.add(BUBBLE_VISIBLE_CLASS);
    bubbleTimer = setTimeout(() => bubble.classList.remove(BUBBLE_VISIBLE_CLASS), ms);
  }

  /**
   * 말풍선을 즉시 숨긴다.
   * 
   * @returns {void}
   */
  function hideBubble() {
    if (bubbleTimer) clearTimeout(bubbleTimer);
    bubble.classList.remove(BUBBLE_VISIBLE_CLASS);
  }

  /**
   * 발화 시작 — 입 모션 + 표정 변경.
   * 
   * @returns {void}
   */
  function startSpeaking() {
    if (!model) { speaking = true; return; }
    speaking = true;
    try { model.motion(SPEAK_MOTION_GROUP, 0, MOTION_PRIORITY_FORCE); } catch {}
    _setRandomExpression();
  }

  /**
   * 발화 종료 — 랜덤 모션으로 복귀.
   * 
   * @returns {void}
   */
  function stopSpeaking() {
    speaking = false;
    if (!model) return;
    _playRandomMotion();
    _setRandomExpression();
  }

  /**
   * base64 오디오를 재생하며 립싱크(입 모션)를 수행한다. 종료/오류 시 버퍼를 해제한다.
   * 
   * @param {string} b64 - audio_b64 (base64 또는 data URI)
   * @param {string} [text] - 함께 표시할 말풍선 문구
   * @returns {Promise<void>} 재생 종료 시 resolve
   */
  function playAudio(b64, text) {
    interruptAudio();
    return new Promise((resolve) => {
      if (!Jarvis.util.validateAudioB64(b64)) { resolve(); return; }

      const perfStart = performance.now();
      const audio = new Audio(Jarvis.util.toAudioSrc(b64));
      audio.addEventListener('playing', () => Jarvis.api.perfLog('audio 재생 시작(디코딩)', perfStart), { once: true });
      currentAudio = audio;
      startSpeaking();
      if (text) {
        showBubble(text);
        setEmotion(Jarvis.emotion.detect(text));   // startSpeaking의 랜덤 표정 덮어씀
      }

      let settled = false;
      const done = () => {
        if (settled) return;
        settled = true;
        audio.onended = null;
        audio.onerror = null;
        try { audio.pause(); } catch {}    // 중단(barge-in) 시 즉시 정지
        audio.src = '';                    // 버퍼 해제 (메모리 누수 방지)
        if (currentAudio === audio) { currentAudio = null; currentDone = null; }
        stopSpeaking();
        resolve();
      };
      currentDone = done;
      audio.onended = done;
      audio.onerror = done;
      audio.play().catch(done);
    });
  }

  /**
   * 재생 중인 TTS를 즉시 중단한다 (barge-in). 재생 없으면 무시.
   * 
   * @returns {void}
   */
  function interruptAudio() {
    if (currentDone) currentDone();
  }

  /**
   * 모델 렌더 알파를 설정한다 (텔레포트 페이드용, 사용자 투명도와 독립).
   * 
   * @param {number} a - 0~1
   * @returns {void}
   */
  function setModelAlpha(a) {
    if (model) model.alpha = a;
  }

  /**
   * 캐릭터 투명도를 설정한다 (완전 투명 방지 위해 하한 적용).
   * 
   * @param {number} val - 0.2~1.0
   * @returns {void}
   */
  function setOpacity(val) {
    opacity = Math.max(OPACITY_MIN, Math.min(OPACITY_MAX, val));
    if (visible) canvas.style.opacity = opacity;
  }

  /**
   * 캐릭터 표시/숨김을 토글한다.
   * 
   * @returns {boolean} 토글 후 표시 여부
   */
  function toggleVisibility() {
    visible = !visible;
    canvas.style.opacity = visible ? opacity : HIDDEN_OPACITY;
    if (!visible) hideBubble();
    return visible;
  }

  /**
   * 타이머·오디오·PIXI/모델을 해제한다 (메모리 누수 방지). app:teardown 시 호출.
   * 
   * @returns {void}
   */
  function destroy() {
    interruptAudio();   // 재생 중이면 정리 + 대기 중인 playAudio promise 해소
    if (motionTimer) clearTimeout(motionTimer);
    if (bubbleTimer) clearTimeout(bubbleTimer);
    motionTimer = null;
    bubbleTimer = null;
    if (currentAudio) {
      currentAudio.onended = null;
      currentAudio.onerror = null;
      try { currentAudio.pause(); } catch {}
      currentAudio.src = '';
      currentAudio = null;
    }
    try { model?.destroy(); } catch {}
    try { app?.destroy(true, { children: true, texture: true, baseTexture: true }); } catch {}
    model = null;
    app = null;
  }

  Jarvis.bus.on(Jarvis.EVENTS.TEARDOWN, destroy);

  return {
    init, showBubble, hideBubble,
    startSpeaking, stopSpeaking, playAudio, interruptAudio,
    setEmotion, setModelAlpha, setOpacity, toggleVisibility, destroy,
    isSpeaking: () => speaking,
    isVisible : () => visible,
  };
})();