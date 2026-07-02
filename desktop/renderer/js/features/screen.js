'use strict';

/**
 * @file 화면 인식 모듈 — 앱 시작 시 자동으로 주 화면 전체를 일정 간격으로 캡처,
 *       변화가 있으면 /chat/screen 으로 보내 능동 발화한다 (사용자 토글 없음).
 */
window.Jarvis = window.Jarvis || {};

Jarvis.screen = (() => {
  const DEBUG = false;
  const HTTP_POST = 'POST';
  const JSON_HEADERS = { 'Content-Type': 'application/json' };
  const CHROME_MEDIA_SOURCE = 'desktop';

  const CAPTURE_INTERVAL_MS = 5000;
  const MAX_DIM = 1280;
  const SAMPLE_SIZE = 64;
  const SAMPLE_STRIDE = 16;
  const HASH_MULT = 31;
  const HASH_MASK = 0xffffffff;
  const HASH_RADIX = 36;
  const JPEG_MIME = 'image/jpeg';
  const JPEG_QUALITY = 0.7;
  const SEND_TIMEOUT_MS = 65000;
  const SPEAK_INTERVAL_MS = 10000;

  let running = false;
  let analyzing = false;
  let stream = null;
  let video = null;
  let prevHash = null;
  let lastSpokenAt = 0;
  let timer = null;

  let workCanvas = null;
  let workCtx = null;

  /**
   * 주 화면 소스를 받아 자동 캡처를 시작한다 (앱 부팅 시 1회 호출).
   * 사용자 제스처 없이 동작하도록 getUserMedia + chromeMediaSourceId 사용.
   * 
   * @returns {Promise<void>}
   */
  async function start() {
    if (running) return;
    try {
      const sourceId = await window.electronAPI?.getScreenSource();
      if (!sourceId) { console.warn('[Screen] 화면 소스를 찾지 못함'); return; }

      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { mandatory: { chromeMediaSource: CHROME_MEDIA_SOURCE, chromeMediaSourceId: sourceId } },
      });
      stream.getVideoTracks()[0].onended = stop;

      video = document.createElement('video');
      video.srcObject = stream;
      video.muted = true;
      await video.play();

      running = true;
      if (DEBUG) {
        const s = stream.getVideoTracks()[0].getSettings();
        console.log(`[Screen] 자동 캡처 시작 — ${s.width}x${s.height}, ${CAPTURE_INTERVAL_MS / 1000}초 간격`);
      }
      _tick();
    } catch (e) {
      console.warn('[Screen] 자동 화면 인식 시작 실패:', e);
      stop();
    }
  }

  /**
   * 캡처를 정지하고 스트림·video·타이머를 해제한다.
   * 
   * @returns {void}
   */
  function stop() {
    running = false;
    if (timer) { clearTimeout(timer); timer = null; }
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
    if (video) {
      video.srcObject = null;
      video = null;
    }
    prevHash = null;
  }

  /**
   * 일정 간격으로 캡처·분석을 예약하는 타이머 루프.
   * 
   * @returns {void}
   */
  function _tick() {
    if (!running) return;
    timer = setTimeout(async () => {
      if (!analyzing) {
        analyzing = true;
        try {
          await _captureAndAnalyze();
        } catch (e) {
          console.warn('[Screen] 분석 오류:', e);
        } finally {
          analyzing = false;
        }
      }
      _tick();
    }, CAPTURE_INTERVAL_MS);
  }

  /**
   * 재사용 작업 캔버스의 2D 컨텍스트를 반환한다 (필요 시 크기만 조정).
   * 
   * @param {number} w - 너비
   * @param {number} h - 높이
   * @returns {CanvasRenderingContext2D}
   */
  function _getCtx(w, h) {
    if (!workCanvas) {
      workCanvas = document.createElement('canvas');
      workCtx = workCanvas.getContext('2d');
    }
    if (workCanvas.width !== w) workCanvas.width = w;
    if (workCanvas.height !== h) workCanvas.height = h;
    return workCtx;
  }

  /**
   * 샘플 픽셀을 스트라이드로 훑어 프레임 해시를 계산한다 (중간 배열 미할당).
   * 
   * @param {Uint8ClampedArray} data - ImageData.data
   * @returns {string} 해시 문자열
   */
  function _hashSample(data) {
    let hash = 0;
    for (let i = 0; i < data.length; i += SAMPLE_STRIDE) {
      hash = (hash * HASH_MULT + data[i]) & HASH_MASK;
    }
    return hash.toString(HASH_RADIX);
  }

  /**
   * 현재 video 프레임을 리사이즈·해시 비교하고, 변화가 있으면 서버로 보내 능동 발화한다.
   * busy/recording 중이거나 이전과 동일 프레임이면 건너뛴다.
   * 
   * @returns {Promise<void>}
   */
  async function _captureAndAnalyze() {
    if (Jarvis.state.get(Jarvis.KEYS.BUSY) || Jarvis.state.get(Jarvis.KEYS.RECORDING)) return;
    if (!video || !video.videoWidth) return;

    // 리사이즈 + 변화 해시 + 압축
    const sw = video.videoWidth;
    const sh = video.videoHeight;
    const ratio = Math.min(MAX_DIM / sw, MAX_DIM / sh, 1);
    const w = Math.round(sw * ratio);
    const h = Math.round(sh * ratio);
    const ctx = _getCtx(w, h);
    ctx.drawImage(video, 0, 0, w, h);

    const sample = ctx.getImageData(0, 0, Math.min(w, SAMPLE_SIZE), Math.min(h, SAMPLE_SIZE));
    const hash = _hashSample(sample.data);
    if (hash === prevHash) return;
    prevHash = hash;

    const image_b64 = workCanvas.toDataURL(JPEG_MIME, JPEG_QUALITY).split(',')[1];
    if (DEBUG) console.log(`[Screen] 변화 감지 → 분석 요청 (${w}x${h}, ${Math.round(image_b64.length / 1024)}KB)`);

    // 서버 전송
    let data;
    const t0 = Date.now();
    try {
      const res = await Jarvis.api.fetchWithTimeout(
        Jarvis.api.chatScreen,
        {
          method : HTTP_POST,
          headers: JSON_HEADERS,
          body   : JSON.stringify({ image_b64, session_id: Jarvis.state.get(Jarvis.KEYS.SESSION_ID) }),
        },
        SEND_TIMEOUT_MS
      );
      data = await res.json();
    } catch (e) {
      // 타임아웃(AbortError) 포함 모든 실패 표시 — 원인 진단용
      console.warn(`[Screen] 전송 실패 (${Date.now() - t0}ms, ${e.name}): ${e.message || e}`);
      return;
    }
    if (DEBUG) console.log(`[Screen] 서버 응답 (${Date.now() - t0}ms) — speak:`, data.speak || '(없음)');

    // 능동 발화 (간격 제한)
    const now = Date.now();
    if (data.speak && data.audio_b64 &&
        (now - lastSpokenAt) >= SPEAK_INTERVAL_MS && !Jarvis.state.get(Jarvis.KEYS.BUSY)) {
      lastSpokenAt = now;
      Jarvis.avatar.playAudio(data.audio_b64, data.speak);
    }
  }

  // 종료 시 캡처 정지 + 작업 캔버스 해제
  Jarvis.bus.on(Jarvis.EVENTS.TEARDOWN, () => {
    stop();
    workCanvas = null;
    workCtx = null;
  });

  return { start, stop };
})();