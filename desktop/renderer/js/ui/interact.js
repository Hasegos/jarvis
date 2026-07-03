'use strict';

/**
 * @file 상호작용 모듈 — 드래그 이동, click-through(투명 픽셀 통과), 탭 반응.
 */
window.Jarvis = window.Jarvis || {};

Jarvis.interact = (() => {
  /** @constant {string[]} 캐릭터를 탭했을 때 랜덤 반응 문구 */
  const TAP_REACTIONS = [
    '응? 뭐야~ 건드리지 마세요!',
    '헤헤, 간지럽다고요~',
    '주인님! 저 여기 있어요!',
    '어, 어! 깜짝이야~',
    '...지금 나 건드렸죠?',
    '뭔가 필요하신 거 있어요?',
    '히히, 또 건드렸어~',
    '주인님이 관심 줬다!',
    '저 지금 열심히 대기 중이에요.',
  ];

  const HIT_INTERVAL_MS = 50;
  const ALPHA_THRESHOLD = 15;
  const TAP_BUBBLE_MS = 4000;
  const TTS_TIMEOUT_MS = 20000;
  const HTTP_POST = 'POST';
  const JSON_HEADERS = { 'Content-Type': 'application/json' };
  const LEFT_BUTTON = 0;
  const LEFT_BUTTON_MASK = 1;
  const DRAG_MOVE_THRESHOLD = 4;
  const CANVAS_SELECTOR = '.avatar-canvas';
  const INTERACTIVE_SELECTOR = 'button, input, .confirm, .opacity-popup';
  const GL_CONTEXTS = ['webgl2', 'webgl', 'experimental-webgl'];

  let _ignoring = false;
  let _lastHitMs = 0;
  let _gl = null;
  let _glCanvas = null;
  const _pixel = new Uint8Array(4);

  let _dragging = false;
  let _dragPending = false;
  let _prevButtonDown = false;
  let _dragMouseStart = null;
  let _dragWinStart = null;
  let _didDrag = false;
  let _moved = false;

  /**
   * 캔버스의 WebGL 컨텍스트를 지연 획득/캐시한다.
   * 
   * @returns {WebGLRenderingContext|WebGL2RenderingContext|null}
   */
  function _getGL() {
    if (_gl) return _gl;
    _glCanvas = document.querySelector(CANVAS_SELECTOR);
    if (_glCanvas) {
      for (const name of GL_CONTEXTS) {
        _gl = _glCanvas.getContext(name);
        if (_gl) break;
      }
    }
    return _gl;
  }

  /**
   * 해당 좌표의 캔버스 픽셀이 (거의) 투명한지 판정한다.
   * 
   * @param {number} x - clientX
   * @param {number} y - clientY
   * @returns {boolean} 투명(=클릭 통과 대상) 여부
   */
  function _isTransparentPixel(x, y) {
    const gl = _getGL();
    if (!gl || !_glCanvas) return true;
    const dpr = window.devicePixelRatio || 1;
    try {
      gl.readPixels(Math.round(x * dpr), _glCanvas.height - Math.round(y * dpr), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, _pixel);
      return _pixel[3] < ALPHA_THRESHOLD;
    } catch { return true; }
  }

  /**
   * 좌표에 버튼·입력·패널 등 상호작용 요소가 있는지 확인한다.
   * 
   * @param {number} x - clientX
   * @param {number} y - clientY
   * @returns {boolean}
   */
  function _isInteractive(x, y) {
    const el = document.elementFromPoint(x, y);
    if (!el || el === document.documentElement || el === document.body) return false;
    return !!el.closest(INTERACTIVE_SELECTOR);
  }

  /**
   * 스로틀링된 히트 테스트 — 투명 영역이면 창을 클릭 통과 상태로 전환한다.
   * 
   * @param {number} x - clientX
   * @param {number} y - clientY
   * @returns {void}
   */
  function _hitTest(x, y) {
    const now = Date.now();
    if (now - _lastHitMs < HIT_INTERVAL_MS) return;
    _lastHitMs = now;
    const shouldIgnore = !_isInteractive(x, y) && _isTransparentPixel(x, y);
    if (shouldIgnore !== _ignoring) {
      _ignoring = shouldIgnore;
      window.electronAPI?.setIgnoreMouse(shouldIgnore);
    }
  }

  /**
   * 현재 창 bounds를 비동기 조회해 드래그 기준점을 설정한다.
   * 
   * @param {number} screenX - 시작 시점 screenX
   * @param {number} screenY - 시작 시점 screenY
   * @returns {Promise<void>}
   */
  async function _startDragFrom(screenX, screenY) {
    if (_dragPending || _dragging) return;
    _dragPending = true;
    const snapX = screenX;
    const snapY = screenY;
    try {
      const b = await window.electronAPI?.getBounds();
      if (b && _dragPending) {
        _dragging = true;
        _dragPending = false;
        _dragMouseStart = { x: snapX, y: snapY };
        _dragWinStart = { x: b.x, y: b.y };
        Jarvis.bus.emit(Jarvis.EVENTS.DRAG, true);   // 자율 이동 일시정지 신호
      }
    } catch {
      _dragPending = false;   // getBounds 실패 시 드래그 취소
    }
  }

  /**
   * 드래그 상태를 초기화한다.
   * 
   * @returns {void}
   */
  function _stopDrag() {
    const wasDragging = _dragging;
    _dragging = false;
    _dragPending = false;
    _prevButtonDown = false;
    _dragMouseStart = null;
    _dragWinStart = null;
    if (wasDragging) Jarvis.bus.emit(Jarvis.EVENTS.DRAG, false);   // 자율 이동 재개 신호
  }

  /**
   * 랜덤 탭 반응을 말풍선 + 표정 + 음성(TTS)으로 표현한다.
   * 응답/발화 중(busy)이면 음성은 생략하고 시각 반응만 한다.
   * 
   * @returns {Promise<void>}
   */
  async function _tapReact() {
    const msg = TAP_REACTIONS[Math.floor(Math.random() * TAP_REACTIONS.length)];
    Jarvis.avatar.showBubble(msg, TAP_BUBBLE_MS);           // 즉시 말풍선 (TTS 실패해도 유지)
    Jarvis.avatar.setEmotion(Jarvis.emotion.detect(msg));   // 즉시 감정 표정

    if (Jarvis.state.get(Jarvis.KEYS.BUSY)) return;         // 응답/발화 중이면 시각 반응만 (음성 훼방 금지)
    Jarvis.avatar.interruptAudio();                         // 진행 중 발화(능동 발화 등) 중단
    Jarvis.state.set(Jarvis.KEYS.BUSY, true);
    try {
      const res = await Jarvis.api.fetchWithTimeout(
        Jarvis.api.tts,
        { method: HTTP_POST, headers: JSON_HEADERS, body: JSON.stringify({ text: msg }) },
        TTS_TIMEOUT_MS,
      );
      const tJson = performance.now();
      const data = await res.json();
      Jarvis.api.perfLog('tap-tts json 파싱', tJson);
      if (data.audio_b64) await Jarvis.avatar.playAudio(data.audio_b64, msg);   // 립싱크 + 재생
    } catch (e) {
      console.warn('[interact] 탭 TTS 실패:', e);            // 백엔드 미기동 등 — 말풍선만 유지
    } finally {
      Jarvis.state.set(Jarvis.KEYS.BUSY, false);
    }
  }

  const scope = Jarvis.dom.createScope();

  // mousedown: 캐릭터 영역(setIgnoreMouse=false)에서 드래그 시작
  scope.on(document, 'mousedown', (e) => {
    if (e.button !== LEFT_BUTTON) return;
    if (_isInteractive(e.clientX, e.clientY)) return;
    _didDrag = false;
    _moved = false;
    _startDragFrom(e.screenX, e.screenY);
  });

  scope.on(document, 'mouseup', (e) => {
    if (e.button !== LEFT_BUTTON) return;
    if (_dragging && _moved) _didDrag = true;
    _stopDrag();
    _lastHitMs = 0;
    _hitTest(e.clientX, e.clientY);
  });

  scope.on(document, 'mousemove', (e) => {
    const buttonDown = !!(e.buttons & LEFT_BUTTON_MASK);

    if (_dragging) {
      if (!buttonDown) {
        if (_moved) _didDrag = true;
        _stopDrag();
        _hitTest(e.clientX, e.clientY);
      } else if (_dragMouseStart && _dragWinStart) {
        const dx = e.screenX - _dragMouseStart.x;
        const dy = e.screenY - _dragMouseStart.y;
        if (Math.abs(dx) > DRAG_MOVE_THRESHOLD || Math.abs(dy) > DRAG_MOVE_THRESHOLD) _moved = true;
        window.electronAPI?.moveWindow(_dragWinStart.x + dx, _dragWinStart.y + dy);
      }
      _prevButtonDown = buttonDown;
      return;
    }

    if (_dragPending) {
      if (!buttonDown) _stopDrag();
      _prevButtonDown = buttonDown;
      return;
    }

    if (buttonDown && !_prevButtonDown && !_isInteractive(e.clientX, e.clientY)) {
      _didDrag = false;
      _startDragFrom(e.screenX, e.screenY);
    }

    _prevButtonDown = buttonDown;
    if (!buttonDown) _hitTest(e.clientX, e.clientY);
  });

  scope.on(document, 'click', (e) => {
    if (_didDrag) { _didDrag = false; return; }
    if (_isInteractive(e.clientX, e.clientY)) return;
    if (!_isTransparentPixel(e.clientX, e.clientY)) _tapReact();
  });

  scope.on(window, 'blur', _stopDrag);

  /**
   * 등록된 모든 리스너를 해제한다. app:teardown 시 호출.
   * 
   * @returns {void}
   */
  function destroy() {
    scope.dispose();
    _gl = null;         // WebGL 컨텍스트 참조 해제
    _glCanvas = null;
  }

  Jarvis.bus.on(Jarvis.EVENTS.TEARDOWN, destroy);

  return { destroy };
})();