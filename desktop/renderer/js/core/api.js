'use strict';

/**
 * @file 백엔드 API 엔드포인트 + 공통 fetch 래퍼 + 오디오 유틸
 */
window.Jarvis = window.Jarvis || {};

Jarvis.api = (() => {
  const BASE = window.electronAPI?.backendUrl || 'http://localhost:8000';
  const DEFAULT_TIMEOUT_MS = 30000;
  const PERF = true;   // 성능 계측 로그 스위치 — true 시 콘솔에 구간별 ms 출력

  /**
   * 성능 계측 로그를 출력한다 (PERF=true일 때만). 경로·구간명·ms만 기록,
   * 요청/응답 본문은 절대 남기지 않는다.
   * 
   * @param {string} label - 구간 이름
   * @param {number} startMs - performance.now() 시작 시각
   * @returns {void}
   */
  function perfLog(label, startMs) {
    if (PERF) console.info(`[perf] ${label}: ${Math.round(performance.now() - startMs)}ms`);
  }

  /**
   * AbortController 기반 타임아웃 fetch. 응답이 실패(!ok)면 예외를 던진다.
   *
   * @param {string} url - 요청 URL
   * @param {RequestInit} [options] - fetch 옵션
   * @param {number} [timeoutMs] - 타임아웃(ms)
   * @returns {Promise<Response>} 성공 응답
   * @throws {Error} 타임아웃(AbortError) 또는 HTTP 오류
   */
  async function fetchWithTimeout(url, options = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), timeoutMs);
    const t0 = performance.now();
    try {
      const res = await fetch(url, { ...options, signal: ctrl.signal });
      perfLog(`fetch ${new URL(url).pathname} (HTTP ${res.status})`, t0);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res;
    } catch (e) {
      perfLog(`fetch ${new URL(url).pathname} 실패 (${e.name})`, t0);
      throw e;
    } finally {
      clearTimeout(tid);
    }
  }

  return {
    BASE,
    chatStream  : `${BASE}/api/v1/chat/stream`,
    chatScreen  : `${BASE}/api/v1/chat/screen`,
    chatConfirm : `${BASE}/api/v1/chat/confirm`,
    chatSessions: `${BASE}/api/v1/chat/sessions`,
    voice       : `${BASE}/api/v1/voice`,
    tts         : `${BASE}/api/v1/voice/tts`,
    fetchWithTimeout,
    perfLog,
  };
})();

Jarvis.util = (() => {
  const AUDIO_DATA_PREFIX = 'data:';
  const AUDIO_MIME_PREFIX = 'data:audio/';
  const BASE64_RE = /^[A-Za-z0-9+/]+=*$/;
  const MP3_DATA_URI = 'data:audio/mp3;base64,';

  /**
   * audio_b64 포맷을 검증한다 (data:audio/ URI 또는 순수 base64).
   * 
   * @param {string} b64 - 검증할 문자열
   * @returns {boolean} 유효 여부
   */
  function validateAudioB64(b64) {
    if (!b64 || typeof b64 !== 'string') return false;
    if (b64.startsWith(AUDIO_DATA_PREFIX)) return b64.startsWith(AUDIO_MIME_PREFIX);
    return BASE64_RE.test(b64);
  }

  /**
   * audio_b64를 재생용 src(data URI)로 변환한다.
   * 
   * @param {string} b64 - base64 또는 data URI
   * @returns {string} 재생 가능한 src
   */
  function toAudioSrc(b64) {
    return b64.startsWith(AUDIO_DATA_PREFIX) ? b64 : `${MP3_DATA_URI}${b64}`;
  }

  return { validateAudioB64, toAudioSrc };
})();